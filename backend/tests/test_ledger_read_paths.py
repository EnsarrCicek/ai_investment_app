"""Satış defteriyle tutarlı okuma yolları: limit kontrolü, risk yoğunlaşması, K/Z, kapatma/yeniden alış, geçmiş.

Altyapı `test_partial_sale.py` ve `portfolio_fakes.py`'den yeniden kullanılır (yeni sahte depo kurulmaz).
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import portfolio as portfolio_api
from app.api import risk as risk_api
from app.core.auth import get_current_user_id
from app.models.portfolio_position import PortfolioPosition
from app.models.portfolio_transaction import PortfolioTransaction
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.portfolio import limit_check as lc
from app.services.portfolio import position_review as pr
from app.services.portfolio.sale_ledger import plan_sale
from tests.portfolio_fakes import FakeLedgerRepository, FakePortfolioRepository
from tests.test_partial_sale import NOW, lot, make_client, position, sell
from tests.test_portfolio_limit_check import CLEAN_CA, FakeProvider
from tests.test_portfolio_limit_check import NOW as LIMIT_NOW


def limit(store, version, provider=None, **kw):
    return lc.check_limits("u1", "AAA", version, {"max_loss_pct": 50.0}, FakePortfolioRepository(store),
                           provider or FakeProvider(), clock=lambda: LIMIT_NOW, ledger_repo=FakeLedgerRepository(store), **kw)


def capture_review(monkeypatch):
    seen = []
    original = pr.review

    def spy(payload):
        seen.append(payload)
        return original(payload)

    monkeypatch.setattr(lc.pr, "review", spy)
    return seen


# --- limit kontrolü ------------------------------------------------------------------------------------------------

def test_L1_L2_L5_stale_vs_current_version_after_partial_sale(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    v_pre = position(c)["position_version"]
    assert sell(c, 60, version=v_pre).status_code == 200
    assert limit(store, v_pre)["block_code"] == lc.POSITION_CHANGED
    v_post = position(c)["position_version"]
    out = limit(store, v_post)
    assert out["block_code"] != lc.POSITION_CHANGED and out["position_version"] == v_post  # /positions ile aynı sürüm
    assert out["block_code"] == pr.PRICE_BASIS_UNVERIFIED  # üretim tarzı (düzeltilmiş) temel: sonraki kapalı kapı


def test_L3_review_quantity_is_remaining_40(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    assert sell(c, 60).status_code == 200
    seen = capture_review(monkeypatch)
    limit(store, position(c)["position_version"], price_basis=pr.RAW_BASIS, corporate_action_check=CLEAN_CA)
    assert [p["quantity"] for p in seen[-1]["positions"]] == [40.0]  # 100 alış − 60 satış


def test_L4_review_cost_is_exact_remaining_cost_basis(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0), lot(50, 20.0)])
    assert sell(c, 60).status_code == 200
    seen = capture_review(monkeypatch)
    out = limit(store, position(c)["position_version"], price_basis=pr.RAW_BASIS, corporate_action_check=CLEAN_CA)
    assert out["state"] in (lc.STATE_WITHIN, lc.STATE_EXCEEDED)  # tüm kapılar geçildi, kalan durum değerlendirildi
    lots = seen[-1]["positions"]
    assert sum(p["quantity"] for p in lots) == pytest.approx(90, abs=1e-12)
    assert sum(p["quantity"] * p["buy_price"] for p in lots) == pytest.approx(1200, abs=1e-9)
    assert {p["buy_price"] for p in lots} == {float(Decimal(1200) / Decimal(90))}  # round(ort, 2) DEĞİL
    assert sorted(p["buy_date"] for p in lots)[0] == NOW  # en erken alış tarihi korunur


def test_L6_full_sale_then_limit_check_does_not_evaluate(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    v = position(c)["position_version"]
    assert sell(c, 100, version=v).status_code == 200
    assert limit(store, v)["block_code"] == lc.POSITION_NOT_FOUND


def test_L7_second_partial_sale_changes_version_again(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    assert sell(c, 10).status_code == 200
    v1 = position(c)["position_version"]
    assert sell(c, 10).status_code == 200
    v2 = position(c)["position_version"]
    assert v1 != v2 and limit(store, v1)["block_code"] == lc.POSITION_CHANGED
    assert limit(store, v2)["block_code"] != lc.POSITION_CHANGED


def test_limit_endpoint_wiring_passes_ledger(monkeypatch):
    c, _ = make_client(monkeypatch, [lot(100, 10.0)])
    monkeypatch.setattr(portfolio_api, "ProvenanceBistProvider", FakeProvider)
    v_pre = position(c)["position_version"]
    assert sell(c, 60, version=v_pre).status_code == 200
    body = {"max_loss_pct": 50.0}
    stale = c.post("/portfolio/positions/AAA/limit-check", json=body | {"position_version": v_pre}).json()
    assert stale["block_code"] == lc.POSITION_CHANGED
    v_post = position(c)["position_version"]
    cur = c.post("/portfolio/positions/AAA/limit-check", json=body | {"position_version": v_post}).json()
    assert cur["block_code"] != lc.POSITION_CHANGED and cur["position_version"] == v_post


# --- risk yoğunlaşması ---------------------------------------------------------------------------------------------

def risk_client(monkeypatch, store):
    monkeypatch.setattr(risk_api, "PortfolioRepository", lambda: FakePortfolioRepository(store))
    monkeypatch.setattr(risk_api, "PortfolioLedgerRepository", lambda: FakeLedgerRepository(store))
    app = FastAPI()
    app.include_router(risk_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    return TestClient(app)


def test_risk_A_B_partial_sale_exposure_uses_remaining_quantity(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0, asset="AAA"), lot(40, 10.0, asset="BBB")])
    assert sell(c, 60).status_code == 200  # AAA: 40 kaldı, BBB: 40 (aynı fiyat 30)
    out = risk_client(monkeypatch, store).get("/risk/portfolio/concentration").json()
    assert out["weights_pct"] == {"AAA": 50.0, "BBB": 50.0}  # ham lotla 71.43 / 28.57 olurdu
    assert out["herfindahl_index"] == 0.5


def test_risk_C_fully_sold_asset_excluded(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0, asset="AAA"), lot(40, 10.0, asset="BBB")])
    assert sell(c, 100).status_code == 200
    out = risk_client(monkeypatch, store).get("/risk/portfolio/concentration").json()
    assert out["weights_pct"] == {"BBB": 100.0} and out["herfindahl_index"] == 1.0


def test_risk_D_no_sales_unchanged_lot_based(monkeypatch):
    _, store = make_client(monkeypatch, [lot(30, 10.0, asset="AAA"), lot(10, 12.0, asset="AAA"), lot(40, 10.0, asset="BBB")])
    out = risk_client(monkeypatch, store).get("/risk/portfolio/concentration").json()
    assert out["weights_pct"] == {"AAA": 50.0, "BBB": 50.0} and out["herfindahl_index"] == 0.5


# --- K/Z, kapatma/yeniden alış, geçmiş ------------------------------------------------------------------------------

def test_pnl_partial_sale_uses_remaining_quantity(monkeypatch):
    c, _ = make_client(monkeypatch, [lot(100, 10.0), lot(50, 20.0)])
    assert sell(c, 60).status_code == 200
    p = position(c)
    assert p["quantity"] == 90 and p["current_value"] == 90 * 30.0
    assert p["invested_amount"] == round(90 * round(1200 / 90, 2), 2)  # gösterim ortalaması (bilinen LOW sapma)
    assert p["profit_loss"] == round(p["current_value"] - p["invested_amount"], 2)
    assert p["pnl_basis_verified"] is False


def test_close_after_partial_sale_then_reopen(monkeypatch):
    c, store = make_client(monkeypatch, [lot(150, 10.0)])
    assert sell(c, 60).status_code == 200
    r = c.post("/portfolio/positions/AAA/close", json={"sell_price": 12.0})
    assert r.status_code == 200 and r.json()["quantity"] == 90 and position(c) is None and not store.lots
    assert c.post("/portfolio/positions", json={"asset": "AAA", "buy_price": 7.0, "quantity": 3,
                                                "buy_date": NOW.isoformat(), "currency": "TRY"}).status_code == 200
    p = position(c)
    assert p["quantity"] == 3 and p["buy_price"] == 7.0  # eski kısmi satış ve /close yeni lota uygulanmaz


def test_history_contract_carries_partial_sale_fields(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0), lot(50, 20.0)])
    assert sell(c, 60).status_code == 200

    class TxRepo:
        def list_for_user(self, user_id):
            return [PortfolioTransaction(**d) for d in store.sales.values() if d["user_id"] == user_id]

    monkeypatch.setattr(portfolio_api, "PortfolioTransactionRepository", TxRepo)
    (tx,) = c.get("/portfolio/history").json()["transactions"]
    assert tx["quantity"] == 60 and Decimal(tx["disposed_cost_basis"]) == 800
    assert Decimal(tx["average_cost_at_sale"]).quantize(Decimal("1e-20")) == (Decimal(2000) / Decimal(150)).quantize(Decimal("1e-20"))
    assert tx["realized_pnl"] == 700.0 and tx["basis_verified"] is False
    assert tx["disposal_method"] == "WEIGHTED_AVERAGE" and tx["currency"] == "TRY"


def test_real_repository_get_position_for_asset_ledger_branch():
    """Gerçek `PortfolioRepository.get_position_for_asset` (Firestore yerine bellek içi sorgu sahtesi; ağ yok)."""

    class Query:
        def __init__(self, rows, filters=()):
            self.rows, self.filters = rows, filters

        def where(self, filter):
            return Query(self.rows, self.filters + ((filter.field_path, filter.value),))

        def stream(self, transaction=None):
            for doc_id, data in self.rows.items():
                if all(data.get(f) == v for f, v in self.filters):
                    yield SimpleNamespace(id=doc_id, to_dict=lambda d=data: dict(d))

    collections = {"portfolio_positions": {"l1": lot(100, 10.0), "l2": lot(50, 20.0)}, "portfolio_transactions": {}}
    lots = [(i, PortfolioPosition(**d)) for i, d in collections["portfolio_positions"].items()]
    plan = plan_sale("u1", "AAA", lots, [], quantity=60, sell_price=25.0, sell_date=None, expected_version=None,
                     request_currency=None, now=NOW)
    collections["portfolio_transactions"]["s1"] = plan.transaction.model_dump()
    repo = object.__new__(PortfolioRepository)
    repo._db = SimpleNamespace(collection=lambda name: Query(collections[name]))
    p = repo.get_position_for_asset("u1", "AAA")
    assert p.quantity == 90.0 and p.buy_price == round(1200 / 90, 2) and p.currency == "TRY"
    collections["portfolio_transactions"].clear()  # satış yoksa önceki davranış
    p0 = repo.get_position_for_asset("u1", "AAA")
    assert p0.quantity == 150.0 and p0.buy_price == round(2000 / 150, 2)
