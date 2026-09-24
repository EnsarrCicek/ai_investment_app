from types import SimpleNamespace

from app.models.asset import Asset
from app.services.jobs import daily_analysis as job_module
from app.services.jobs.daily_analysis import run_daily_analysis


def _asset(symbol: str) -> Asset:
    return Asset(symbol=symbol, name=symbol, market="BIST", asset_type="STOCK", currency="TRY")


class _FakeAssetRepo:
    def __init__(self, symbols):
        self._symbols = symbols

    def list_active(self):
        return [_asset(s) for s in self._symbols]


class _FakeDecisionEngine:
    def __init__(self, raise_for: set[str] | None = None):
        self._raise_for = raise_for or set()
        self.calls: list[str] = []

    def decide_for_asset(self, symbol):
        self.calls.append(symbol)
        if symbol in self._raise_for:
            raise ValueError(f"'{symbol}' için hiçbir analiz skoru mevcut değil")
        return SimpleNamespace(asset=symbol, decision="BUY", final_score=50.0, confidence=80.0)


class _FakeEventEngine:
    def __init__(self, raise_from_call: int | None = None, error: Exception | None = None):
        self.calls: list[str] = []
        self._raise_from_call = raise_from_call
        self._error = error

    def analyze_recent_for_asset(self, symbol):
        self.calls.append(symbol)
        if self._raise_from_call is not None and len(self.calls) > self._raise_from_call:
            raise self._error
        return []


class _FakeTokenRepo:
    def __init__(self, user_ids):
        self._user_ids = user_ids

    def list_all_user_ids(self):
        return self._user_ids


class _FakePortfolioRepo:
    def __init__(self, holdings: dict[tuple[str, str], float]):
        self._holdings = holdings

    def get_position_for_asset(self, user_id, asset):
        quantity = self._holdings.get((user_id, asset))
        return None if quantity is None else SimpleNamespace(quantity=quantity)


class _FakeNewsRawRepo:
    def __init__(self):
        self.upserted = []

    def upsert(self, item):
        self.upserted.append(item)


class _FakeForeksProvider:
    def __init__(self, items=None, raise_error: bool = False):
        self._items = items or []
        self._raise_error = raise_error

    def get_market_news(self, limit=100):
        if self._raise_error:
            raise RuntimeError("Foreks geçici olarak erişilemiyor")
        return self._items


def _run(
    symbols=("THYAO", "GARAN"),
    user_ids=(),
    holdings=None,
    decision_raise_for=None,
    foreks_items=None,
    foreks_raises=False,
    event_engine=None,
):
    decision_engine = _FakeDecisionEngine(raise_for=decision_raise_for)
    result = run_daily_analysis(
        asset_repo=_FakeAssetRepo(symbols),
        decision_engine=decision_engine,
        event_engine=event_engine if event_engine is not None else _FakeEventEngine(),
        token_repo=_FakeTokenRepo(list(user_ids)),
        portfolio_repo=_FakePortfolioRepo(holdings or {}),
        news_raw_repo=_FakeNewsRawRepo(),
        foreks_provider=_FakeForeksProvider(foreks_items, raise_error=foreks_raises),
        fetch_news=lambda symbol, limit: [],
    )
    return result, decision_engine


def test_processes_all_active_assets_and_persists_decisions():
    result, decision_engine = _run(symbols=("THYAO", "GARAN", "TUPRS"))

    assert result["total_assets"] == 3
    assert result["processed"] == 3
    assert decision_engine.calls == ["THYAO", "GARAN", "TUPRS"]


def test_one_asset_error_does_not_abort_the_rest():
    result, decision_engine = _run(symbols=("THYAO", "BROKEN", "TUPRS"), decision_raise_for={"BROKEN"})

    assert result["processed"] == 2
    assert result["errors"] == [{"asset": "BROKEN", "error": "'BROKEN' için hiçbir analiz skoru mevcut değil"}]
    # BROKEN'daki hataya rağmen TUPRS'a kadar devam edildi
    assert decision_engine.calls == ["THYAO", "BROKEN", "TUPRS"]


