"""EventIntelligence merkezi OpenAI bütçe kapısı.

Sahte OpenAI istemcisi ve sahte Firestore (tests/event_budget_fakes.py) kullanılır;
sahte transaction'lar tek kilitle sıralı çalışır — bu testler MANTIĞI doğrular,
gerçek Firestore eşzamanlılık davranışının kanıtı DEĞİLDİR.
"""

import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import news_analysis as news_analysis_api
from app.engines.event_intelligence import engine as engine_module
from app.engines.event_intelligence.budget import (
    MAX_COMPLETION_TOKENS,
    BudgetExhaustedError,
    BudgetUnavailableError,
    estimate_max_cost_usd,
)
from app.engines.event_intelligence.engine import EventIntelligenceEngine
from app.models.news_raw import NewsRawItem
from app.repositories.event_intelligence_budget_repository import (
    LEDGER_COLLECTION,
    RESERVATIONS_COLLECTION,
    RESERVED,
    SETTLED,
    UNCERTAIN,
)
from app.services.jobs.daily_analysis import run_daily_analysis
from tests.event_budget_fakes import FakeFirestore, make_test_budget

MODEL = "gpt-5.6-luna"
_VALID = {"sentiment_score": 60.0, "confidence": 0.8, "importance": 0.5, "event_type": "earnings", "reasoning": "r"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(engine_module, "fetch_article_text", lambda url, **kwargs: "")


class _Client:
    def __init__(self, *, error=None, content=None, usage="default"):
        self.calls: list[dict] = []
        self._error = error
        self._content = json.dumps(_VALID) if content is None else content
        self._usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100, total_tokens=1100) if usage == "default" else usage
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))], usage=self._usage)


class _AnalysisRepo:
    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.added = []

    def add(self, analysis):
        self.added.append(analysis)

    def get_by_news_id(self, news_id, asset):
        return self.existing.get(news_id)


class _NewsRepo:
    def __init__(self, items):
        self._items = items

    def get_recent(self, symbol, limit=20):
        return self._items[:limit]


def _news(external_id="n1", title="Şirket rekor kâr açıkladı"):
    now = datetime.now(timezone.utc)
    return NewsRawItem(
        external_id=external_id, title=title, summary="özet", url="https://example.com", publisher="P",
        source="yahoo_finance", source_reliability=0.8, related_assets=["THYAO"], published_at=now, received_at=now,
    )


def _engine(client, budget, news=(), analysis_repo=None):
    return EventIntelligenceEngine(
        client=client, analysis_repo=analysis_repo or _AnalysisRepo(), news_repo=_NewsRepo(list(news)),
        budget=budget, primary_model=MODEL,
    )


def _one_call_estimate() -> float:
    """analyze_item'ın gerçekten gönderdiği isteğin rezervasyon tutarı."""
    client = _Client()
    _engine(client, make_test_budget()).analyze_item(_news(), "THYAO")
    return estimate_max_cost_usd(MODEL, client.calls[0])


def _ledger(db):
    return db.collection_docs(LEDGER_COLLECTION)["ledger"]


def _reservations(db):
    return list(db.collection_docs(RESERVATIONS_COLLECTION).values())


# ------------------------------------------------------------------ central gate on both paths


def test_request_carries_mandatory_output_limit_used_by_reservation():
    client = _Client()
    _engine(client, make_test_budget()).analyze_item(_news(), "THYAO")
    assert client.calls[0]["max_completion_tokens"] == MAX_COMPLETION_TOKENS


def test_manual_route_cannot_bypass_budget(monkeypatch):
    client = _Client()
    engine = _engine(client, make_test_budget(budget_usd=0.0), news=[_news()])
    monkeypatch.setattr(news_analysis_api, "EventIntelligenceEngine", lambda: engine)

    with pytest.raises(HTTPException) as exc:
        news_analysis_api.analyze_news("thyao", limit=5, user_id="u")
    assert exc.value.status_code == 402
    assert client.calls == []


