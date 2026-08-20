from datetime import datetime, timezone

from app.models.fund_analysis import FundAnalysis
from app.services.notifications import fund_notifier


class _FakeTokenRepo:
    def __init__(self, token="tok"):
        self._token = token

    def get(self, user_id):
        return self._token


class _FakeLogRepo:
    def __init__(self, last_monthly=None, last_switch=None):
        self._last_monthly = last_monthly
        self._last_switch = last_switch or {}
        self.monthly_set_calls = []
        self.switch_set_calls = []

    def get_last_monthly_notified(self, user_id):
        return self._last_monthly

    def set_last_monthly_notified(self, user_id, year_month):
        self.monthly_set_calls.append((user_id, year_month))
        self._last_monthly = year_month

    def get_last_switch_suggestion(self, user_id, held_fund_code):
        return self._last_switch.get(held_fund_code)

    def set_last_switch_suggestion(self, user_id, held_fund_code, suggested_code, date):
        self.switch_set_calls.append((user_id, held_fund_code, suggested_code, date))
        self._last_switch[held_fund_code] = {"suggested_code": suggested_code, "date": date}


class _FakeRecordRepo:
    def __init__(self):
        self.added = []

    def add(self, record):
        self.added.append(record)
        return "fake-record-id"


def _fund(code, score):
    return FundAnalysis(
        fund_code=code,
        fund_name=f"{code} FONU",
        price=100.0,
        portfolio_size=10_000_000.0,
        investor_count=100,
        composite_score=score,
        as_of_date="2026-08-20",
        generated_at=datetime.now(timezone.utc),
    )


def test_notify_monthly_allocation_sends_and_logs_dedup(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: sent_messages.append(message))

    funds = [_fund("A", 20.0), _fund("B", 10.0)]
    log_repo = _FakeLogRepo()
    record_repo = _FakeRecordRepo()

    sent = fund_notifier.notify_monthly_allocation(
        "u1", funds, budget_tl=1000.0, token_repo=_FakeTokenRepo(), log_repo=log_repo, record_repo=record_repo
    )

    assert sent is True
    assert len(sent_messages) == 1
    assert len(record_repo.added) == 1
    assert record_repo.added[0].kind == "FUND_BUY_MONTHLY"
    assert len(log_repo.monthly_set_calls) == 1


def test_notify_monthly_allocation_skips_if_already_notified_this_month(monkeypatch):
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: None)
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    log_repo = _FakeLogRepo(last_monthly=this_month)

    sent = fund_notifier.notify_monthly_allocation(
        "u1", [_fund("A", 10.0)], budget_tl=1000.0, token_repo=_FakeTokenRepo(), log_repo=log_repo,
        record_repo=_FakeRecordRepo(),
    )

    assert sent is False


def test_notify_monthly_allocation_skips_without_budget(monkeypatch):
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: None)

    sent = fund_notifier.notify_monthly_allocation(
        "u1", [_fund("A", 10.0)], budget_tl=0.0, token_repo=_FakeTokenRepo(), log_repo=_FakeLogRepo(),
        record_repo=_FakeRecordRepo(),
    )

    assert sent is False


def test_notify_ad_hoc_allocation_has_no_dedup_and_sends_every_time(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: sent_messages.append(message))
    funds = [_fund("A", 20.0)]

    for _ in range(3):
        sent = fund_notifier.notify_ad_hoc_allocation(
            "u1", funds, amount_tl=500.0, token_repo=_FakeTokenRepo(), record_repo=_FakeRecordRepo()
        )
        assert sent is True

    assert len(sent_messages) == 3


def test_notify_ad_hoc_allocation_returns_false_without_registered_token(monkeypatch):
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: None)

    sent = fund_notifier.notify_ad_hoc_allocation(
        "u1", [_fund("A", 20.0)], amount_tl=500.0, token_repo=_FakeTokenRepo(token=None),
        record_repo=_FakeRecordRepo(),
    )

    assert sent is False


def test_notify_switch_recommendations_triggers_when_gap_is_large(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: sent_messages.append(message))
    ranked = [_fund("BEST", 50.0), _fund("WORST", -10.0)]
    held_scores = {"WORST": -10.0}

    count = fund_notifier.notify_switch_recommendations(
        "u1", held_scores, ranked, token_repo=_FakeTokenRepo(), log_repo=_FakeLogRepo(), record_repo=_FakeRecordRepo()
    )

    assert count == 1
    assert len(sent_messages) == 1


def test_notify_switch_recommendations_skips_when_gap_is_small(monkeypatch):
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: None)
    ranked = [_fund("BEST", 12.0), _fund("HELD", 5.0)]
    held_scores = {"HELD": 5.0}

    count = fund_notifier.notify_switch_recommendations(
        "u1", held_scores, ranked, token_repo=_FakeTokenRepo(), log_repo=_FakeLogRepo(), record_repo=_FakeRecordRepo()
    )

    assert count == 0


def test_notify_switch_recommendations_skips_when_held_fund_is_already_the_best():
    ranked = [_fund("BEST", 50.0)]
    held_scores = {"BEST": 50.0}

    count = fund_notifier.notify_switch_recommendations(
        "u1", held_scores, ranked, token_repo=_FakeTokenRepo(), log_repo=_FakeLogRepo(), record_repo=_FakeRecordRepo()
    )

    assert count == 0


def test_notify_switch_recommendations_dedups_same_suggestion_same_day(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fund_notifier.messaging, "send", lambda message: sent_messages.append(message))
    ranked = [_fund("BEST", 50.0), _fund("WORST", -10.0)]
    held_scores = {"WORST": -10.0}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_repo = _FakeLogRepo(last_switch={"WORST": {"suggested_code": "BEST", "date": today}})

    count = fund_notifier.notify_switch_recommendations(
        "u1", held_scores, ranked, token_repo=_FakeTokenRepo(), log_repo=log_repo, record_repo=_FakeRecordRepo()
    )

    assert count == 0
    assert len(sent_messages) == 0