def test_budget_exhaustion_stops_news_analysis_but_decisions_continue():
    from app.engines.event_intelligence.budget import BudgetExhaustedError

    event_engine = _FakeEventEngine(raise_from_call=1, error=BudgetExhaustedError("yetersiz"))

    result, decision_engine = _run(symbols=("THYAO", "GARAN", "TUPRS"), event_engine=event_engine)

    assert event_engine.calls == ["THYAO", "GARAN"]  # tükendikten sonra motor bir daha çağrılmaz
    assert result["news_analysis_skipped_budget"] == ["GARAN", "TUPRS"]
    assert result["news_analysis_stop_reason"] == "BUDGET_EXHAUSTED"
    assert decision_engine.calls == ["THYAO", "GARAN", "TUPRS"]
    assert result["errors"] == []


def test_unreadable_budget_state_stops_news_analysis_with_explicit_reason():
    from app.engines.event_intelligence.budget import BudgetUnavailableError

    event_engine = _FakeEventEngine(raise_from_call=0, error=BudgetUnavailableError("okunamadı"))

    result, _ = _run(symbols=("THYAO", "GARAN"), event_engine=event_engine)

    assert event_engine.calls == ["THYAO"]
    assert result["news_analysis_stop_reason"] == "BUDGET_STATE_UNAVAILABLE"
    assert result["news_analysis_skipped_budget"] == ["THYAO", "GARAN"]


def test_analyzes_news_when_budget_available():
    event_engine = _FakeEventEngine()

    result, _ = _run(symbols=("THYAO", "GARAN"), event_engine=event_engine)

    assert event_engine.calls == ["THYAO", "GARAN"]
    assert result["news_analysis_skipped_budget"] == []
    assert result["news_analysis_stop_reason"] is None


def test_notifies_holding_user_as_strong_decision_and_non_holder_as_new_opportunity(monkeypatch):
    strong_calls = []
    opportunity_calls = []
    monkeypatch.setattr(
        job_module, "notify_if_strong_decision", lambda user_id, decision, quantity_held=None: strong_calls.append(
            (user_id, decision.asset, quantity_held)
        )
    )
    monkeypatch.setattr(
        job_module, "notify_if_new_opportunity", lambda user_id, decision: opportunity_calls.append(
            (user_id, decision.asset)
        )
    )

    _run(symbols=("THYAO",), user_ids=("holder", "non_holder"), holdings={("holder", "THYAO"): 10.0})

    assert strong_calls == [("holder", "THYAO", 10.0)]
    assert opportunity_calls == [("non_holder", "THYAO")]


def test_foreks_market_news_fetched_once_and_upserted():
    from app.models.news_raw import NewsRawItem
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    item = NewsRawItem(
        external_id="foreks:abc",
        title="t",
        summary="s",
        url="https://example.com",
        publisher="Foreks",
        source="foreks",
        source_reliability=0.8,
        related_assets=["THYAO"],
        published_at=now,
        received_at=now,
    )
    news_raw_repo = _FakeNewsRawRepo()
    run_daily_analysis(
        asset_repo=_FakeAssetRepo(()),
        decision_engine=_FakeDecisionEngine(),
        event_engine=_FakeEventEngine(),
        token_repo=_FakeTokenRepo([]),
        portfolio_repo=_FakePortfolioRepo({}),
        news_raw_repo=news_raw_repo,
        foreks_provider=_FakeForeksProvider([item]),
        fetch_news=lambda symbol, limit: [],
    )

    assert news_raw_repo.upserted == [item]


def test_foreks_failure_does_not_abort_job():
    result, decision_engine = _run(symbols=("THYAO",), foreks_raises=True)

    assert result["processed"] == 1
    assert decision_engine.calls == ["THYAO"]


def test_make_event_engine_returns_none_without_openai_key(monkeypatch):
    from app.engines.event_intelligence import engine as engine_module

    monkeypatch.setattr(engine_module, "OPENAI_API_KEY", None)

    assert job_module._make_event_engine() is None