def test_manual_route_unreadable_budget_state_is_503_with_zero_calls(monkeypatch):
    db = FakeFirestore()
    db.fail_reads = True
    client = _Client()
    engine = _engine(client, make_test_budget(db=db), news=[_news()])
    monkeypatch.setattr(news_analysis_api, "EventIntelligenceEngine", lambda: engine)

    with pytest.raises(HTTPException) as exc:
        news_analysis_api.analyze_news("thyao", limit=5, user_id="u")
    assert exc.value.status_code == 503
    assert client.calls == []


class _Decisions:
    def __init__(self):
        self.calls = []

    def decide_for_asset(self, symbol):
        self.calls.append(symbol)
        return SimpleNamespace(asset=symbol, decision="HOLD", final_score=0.0, confidence=50.0)


def _daily(engine, symbols):
    decisions = _Decisions()
    result = run_daily_analysis(
        asset_repo=SimpleNamespace(list_active=lambda: [SimpleNamespace(symbol=s) for s in symbols]),
        decision_engine=decisions,
        event_engine=engine,
        token_repo=SimpleNamespace(list_all_user_ids=lambda: []),
        portfolio_repo=SimpleNamespace(),
        news_raw_repo=SimpleNamespace(upsert=lambda item: None),
        foreks_provider=SimpleNamespace(get_market_news=lambda limit=100: []),
        fetch_news=lambda symbol, limit: [],
    )
    return result, decisions


def test_daily_job_goes_through_the_same_gate_and_stops_when_budget_runs_out():
    estimate = _one_call_estimate()
    # Gerçek kullanım tahmine yakın (çıktı sınırına kadar): uzlaştırmadan sonra
    # kalan bütçe ikinci çağrıya yetmez.
    client = _Client(usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=MAX_COMPLETION_TOKENS, total_tokens=1000 + MAX_COMPLETION_TOKENS))
    # Tam bir çağrıya yetecek bütçe: 1. varlık analiz edilir, 2. varlıkta job
    # içinde tükenir (başlangıç kontrolü yok, kapı her çağrıdan önce).
    engine = _engine(client, make_test_budget(budget_usd=estimate * 1.5), news=[_news()])

    result, decisions = _daily(engine, ["THYAO", "GARAN", "TUPRS"])

    assert len(client.calls) == 1
    assert result["news_analysis_stop_reason"] == "BUDGET_EXHAUSTED"
    assert result["news_analysis_skipped_budget"] == ["GARAN", "TUPRS"]
    assert decisions.calls == ["THYAO", "GARAN", "TUPRS"]


# ------------------------------------------------------------------ exhaustion + preservation


def test_exhausted_budget_makes_zero_calls_and_keeps_existing_analyses():
    existing = SimpleNamespace(news_id="old", asset="THYAO")
    repo = _AnalysisRepo(existing={"old": existing})
    client = _Client()
    engine = _engine(client, make_test_budget(budget_usd=0.0), news=[_news("old", "Eski olay başlığı tamamen"), _news("new", "Yeni bambaşka gelişme duyuruldu")], analysis_repo=repo)

    with pytest.raises(BudgetExhaustedError):
        engine.analyze_recent_for_asset("THYAO")
    assert client.calls == []
    assert repo.added == []
    assert repo.existing == {"old": existing}


def test_ledger_is_seeded_from_existing_all_time_usage_logs():
    db = FakeFirestore()
    db.docs[("token_usage_logs", "legacy")] = {"cost_usd": 4.999}
    client = _Client()

    with pytest.raises(BudgetExhaustedError):
        _engine(client, make_test_budget(budget_usd=5.0, db=db)).analyze_item(_news(), "THYAO")
    assert client.calls == []


