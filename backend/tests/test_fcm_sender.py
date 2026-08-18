from datetime import datetime, timezone

from app.models.ai_decision import AIDecision
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
