from datetime import datetime

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import portfolio as portfolio_api
from app.core.auth import get_current_user_id
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models.portfolio_position import PortfolioPosition
from app.services.portfolio import limit_check as lc
from app.services.portfolio import position_review as pr

NOW = datetime(2025, 7, 14, 10, 0, tzinfo=ISTANBUL_TZ)  # son tamamlanmış seans 2025-07-11
BUY = datetime(2025, 7, 1, 10, 0, tzinfo=ISTANBUL_TZ)


def lot(user, asset, price=100.0, qty=10.0):
    return PortfolioPosition(user_id=user, asset=asset, buy_price=price, buy_date=BUY, quantity=qty, created_at=BUY)


class FakeRepo:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def list_for_user(self, user_id):
        self.calls.append(user_id)
        return [(i, p) for i, p in self.rows if p.user_id == user_id]


class FakeProvider:
    SOURCE = "fake_source"

    def __init__(self, close=110.0, fail=False, identity="MATCH", error=None):
        self.close, self.fail, self.calls, self.identity, self.error = close, fail, 0, identity, error

    def get_history_with_provenance(self, symbol, period="6mo"):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.fail:
            raise ValueError("yok")
        idx = pd.DatetimeIndex([pd.Timestamp("2025-07-10", tz=ISTANBUL_TZ), pd.Timestamp("2025-07-11", tz=ISTANBUL_TZ)])
        df = pd.DataFrame({"Open": [1, 1], "High": [1, 1], "Low": [1, 1], "Close": [100.0, self.close], "Volume": [1, 1]}, index=idx)
        match = self.identity == "MATCH"
        return df, {"requested_symbol": symbol, "provider_symbol": f"{symbol}.IS" if match else None,
                    "currency": "TRY" if match else None, "exchange": "IST" if match else None,
                    "identity_check": self.identity, "source": self.SOURCE, "retrieved_at": NOW}


ROWS = [("a1", lot("u1", "AAA")), ("b1", lot("u2", "AAA", price=50.0))]
V1 = lc.position_version([ROWS[0]])
CLEAN_CA = {"checked_from": "2025-07-01", "checked_through": "2025-07-11", "split_or_bonus_dates": []}


def run(limits, version=V1, provider=None, **kw):
    return lc.check_limits("u1", "aaa", version, limits, FakeRepo(ROWS), provider or FakeProvider(), clock=lambda: NOW, **kw)


def test_no_limits_does_not_fetch_or_read():
    p = FakeProvider()
    out = run({"profit_target_pct": None, "max_loss_pct": None}, provider=p)
    assert out["state"] == lc.STATE_NO_LIMITS and p.calls == 0


def test_current_provider_is_blocked_with_reason_and_no_values():
    out = run({"profit_target_pct": 5.0, "max_loss_pct": None})
    assert out["state"] == lc.STATE_NOT_EVALUATED and out["block_code"] == pr.PRICE_BASIS_UNVERIFIED
    assert "aynı temelde olduğu doğrulanamadı" in out["block_message"]
    assert out["checks"] is None and out["price_used"] is None and out["expected_session"] == "2025-07-11"


def test_position_changed_or_other_user_or_fetch_failure_blocks():
    assert run({"max_loss_pct": 8.0}, version="eski")["block_code"] == lc.POSITION_CHANGED
    other = lc.check_limits("u3", "AAA", V1, {"max_loss_pct": 8.0}, FakeRepo(ROWS), FakeProvider(), clock=lambda: NOW)
    assert other["block_code"] == lc.POSITION_NOT_FOUND  # u2'nin lotu u3'e görünmez
    assert run({"max_loss_pct": 8.0}, provider=FakeProvider(fail=True))["block_code"] == lc.PRICE_FETCH_FAILED


def test_thresholds_equality_is_not_exceeded_with_verified_server_side_basis():
    kw = {"price_basis": pr.RAW_BASIS, "corporate_action_check": CLEAN_CA}
    eq = run({"profit_target_pct": 10.0, "max_loss_pct": 8.0}, provider=FakeProvider(close=110.0), **kw)
    assert eq["state"] == lc.STATE_WITHIN and eq["checks"]["profit_target"]["status"] == pr.LIMIT_WITHIN
    assert eq["price_used"] == {"session": "2025-07-11", "close": 110.0, "source": "fake_source", "price_basis": pr.RAW_BASIS}
    up = run({"profit_target_pct": 10.0}, provider=FakeProvider(close=110.5), **kw)
    assert up["state"] == lc.STATE_EXCEEDED and up["checks"]["max_loss"]["status"] == pr.LIMIT_NOT_DEFINED
    down = run({"max_loss_pct": 8.0}, provider=FakeProvider(close=91.9), **kw)
    assert down["state"] == lc.STATE_EXCEEDED and down["checks"]["max_loss"]["loss_pct_vs_cost"] == 8.1
    assert run({"max_loss_pct": 8.0}, provider=FakeProvider(close=92.0), **kw)["state"] == lc.STATE_WITHIN


def test_invalid_limit_rejected():
    with pytest.raises(pr.InputError):
        run({"profit_target_pct": -1.0})


def test_endpoint_rejects_client_price_or_verified_flag():
    app = FastAPI()
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    client = TestClient(app)
    for extra in ({"close": 120.0}, {"buy_price": 1.0}, {"price_basis": "RAW_UNADJUSTED"}, {"verified": True}):
        r = client.post("/portfolio/positions/AAA/limit-check", json={"position_version": V1, "max_loss_pct": 8.0, **extra})
        assert r.status_code == 422


def test_limit_check_module_has_no_decision_or_notification_dependency():
    src = open(lc.__file__, encoding="utf-8").read()
    assert "fcm_sender" not in src and "DecisionEngine" not in src and "messaging" not in src


def test_version_is_order_independent_and_tracks_lot_content():
    a, b = ("a1", lot("u1", "AAA")), ("a2", lot("u1", "AAA", price=120.0, qty=5.0))
    assert lc.position_version([a, b]) == lc.position_version([b, a])
    base = lc.position_version([a])
    same_id = [("a1", lot("u1", "AAA", qty=11.0)), ("a1", lot("u1", "AAA", price=101.0)),
               ("a1", lot("u1", "AAA").model_copy(update={"buy_date": datetime(2025, 7, 2, 10, 0, tzinfo=ISTANBUL_TZ)}))]
    for changed in same_id:  # aynı belge kimliği yerinde değişse de sürüm değişir
        assert lc.position_version([changed]) != base
    assert lc.position_version([("z9", lot("u1", "AAA"))]) != base  # kapatılıp aynı değerlerle yeniden açılan (yeni kimlik)
    assert lc.position_version([a, b]) != base  # lot ekleme


def test_changed_position_is_not_evaluated_and_price_not_fetched():
    p = FakeProvider()
    rows = [("a1", lot("u1", "AAA", qty=12.0))]  # sınır V1'de kaydedildi; miktar sonra değişti
    out = lc.check_limits("u1", "AAA", V1, {"max_loss_pct": 8.0}, FakeRepo(rows), p, clock=lambda: NOW)
    assert out["block_code"] == lc.POSITION_CHANGED and p.calls == 0 and out["checks"] is None
