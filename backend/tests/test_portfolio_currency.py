"""Pozisyon para birimi + güncel fiyat kaynağı — ağsız, sahte depolar/sağlayıcılarla."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import portfolio as portfolio_api
from app.core.auth import get_current_user_id
from app.models.market_data import MarketData
from app.models.portfolio_position import PortfolioPosition, merged_currency
from app.models.portfolio_transaction import PortfolioTransaction
from app.schemas.portfolio import PortfolioPositionCreate
from app.services.market_data import bist_provenance_provider as pp
from app.services.market_data import bist_provider as bp
from app.services.portfolio import pnl_calculator

NOW = datetime(2025, 7, 1, 10, 0, tzinfo=timezone.utc)
OLD_DOC = {"user_id": "u1", "asset": "AAA", "buy_price": 10.0, "buy_date": NOW, "quantity": 5.0, "created_at": NOW}


def test_old_position_record_has_unknown_currency():
    p = PortfolioPosition(**OLD_DOC)
    assert p.currency is None
    assert merged_currency([p, PortfolioPosition(**OLD_DOC, currency="TRY")]) is None  # eksik varsa birleşik bilinmez
    assert merged_currency([PortfolioPosition(**OLD_DOC, currency="TRY")] * 2) == "TRY"
    assert merged_currency([PortfolioPosition(**OLD_DOC, currency="TRY"), PortfolioPosition(**OLD_DOC, currency="USD")]) is None


def test_create_with_currency_round_trip_and_validation():
    payload = PortfolioPositionCreate(asset="AAA", buy_price=10.0, buy_date=NOW, quantity=5.0, currency="TRY")
    stored = PortfolioPosition(user_id="u1", **payload.model_dump(), created_at=NOW).model_dump()
    assert PortfolioPosition(**stored).currency == "TRY"
    assert PortfolioPositionCreate(asset="AAA", buy_price=1, buy_date=NOW, quantity=1).currency is None
    for bad in ("tl", "TL", "TRYY", ""):
        with pytest.raises(ValidationError):
            PortfolioPositionCreate(asset="AAA", buy_price=1, buy_date=NOW, quantity=1, currency=bad)


class FakeTicker:
    def __init__(self, meta):
        self._price_history = SimpleNamespace(_history_metadata=None)
        self._meta = meta
        self.calls = 0

    def history(self, period=None, interval="1d", **kw):
        self.calls += 1
        self._price_history._history_metadata = self._meta
        idx = pd.DatetimeIndex([pd.Timestamp("2025-06-30", tz="Europe/Istanbul")])
        return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [12.0], "Volume": [10]}, index=idx)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(bp.time, "sleep", lambda *_a, **_k: None)


def latest(monkeypatch, meta):
    t = FakeTicker(meta)
    monkeypatch.setattr(bp.yf, "Ticker", lambda _s: t)
    return pp.ProvenanceBistProvider().get_latest("AAA"), t


def test_get_latest_match_try_from_same_response(monkeypatch):
    md, t = latest(monkeypatch, {"symbol": "AAA.IS", "exchangeName": "IST", "currency": "TRY"})
    assert (md.currency, md.exchange, md.identity_check) == ("TRY", "IST", "MATCH")
    assert md.close == 12.0 and t.calls == 1  # ek istek yok


def test_get_latest_missing_metadata_unverified_and_mismatch_fails_closed(monkeypatch):
    md, _ = latest(monkeypatch, {"symbol": "AAA.IS"})
    assert md.currency is None and md.exchange is None and md.identity_check == "UNVERIFIED"
    md2, _ = latest(monkeypatch, None)
    assert md2.identity_check == "UNVERIFIED" and md2.currency is None
    with pytest.raises(ValueError):
        latest(monkeypatch, {"symbol": "AAA.IS", "exchangeName": "IST", "currency": "USD"})


class FakeRepo:
    def __init__(self, docs):
        self.docs, self.deleted = docs, []

    def list_for_user(self, user_id):
        return [(f"id{i}", PortfolioPosition(**d)) for i, d in enumerate(self.docs) if d["user_id"] == user_id]

    def get_position_for_asset(self, user_id, asset):
        lots = [PortfolioPosition(**d) for d in self.docs if d["user_id"] == user_id and d["asset"] == asset]
        if not lots:
            return None
        return PortfolioPosition(user_id=user_id, asset=asset, buy_price=lots[0].buy_price, buy_date=lots[0].buy_date,
                                 quantity=sum(lot.quantity for lot in lots), created_at=NOW, currency=merged_currency(lots))

    def delete_for_asset(self, user_id, asset):
        self.deleted.append(asset)

    def replace_for_asset(self, user_id, asset, position):
        self.docs = [d for d in self.docs if not (d["user_id"] == user_id and d["asset"] == asset)]
        self.docs.append(position.model_dump())
        return "new-id"


class FakeTxRepo:
    added: list = []

    def add(self, tx):
        FakeTxRepo.added.append(tx)


class DocsLedger:
    """Satış defteri sahtesi (FakeRepo belgeleri üzerinde): /close artık ortak satış çekirdeğini kullanıyor."""

    def __init__(self, repo):
        self.repo, self.sales = repo, []

    def _lots(self, user_id, asset):
        return [(f"id{i}", PortfolioPosition(**d)) for i, d in enumerate(self.repo.docs)
                if d["user_id"] == user_id and d["asset"] == asset]

    def sales_for_user(self, user_id):
        return [(f"s{i}", t) for i, t in enumerate(self.sales) if t.user_id == user_id]

    def execute_sale(self, user_id, asset, plan_fn):
        plan = plan_fn(self._lots(user_id, asset), [x for x in self.sales_for_user(user_id) if x[1].asset == asset])
        self.sales.append(plan.transaction)
        if plan.full:
            self.repo.docs = [d for d in self.repo.docs if not (d["user_id"] == user_id and d["asset"] == asset)]
        return f"s{len(self.sales) - 1}", plan


def client(monkeypatch, docs, meta_currency="TRY", identity="MATCH"):
    repo = FakeRepo(docs)
    repo.ledger = DocsLedger(repo)
    monkeypatch.setattr(portfolio_api, "PortfolioRepository", lambda: repo)
    monkeypatch.setattr(portfolio_api, "PortfolioTransactionRepository", FakeTxRepo)
    monkeypatch.setattr(portfolio_api, "PortfolioLedgerRepository", lambda: repo.ledger)

    class FakeProvider:
        def get_latest(self, symbol):
            return MarketData(asset_id=symbol, timestamp=NOW, open=1, high=1, low=1, close=12.0, volume=1, source="fake",
                              currency=meta_currency, exchange="IST" if meta_currency else None, identity_check=identity)

    monkeypatch.setattr(pnl_calculator, "ProvenanceBistProvider", FakeProvider)
    app = FastAPI()
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    return TestClient(app), repo


def test_positions_response_carries_current_price_provenance_separately(monkeypatch):
    c, _ = client(monkeypatch, [OLD_DOC | {"currency": "TRY"}])
    row = c.get("/portfolio/positions").json()["positions"][0]
    assert row["currency"] == "TRY"
    assert (row["current_price_currency"], row["current_price_exchange"], row["current_price_identity_check"]) == ("TRY", "IST", "MATCH")
    assert row["profit_loss"] == round(5 * 12.0 - 5 * 10.0, 2)  # hesap değişmedi


def test_currency_mismatch_or_unknown_is_not_merged(monkeypatch):
    c, _ = client(monkeypatch, [OLD_DOC | {"currency": "TRY"}], meta_currency="USD")
    row = c.get("/portfolio/positions").json()["positions"][0]
    assert row["currency"] == "TRY" and row["current_price_currency"] == "USD"  # iki taraf ayrı raporlanır
    c2, _ = client(monkeypatch, [OLD_DOC], meta_currency=None, identity="UNVERIFIED")
    row2 = c2.get("/portfolio/positions").json()["positions"][0]
    assert row2["currency"] is None and row2["current_price_currency"] is None and row2["current_price_identity_check"] == "UNVERIFIED"


def test_transaction_currency_carried_from_position_and_backward_compatible(monkeypatch):
    old_tx = {"user_id": "u1", "asset": "AAA", "quantity": 1.0, "buy_price": 1.0, "buy_date": NOW, "sell_price": 2.0,
              "sell_date": NOW, "realized_pnl": 1.0, "realized_pnl_percent": 100.0, "created_at": NOW}
    assert PortfolioTransaction(**old_tx).currency is None
    c, repo = client(monkeypatch, [OLD_DOC | {"currency": "TRY"}])
    assert c.post("/portfolio/positions/AAA/close", json={"sell_price": 11.0}).status_code == 200
    assert repo.ledger.sales[-1].currency == "TRY"
    c2, _ = client(monkeypatch, [OLD_DOC])
    assert c2.post("/portfolio/positions/AAA/close", json={"sell_price": 11.0}).json()["currency"] is None


UPDATE = {"buy_price": 11.0, "buy_date": NOW.isoformat(), "quantity": 6.0}


def updated_currency(monkeypatch, stored_currency, extra):
    c, repo = client(monkeypatch, [OLD_DOC | ({"currency": stored_currency} if stored_currency else {})])
    r = c.put("/portfolio/positions/AAA", json=UPDATE | extra)
    assert r.status_code == 200
    (doc,) = [d for d in repo.docs if d["asset"] == "AAA"]
    assert r.json()["currency"] == doc["currency"]
    return doc["currency"]


def test_update_without_currency_field_preserves_stored_currency(monkeypatch):
    assert updated_currency(monkeypatch, "TRY", {}) == "TRY"


def test_update_with_explicit_currency_uses_request_value(monkeypatch):
    assert updated_currency(monkeypatch, "TRY", {"currency": "USD"}) == "USD"


def test_update_with_explicit_null_clears_currency(monkeypatch):
    assert updated_currency(monkeypatch, "TRY", {"currency": None}) is None


def test_update_old_position_without_currency_stays_null(monkeypatch):
    assert updated_currency(monkeypatch, None, {}) is None


def test_update_rejects_invalid_explicit_currency(monkeypatch):
    c, _ = client(monkeypatch, [OLD_DOC | {"currency": "TRY"}])
    assert c.put("/portfolio/positions/AAA", json=UPDATE | {"currency": "tl"}).status_code == 422
