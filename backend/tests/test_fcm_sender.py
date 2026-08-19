from datetime import datetime, timezone

from app.models.ai_decision import AIDecision
from app.models.market_data import Quote
from app.models.technical_analysis import TechnicalAnalysis
from app.services.notifications import fcm_sender


class _FakeTokenRepo:
    def __init__(self, token=None):
        self._token = token

    def get(self, user_id):
        return self._token


class _FakeLogRepo:
    def __init__(self, last_decision=None):
        self._last = last_decision
        self.set_calls = []

    def get_last_decision(self, user_id, asset):
        return self._last

    def set_last_decision(self, user_id, asset, decision):
        self.set_calls.append((user_id, asset, decision))
        self._last = decision


def _decision(decision="BUY", asset="THYAO", final_score=45.0, confidence=70.0):
    now = datetime.now(timezone.utc)
    return AIDecision(
        asset=asset,
        created_at=now,
        technical_score=final_score,
        news_score=None,
        macro_score=None,
        technical_weight=0.5,
        news_weight=0.3,
        macro_weight=0.2,
        final_score=final_score,
        decision=decision,
        confidence=confidence,
        decision_engine_version="1.0.0",
    )


def test_weak_decisions_never_notify():
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="HOLD"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )
    assert sent is False


def test_no_registered_token_means_no_notification():
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="BUY"), token_repo=_FakeTokenRepo(None), log_repo=_FakeLogRepo()
    )
    assert sent is False


def test_same_decision_is_not_renotified():
    log_repo = _FakeLogRepo(last_decision="BUY")
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="BUY"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )
    assert sent is False


def test_new_strong_decision_sends_and_logs(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    log_repo = _FakeLogRepo(last_decision=None)
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL", asset="GARAN"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )

    assert sent is True
    assert len(sent_messages) == 1
    assert sent_messages[0].fid == "tok"
    assert log_repo.set_calls == [("u1", "GARAN", "SELL")]


def test_decision_change_renotifies(monkeypatch):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)

    log_repo = _FakeLogRepo(last_decision="BUY")
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )
    assert sent is True


def test_quantity_held_included_in_notification_body(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        quantity_held=100.0,
    )

    assert "100 adet" in sent_messages[0].notification.body


def test_no_quantity_held_omits_holding_text(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )

    assert "adet" not in sent_messages[0].notification.body


def test_sell_with_quantity_held_instructs_to_sell(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL", asset="TUPRS"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        quantity_held=50.0,
    )

    body = sent_messages[0].notification.body
    assert "50 adet" in body
    assert "SATMANIZ" in body


def test_suggested_buy_quantity_included_in_notification_body(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="BUY"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        suggested_buy_quantity=25.0,
        budget_tl=5000.0,
    )

    body = sent_messages[0].notification.body
    assert "25 adet" in body
    assert "ALMANIZ" in body
    assert "5000 TL" in body


class _FakeAnalysisRepo:
    def __init__(self, analysis: TechnicalAnalysis | None):
        self._analysis = analysis

    def get_latest(self, asset):
        return self._analysis


class _FakeQuoteProvider:
    def __init__(self, last_price: float = 100.0, raise_error: bool = False):
        self._last_price = last_price
        self._raise_error = raise_error

    def get_quote(self, symbol):
        if self._raise_error:
            raise ValueError(f"'{symbol}' için fiyat alınamadı")
        now = datetime.now(timezone.utc)
        return Quote(
            asset_id=symbol,
            timestamp=now,
            last_price=self._last_price,
            previous_close=self._last_price,
            change=0.0,
            change_percent=0.0,
            open=self._last_price,
            high=self._last_price,
            low=self._last_price,
            volume=1000,
            source="fake",
        )


class _FakeSettingsConfigRepo:
    def __init__(self, settings: dict | None = None):
        self._settings = settings

    def get(self, key, defaults):
        return self._settings if self._settings is not None else defaults


def _strong_analysis(signal_class: str = "STRONG_BULLISH_INITIATION") -> TechnicalAnalysis:
    return TechnicalAnalysis(
        asset="THYAO",
        technical_score=50.0,
        trend="BULLISH",
        confidence=0.9,
        components={},
        indicators={},
        created_at=datetime.now(timezone.utc),
        signal_class=signal_class,
    )


def test_new_opportunity_skipped_when_decision_is_not_buy():
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="SELL"), analysis_repo=_FakeAnalysisRepo(_strong_analysis())
    )
    assert sent is False


def test_new_opportunity_skipped_without_cached_analysis():
    sent = fcm_sender.notify_if_new_opportunity("u1", _decision(decision="BUY"), analysis_repo=_FakeAnalysisRepo(None))
    assert sent is False


def test_new_opportunity_skipped_when_signal_class_not_strong():
    analysis = _strong_analysis(signal_class="BULLISH_CANDIDATE")
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY"), analysis_repo=_FakeAnalysisRepo(analysis)
    )
    assert sent is False


def test_new_opportunity_skipped_when_quote_unavailable():
    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(raise_error=True),
    )
    assert sent is False


def test_new_opportunity_sends_with_computed_quantity(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(last_price=200.0),
        config_repo=_FakeSettingsConfigRepo({"default_trade_budget_tl": 1000.0}),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
    )

    assert sent is True
    body = sent_messages[0].notification.body
    assert "5 adet" in body  # 1000 TL / 200 TL = 5 adet
    assert "1000 TL" in body


def test_new_opportunity_uses_default_budget_when_not_configured(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(last_price=100.0),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
    )

    body = sent_messages[0].notification.body
    assert "50 adet" in body  # varsayılan 5000 TL / 100 TL = 50 adet