def test_unknown_model_price_blocks_the_call():
    client = _Client()
    engine = EventIntelligenceEngine(
        client=client, analysis_repo=_AnalysisRepo(), news_repo=_NewsRepo([]),
        budget=make_test_budget(), primary_model="unpriced-model",
    )
    with pytest.raises(BudgetUnavailableError):
        engine.analyze_item(_news(), "THYAO")
    assert client.calls == []


def test_database_failure_means_zero_openai_calls():
    db = FakeFirestore()
    db.fail_commits = True
    client = _Client()
    with pytest.raises(BudgetUnavailableError):
        _engine(client, make_test_budget(db=db)).analyze_item(_news(), "THYAO")
    assert client.calls == []


# ------------------------------------------------------------------ concurrency


def test_concurrent_reservations_cannot_spend_the_same_remaining_budget():
    estimate = _one_call_estimate()
    db = FakeFirestore()
    budget = make_test_budget(budget_usd=estimate * 1.5, db=db)  # yalnızca biri sığar
    request = _Client()
    _engine(request, make_test_budget()).analyze_item(_news(), "THYAO")
    sent = request.calls[0]

    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        barrier.wait()
        try:
            budget.reserve(model=MODEL, request=sent, news_id="n1", asset="THYAO")
            outcomes.append("reserved")
        except BudgetExhaustedError:
            outcomes.append("exhausted")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["exhausted", "reserved"]
    assert len(_reservations(db)) == 1
    assert _ledger(db)["reserved_usd"] == pytest.approx(estimate)


# ------------------------------------------------------------------ reconciliation


def test_successful_call_is_reconciled_with_actual_usage_exactly_once():
    db = FakeFirestore()
    budget = make_test_budget(db=db)
    client = _Client(usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000))
    _engine(client, budget).analyze_item(_news(), "THYAO")

    ledger = _ledger(db)
    assert ledger["reserved_usd"] == pytest.approx(0.0)
    assert ledger["committed_usd"] == pytest.approx(1.40)
    [reservation] = _reservations(db)
    assert reservation["status"] == SETTLED
    [(reservation_id, log)] = db.collection_docs("token_usage_logs").items()
    assert log["cost_usd"] == pytest.approx(1.40)

    # Aynı rezervasyonun tekrar uzlaştırılması çift muhasebe üretmez.
    budget._store.settle(reservation_id, SimpleNamespace(cost_usd=1.40, model_dump=lambda: {}))
    assert _ledger(db)["committed_usd"] == pytest.approx(1.40)
    assert len(db.collection_docs("token_usage_logs")) == 1


def test_invalid_model_output_is_still_charged_but_not_persisted():
    db = FakeFirestore()
    repo = _AnalysisRepo()
    client = _Client(content="{kesik json")
    with pytest.raises(json.JSONDecodeError):
        _engine(client, make_test_budget(db=db), analysis_repo=repo).analyze_item(_news(), "THYAO")
    assert repo.added == []
    assert _reservations(db)[0]["status"] == SETTLED
    assert len(db.collection_docs("token_usage_logs")) == 1


# ------------------------------------------------------------------ uncertain calls + retry


def test_timeout_keeps_reservation_held_and_retry_cannot_reuse_it():
    estimate = _one_call_estimate()
    db = FakeFirestore()
    budget = make_test_budget(budget_usd=estimate * 1.5, db=db)
    timing_out = _Client(error=TimeoutError("read timeout"))

    with pytest.raises(TimeoutError):
        _engine(timing_out, budget).analyze_item(_news(), "THYAO")
    [reservation] = _reservations(db)
    assert reservation["status"] == UNCERTAIN
    assert _ledger(db)["reserved_usd"] == pytest.approx(estimate)  # serbest bırakılmadı

    retry = _Client()
    with pytest.raises(BudgetExhaustedError):
        _engine(retry, budget).analyze_item(_news(), "THYAO")
    assert retry.calls == []
    assert len(_reservations(db)) == 1


