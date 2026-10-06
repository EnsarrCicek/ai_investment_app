"""Kısmi satış çekirdeği — ağırlıklı ortalama, kesin ondalık, defter, sürüm koruması, atomiklik (sahte depo)."""

import threading
from datetime import datetime, timezone
from decimal import Decimal, localcontext

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import portfolio as portfolio_api
from app.core.auth import get_current_user_id
from app.models.market_data import MarketData
from app.services.portfolio import pnl_calculator
from app.services.portfolio.sale_ledger import PRECISION, SaleError, weighted_average_sale
from tests.portfolio_fakes import FakeLedgerRepository, FakePortfolioRepository, InMemoryPortfolio

NOW = datetime(2025, 7, 1, tzinfo=timezone.utc)


def exact(expr):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return expr()


# --- saf muhasebe ----------------------------------------------------------------------------------------------------

def test_A_weighted_average_partial_sale_exact():
    r = weighted_average_sale(150, 2000, 60, 25)
    assert r["average_cost_at_sale"] == exact(lambda: Decimal(2000) / Decimal(150))
    assert r["disposed_cost_basis"] == Decimal(800)  # 60 × 2000/150, yuvarlanmış 13.33 ile 799.8 DEĞİL
    assert r["sale_proceeds"] == Decimal(1500) and r["realized_pnl"] == Decimal(700)
    assert r["remaining_quantity"] == Decimal(90) and r["remaining_cost_basis"] == Decimal(1200)


def test_B_full_quantity_leaves_zero():
    r = weighted_average_sale(150, 2000, 150, 25)
    assert r["remaining_quantity"] == 0 and r["remaining_cost_basis"] == 0


@pytest.mark.parametrize("qty,price,code", [(151, 25, "QUANTITY_EXCEEDS_AVAILABLE"), (0, 25, "INVALID_QUANTITY"),
                                            (-5, 25, "INVALID_QUANTITY"), (10, 0, "INVALID_SELL_PRICE"),
                                            (10, -1, "INVALID_SELL_PRICE")])
def test_CDEF_invalid_inputs_rejected(qty, price, code):
    with pytest.raises(SaleError) as e:
        weighted_average_sale(150, 2000, qty, price)
    assert e.value.code == code


def test_precision_differs_from_rounded_average_path():
    # 1 @ 10 + 2 @ 11 -> ortalama 32/3 (devirli); eski yol round(avg, 2) = 10.67
    r = weighted_average_sale(3, 32, 3, 12)
    assert r["disposed_cost_basis"] == Decimal(32) and r["realized_pnl"] == Decimal(4)
    old = (12 - round(32 / 3, 2)) * 3
    assert abs(old - 3.99) < 1e-9 and Decimal(repr(round(old, 2))) != r["realized_pnl"]
    part = weighted_average_sale(3, 32, 1, 12)
    assert part["disposed_cost_basis"] + part["remaining_cost_basis"] == Decimal(32)  # kayıp/fazla yok


# --- API / defter --------------------------------------------------------------------------------------------------

def lot(qty, price, currency="TRY", asset="AAA", user="u1"):
    return {"user_id": user, "asset": asset, "buy_price": price, "buy_date": NOW, "quantity": qty, "created_at": NOW,
            "currency": currency}


def make_client(monkeypatch, docs):
    store = InMemoryPortfolio(docs)
    monkeypatch.setattr(portfolio_api, "PortfolioRepository", lambda: FakePortfolioRepository(store))
    monkeypatch.setattr(portfolio_api, "PortfolioLedgerRepository", lambda: FakeLedgerRepository(store))

    class Provider:
        def get_latest(self, symbol):
            return MarketData(asset_id=symbol, timestamp=NOW, open=1, high=1, low=1, close=30.0, volume=1, source="fake",
                              currency="TRY", exchange="IST", identity_check="MATCH")

    monkeypatch.setattr(pnl_calculator, "ProvenanceBistProvider", Provider)
    app = FastAPI()
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    return TestClient(app), store


def position(c, asset="AAA"):
    rows = [r for r in c.get("/portfolio/positions").json()["positions"] if r["asset"] == asset]
    return rows[0] if rows else None


def sell(c, qty, price=25.0, version=None, **extra):
    version = version if version is not None else position(c)["position_version"]
    return c.post("/portfolio/positions/AAA/sell", json={"quantity": qty, "sell_price": price, "position_version": version, **extra})


