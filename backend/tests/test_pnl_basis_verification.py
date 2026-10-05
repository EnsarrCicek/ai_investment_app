"""Portföy kâr/zararının fiyat temeli doğrulama alanları — ağsız; hesap formülleri değişmeden."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import portfolio as portfolio_api
from app.core.auth import get_current_user_id
from app.models.market_data import MarketData
from app.models.portfolio_position import PortfolioPosition
from app.services.market_data import bist_provider as bp
from app.services.portfolio import pnl_calculator
from app.services.portfolio.pnl_calculator import calculate_pnl, pnl_verification
from app.services.portfolio.position_review import RAW_BASIS

NOW = datetime(2025, 7, 1, tzinfo=timezone.utc)
GOOD = {"symbol": "AAA.IS", "exchangeName": "IST", "currency": "TRY"}


def position(currency="TRY", buy_price=100.0, quantity=10.0):
    return PortfolioPosition(user_id="u1", asset="AAA", buy_price=buy_price, quantity=quantity, buy_date=NOW,
                             created_at=NOW, currency=currency)


def md(close=120.0, currency="TRY", identity="MATCH", basis=bp.YAHOO_PRICE_BASIS):
    return MarketData(asset_id="AAA", timestamp=NOW, open=1, high=1, low=1, close=close, volume=1, source="fake",
                      currency=currency, exchange="IST" if currency else None, identity_check=identity, price_basis=basis)


class Provider:
    def __init__(self, data):
        self.data = data

    def get_latest(self, symbol):
        return self.data


class FakeTicker:
    def __init__(self, meta):
        self._price_history = SimpleNamespace(_history_metadata=None)
        self._meta = meta

    def history(self, period=None, interval="1d", **kw):
        self._price_history._history_metadata = dict(self._meta)
        idx = pd.DatetimeIndex([pd.Timestamp("2025-06-30", tz="Europe/Istanbul")])
        return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [120.0], "Volume": [10]}, index=idx)


def test_yahoo_adjusted_price_is_never_verified(monkeypatch):
    monkeypatch.setattr(bp.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(bp.yf, "Ticker", lambda _s: FakeTicker(GOOD))
    out = calculate_pnl(position(), provider=bp.BistProvider())
    assert out["current_price_basis"] == "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
    assert out["current_price_identity_check"] == "MATCH"
    assert out["pnl_basis_verified"] is False and out["pnl_unverified_reason"] == "PRICE_BASIS_UNVERIFIED"


@pytest.mark.parametrize("pos_currency,data,reason", [
    ("TRY", md(identity="UNVERIFIED"), "PRICE_IDENTITY_UNVERIFIED"),
    ("TRY", md(currency="USD"), "CURRENCY_MISMATCH"),
    (None, md(), "POSITION_CURRENCY_UNKNOWN"),
    ("TRY", md(currency=None), "PRICE_CURRENCY_UNKNOWN"),
])
def test_identity_or_currency_problems_are_unverified(pos_currency, data, reason):
    out = calculate_pnl(position(currency=pos_currency), provider=Provider(data))
    assert out["pnl_basis_verified"] is False and out["pnl_unverified_reason"] == reason


def test_missing_provenance_fails_closed(fake_provider):
    out = calculate_pnl(position(currency=None), provider=fake_provider(close_price=120.0))  # eski tarz MarketData
    assert out["current_price_basis"] is None and out["pnl_basis_verified"] is False


def test_numeric_formula_unchanged():
    out = calculate_pnl(position(buy_price=100.0, quantity=10), provider=Provider(md(close=93.456)))
    assert out["invested_amount"] == 1000.0
    assert out["current_value"] == round(10 * 93.456, 2)
    assert out["profit_loss"] == round(round(10 * 93.456, 2) - 1000.0, 2)
    assert out["return_percent"] == round(out["profit_loss"] / 1000.0 * 100, 2)


def test_verified_contract_requires_raw_basis_and_corporate_actions():
    raw = md(basis=RAW_BASIS)
    assert pnl_verification("TRY", raw) == (False, "CORPORATE_ACTIONS_UNVERIFIED")
    assert pnl_verification("TRY", raw, corporate_actions_verified=True) == (True, None)  # yalnız sözleşme fixture'ı
    assert pnl_verification("TRY", md(), corporate_actions_verified=True) == (False, "PRICE_BASIS_UNVERIFIED")


def test_positions_response_carries_fields_and_old_records_work(monkeypatch):
    old = {"user_id": "u1", "asset": "AAA", "buy_price": 10.0, "buy_date": NOW, "quantity": 5.0, "created_at": NOW}

    class Repo:
        def list_for_user(self, user_id):
            return [("id0", PortfolioPosition(**old))]

    monkeypatch.setattr(portfolio_api, "PortfolioRepository", Repo)
    monkeypatch.setattr(pnl_calculator, "BistProvider", lambda: Provider(md()))
    app = FastAPI()
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    row = TestClient(app).get("/portfolio/positions").json()["positions"][0]
    assert row["currency"] is None and row["profit_loss"] == round(5 * 120.0 - 50.0, 2)
    assert row["current_price_basis"] == "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
    assert row["pnl_basis_verified"] is False and row["pnl_unverified_reason"] == "POSITION_CURRENCY_UNKNOWN"