def test_missing_usage_keeps_reservation_held():
    db = FakeFirestore()
    _engine(_Client(usage=None), make_test_budget(db=db)).analyze_item(_news(), "THYAO")
    assert _reservations(db)[0]["status"] == UNCERTAIN
    assert db.collection_docs("token_usage_logs") == {}
    assert _ledger(db)["reserved_usd"] > 0


def test_crash_after_reservation_leaves_it_held():
    db = FakeFirestore()
    budget = make_test_budget(db=db)
    client = _Client()
    _engine(client, make_test_budget()).analyze_item(_news(), "THYAO")

    reservation = budget.reserve(model=MODEL, request=client.calls[0], news_id="n1", asset="THYAO")
    # süreç burada öldü: ne uzlaştırma ne UNCERTAIN işareti
    [stored] = _reservations(db)
    assert stored["status"] == RESERVED
    assert _ledger(db)["reserved_usd"] == pytest.approx(reservation.amount_usd)


# ------------------------------------------------------------------ SDK automatic retries (real SDK, mock HTTP)


def _sdk_factory(monkeypatch, handler):
    import httpx
    from openai import OpenAI as RealOpenAI

    def factory(**kwargs):
        return RealOpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(engine_module, "OpenAI", factory)
    monkeypatch.setattr(engine_module, "OPENAI_API_KEY", "test-key")
    return factory


def _server_error(attempts):
    import httpx

    def handler(request):
        attempts.append(request)
        return httpx.Response(500, headers={"retry-after-ms": "1"}, json={"error": {"message": "boom"}})

    return handler


def test_sdk_default_would_retry_under_one_reservation():
    """Kontrol: kurulu SDK'nin varsayılanı aynı isteği birden fazla kez gönderir."""
    import httpx
    import openai
    from openai import OpenAI as RealOpenAI

    attempts = []
    client = RealOpenAI(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(_server_error(attempts))))
    with pytest.raises(openai.InternalServerError):
        client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "x"}])
    assert len(attempts) == 3


@pytest.mark.parametrize("failure", ["server_error", "timeout"])
def test_engine_client_makes_exactly_one_http_attempt_per_reservation(monkeypatch, failure):
    import httpx
    import openai

    attempts = []
    if failure == "server_error":
        handler = _server_error(attempts)
        expected = openai.InternalServerError
    else:
        def handler(request):
            attempts.append(request)
            raise httpx.ReadTimeout("read timeout", request=request)
        expected = openai.APITimeoutError
    _sdk_factory(monkeypatch, handler)
    db = FakeFirestore()
    engine = EventIntelligenceEngine(
        analysis_repo=_AnalysisRepo(), news_repo=_NewsRepo([]), budget=make_test_budget(db=db), primary_model=MODEL
    )
    assert engine._client.max_retries == 0

    with pytest.raises(expected):
        engine.analyze_item(_news(), "THYAO")
    assert len(attempts) == 1
    [reservation] = _reservations(db)
    assert reservation["status"] == UNCERTAIN


# ------------------------------------------------------------------ ledger seeding + transaction re-execution