def test_1_3_9_partial_sale_multi_lot_exact_and_unverified(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0), lot(50, 20.0)])
    r = sell(c, 60)
    assert r.status_code == 200
    tx = r.json()
    assert tx["quantity"] == 60 and tx["disposal_method"] == "WEIGHTED_AVERAGE"
    assert Decimal(tx["disposed_cost_basis"]) == Decimal(800) and Decimal(tx["realized_pnl_exact"]) == Decimal(700)
    assert Decimal(tx["remaining_quantity"]) == 90 and Decimal(tx["remaining_cost_basis"]) == 1200
    assert tx["basis_verified"] is False and tx["currency"] == "TRY"
    assert len(store.lots) == 2  # alış lotları değişmedi
    p = position(c)
    assert p["quantity"] == 90 and p["buy_price"] == round(1200 / 90, 2)  # pozisyon açık, kalan maliyet defterden


def test_2_full_sale_and_close_compat(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0), lot(50, 20.0)])
    assert sell(c, 60).status_code == 200
    r = c.post("/portfolio/positions/AAA/close", json={"sell_price": 30.0})  # eski sözleşme: kalanın tamamı
    assert r.status_code == 200 and r.json()["quantity"] == 90
    assert Decimal(r.json()["disposed_cost_basis"]) == 1200 and position(c) is None and not store.lots


def test_4_stale_version_rejected_without_writes(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    before = dict(store.lots)
    r = sell(c, 10, version="eski-surum")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "POSITION_CHANGED"
    assert store.sales == {} and store.lots == before


def test_4b_version_changes_after_partial_sale(monkeypatch):
    c, _ = make_client(monkeypatch, [lot(100, 10.0)])
    v1 = position(c)["position_version"]
    assert sell(c, 10, version=v1).status_code == 200
    assert position(c)["position_version"] != v1
    assert sell(c, 10, version=v1).status_code == 409  # aynı ekrandan ikinci satış reddedilir


def test_5_concurrent_sales_with_same_version_cannot_both_succeed(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    v = position(c)["position_version"]
    barrier, codes = threading.Barrier(2), []

    def worker():
        barrier.wait()
        codes.append(sell(c, 70, version=v).status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert sum(d["quantity"] for d in store.sales.values()) == 70  # mevcut adet aşılmadı


def test_6_7_8_currency_rules(monkeypatch):
    c, _ = make_client(monkeypatch, [lot(10, 10.0)])
    assert sell(c, 1, currency="TRY").json()["currency"] == "TRY"
    r = sell(c, 1, currency="USD")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "CURRENCY_MISMATCH"
    c2, _ = make_client(monkeypatch, [lot(10, 10.0, currency=None)])
    assert sell(c2, 1, currency="TRY").json()["currency"] is None  # istekten benimsenmez
    assert position(c2)["currency"] is None


def test_10_full_sale_then_reopen_is_not_affected_by_old_sales(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    assert sell(c, 40).status_code == 200
    assert sell(c, 60).status_code == 200  # kalanın tamamı -> lotlar silinir
    assert position(c) is None
    assert c.post("/portfolio/positions", json={"asset": "AAA", "buy_price": 50.0, "quantity": 5,
                                                "buy_date": NOW.isoformat(), "currency": "TRY"}).status_code == 200
    p = position(c)
    assert p["quantity"] == 5 and p["buy_price"] == 50.0 and len(store.sales) == 2


def test_request_validation_and_extra_fields(monkeypatch):
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    v = position(c)["position_version"]
    for bad in ({"quantity": 0}, {"quantity": -1}, {"sell_price": 0}, {"position_version": ""}, {"currency": "tl"},
                {"buy_price": 1.0}, {"basis_verified": True}):
        body = {"quantity": 10, "sell_price": 25.0, "position_version": v} | bad
        assert c.post("/portfolio/positions/AAA/sell", json=body).status_code == 422
    assert sell(c, 101).status_code == 422 and store.sales == {}  # mevcut adetten fazla


def test_sale_error_writes_nothing(monkeypatch):
    c, store = make_client(monkeypatch, [lot(10, 10.0)])
    assert sell(c, 5, currency="USD").status_code == 422
    assert store.sales == {} and len(store.lots) == 1