def test_two_fresh_instances_seed_history_once_and_the_losing_seed_writes_nothing():
    from app.engines.event_intelligence.budget import EventIntelligenceBudget
    from app.repositories.event_intelligence_budget_repository import FirestoreBudgetLedgerRepository
    from google.api_core.exceptions import AlreadyExists
    from tests.event_budget_fakes import fake_transactional

    db = FakeFirestore()
    db.docs[("token_usage_logs", "legacy")] = {"cost_usd": 1.0}
    request = _Client()
    _engine(request, make_test_budget()).analyze_item(_news(), "THYAO")
    sent = request.calls[0]

    # B okur (defter yok) ama commit'i A'dan SONRA gelir: gerçek Firestore'da bu
    # çakışma B'yi yeniden denetir ya da düşürür; burada create koşulunu gösterir.
    deferred = []

    def read_now_commit_later(fn):
        def run(transaction):
            result = fn(transaction)
            deferred.append(transaction)
            return result
        return run

    instance_b = EventIntelligenceBudget(FirestoreBudgetLedgerRepository(db=db, transactional=read_now_commit_later), 100.0)
    instance_a = EventIntelligenceBudget(FirestoreBudgetLedgerRepository(db=db, transactional=fake_transactional), 100.0)
    instance_b.reserve(model=MODEL, request=sent, news_id="b", asset="THYAO")
    reservation_a = instance_a.reserve(model=MODEL, request=sent, news_id="a", asset="THYAO")

    with pytest.raises(AlreadyExists):
        deferred[0].commit()
    ledger = _ledger(db)
    assert ledger["seeded_from_token_usage_logs_usd"] == pytest.approx(1.0)  # geçmiş bir kez
    assert ledger["reserved_usd"] == pytest.approx(reservation_a.amount_usd)  # A'nın rezervasyonu kaybolmadı
    assert [r["news_id"] for r in _reservations(db)] == ["a"]  # B hiçbir şey yazmadı


def test_transaction_re_execution_creates_single_reservation_and_single_usage_log():
    from app.engines.event_intelligence.budget import EventIntelligenceBudget
    from app.repositories.event_intelligence_budget_repository import FirestoreBudgetLedgerRepository

    db = FakeFirestore()
    executions = []

    def abort_once_then_commit(fn):
        def run(transaction):
            fn(transaction)  # ilk deneme: çakışma -> yazmalar atılır
            executions.append(1)
            retry = db.transaction()
            result = fn(retry)
            retry.commit()
            return result
        return run

    budget = EventIntelligenceBudget(FirestoreBudgetLedgerRepository(db=db, transactional=abort_once_then_commit), 100.0)
    client = _Client(usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000))
    _engine(client, budget).analyze_item(_news(), "THYAO")

    assert len(client.calls) == 1  # dış çağrı transaction içinde değil
    assert len(executions) == 2  # reserve + settle yeniden çalıştı
    assert len(_reservations(db)) == 1
    assert len(db.collection_docs("token_usage_logs")) == 1
    assert _ledger(db)["committed_usd"] == pytest.approx(0.20)


# ------------------------------------------------------------------ settle failure + actual > estimate


def test_settle_failure_keeps_reservation_held_and_persists_no_analysis():
    db = FakeFirestore()
    repo = _AnalysisRepo()

    class _FailSettleClient(_Client):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            db.fail_commits = True  # çağrı başarılı, uzlaştırma yazılamıyor
            return response

    budget = make_test_budget(db=db)
    with pytest.raises(BudgetUnavailableError):
        _engine(_FailSettleClient(), budget, analysis_repo=repo).analyze_item(_news(), "THYAO")
    [reservation] = _reservations(db)
    ledger = _ledger(db)
    assert reservation["status"] == RESERVED
    assert ledger["reserved_usd"] == pytest.approx(reservation["amount_usd"])
    assert ledger["committed_usd"] == pytest.approx(0.0)
    assert repo.added == []


def test_actual_cost_above_estimate_is_recorded_unclipped_and_blocks_later_calls():
    estimate = _one_call_estimate()
    db = FakeFirestore()
    budget = make_test_budget(budget_usd=estimate * 3, db=db)
    # gerçek kullanım tahminin çok üzerinde (ör. sağlayıcı farklı sayım)
    heavy = _Client(usage=SimpleNamespace(prompt_tokens=100_000, completion_tokens=0, total_tokens=100_000))
    _engine(heavy, budget).analyze_item(_news(), "THYAO")

    ledger = _ledger(db)
    assert ledger["committed_usd"] == pytest.approx(0.02)  # kırpılmadı
    assert ledger["committed_usd"] > estimate
    assert ledger["reserved_usd"] == pytest.approx(0.0)

    later = _Client()
    with pytest.raises(BudgetExhaustedError):
        _engine(later, budget).analyze_item(_news(), "THYAO")
    assert later.calls == []
