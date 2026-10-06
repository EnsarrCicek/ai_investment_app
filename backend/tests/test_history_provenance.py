"""Geçmiş (history) yanıtı kimlik bilgisi + sınır kontrolü kapıları — ağsız, sahte yfinance Ticker ile."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models.portfolio_position import PortfolioPosition
from app.services.market_data import bist_provenance_provider as pp
from app.services.market_data import bist_provider as bp
from app.services.portfolio import limit_check as lc
from app.services.portfolio import position_review as pr

GOOD = {"symbol": "AAA.IS", "exchangeName": "IST", "currency": "TRY"}
FETCHED_AT = datetime(2025, 7, 14, 6, 59, tzinfo=timezone.utc)  # 11.07 kapanışı kesinleştikten sonra
NOW = datetime(2025, 7, 14, 10, 0, tzinfo=ISTANBUL_TZ)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FETCHED_AT


class FakeTicker:
    def __init__(self, meta, close=110.0):
        self._price_history = SimpleNamespace(_history_metadata=None)
        self._meta, self._close, self.calls = meta, close, 0

    def history(self, period=None, interval="1d", **kw):
        self.calls += 1
        self._price_history._history_metadata = dict(self._meta) if self._meta is not None else None
        idx = pd.DatetimeIndex([pd.Timestamp("2025-07-10", tz=ISTANBUL_TZ), pd.Timestamp("2025-07-11", tz=ISTANBUL_TZ)])
        return pd.DataFrame({"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0], "Close": [100.0, self._close],
                             "Volume": [5, 5]}, index=idx)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(bp.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(pp, "datetime", FixedDatetime)


def provider_with(monkeypatch, meta):
    t = FakeTicker(meta)
    monkeypatch.setattr(bp.yf, "Ticker", lambda _s: t)
    return pp.ProvenanceBistProvider(), t


def test_full_metadata_is_match_and_carried(monkeypatch):
    p, t = provider_with(monkeypatch, GOOD)
    df, prov = p.get_history_with_provenance("AAA", period="1mo")
    assert len(df) == 2
    assert prov == {"requested_symbol": "AAA", "provider_symbol": "AAA.IS", "currency": "TRY", "exchange": "IST",
                    "identity_check": "MATCH", "source": "yahoo_finance", "retrieved_at": FETCHED_AT}


@pytest.mark.parametrize("missing", ["currency", "exchangeName", "symbol"])
def test_missing_identity_field_is_unverified_without_defaults(monkeypatch, missing):
    meta = {k: v for k, v in GOOD.items() if k != missing}
    _, prov = provider_with(monkeypatch, meta)[0].get_history_with_provenance("AAA")
    assert prov["identity_check"] == "UNVERIFIED"
    assert {"currency": prov["currency"], "exchangeName": prov["exchange"], "symbol": prov["provider_symbol"]}[missing] is None


@pytest.mark.parametrize("wrong", [{"symbol": "AAB.IS"}, {"exchangeName": "NMS"}, {"currency": "USD"}])
def test_identity_mismatch_fails_closed(monkeypatch, wrong):
    p, _ = provider_with(monkeypatch, GOOD | wrong)
    with pytest.raises(pp.ProviderIdentityError):
        p.get_history_with_provenance("AAA")


def test_metadata_read_without_second_request(monkeypatch):
    p, t = provider_with(monkeypatch, GOOD)
    p.get_history_with_provenance("AAA", period="1mo")
    assert t.calls == 1


LOT = ("a1", PortfolioPosition(user_id="u1", asset="AAA", buy_price=100.0, quantity=10.0,
                               buy_date=datetime(2025, 7, 1, 10, 0, tzinfo=ISTANBUL_TZ),
                               created_at=datetime(2025, 7, 1, 10, 0, tzinfo=ISTANBUL_TZ)))


class Repo:
    def list_for_user(self, user_id):
        return [LOT]


def check(monkeypatch, meta, **kw):
    p, t = provider_with(monkeypatch, meta)
    out = lc.check_limits("u1", "AAA", lc.position_version([LOT]), {"max_loss_pct": 8.0}, Repo(), p, clock=lambda: NOW, **kw)
    return out, t


def test_verified_identity_with_yahoo_adjusted_basis_is_still_price_basis_unverified(monkeypatch):
    out, _ = check(monkeypatch, GOOD)
    assert out["state"] == lc.STATE_NOT_EVALUATED and out["block_code"] == pr.PRICE_BASIS_UNVERIFIED
    assert out["price_provenance"]["identity_check"] == "MATCH"
    assert out["price_provenance"]["price_basis"] == "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
    assert out["checks"] is None and out["price_used"] is None


def test_verified_identity_and_raw_basis_reaches_corporate_action_gate(monkeypatch):
    out, _ = check(monkeypatch, GOOD, price_basis=pr.RAW_BASIS)  # yalnız test yolu; üretim beyanı değişmedi
    assert out["block_code"] == pr.CORPORATE_ACTIONS_UNVERIFIED and out["checks"] is None


def test_identity_mismatch_blocks_limit_without_using_data(monkeypatch):
    out, _ = check(monkeypatch, GOOD | {"currency": "USD"}, price_basis=pr.RAW_BASIS)
    assert out["block_code"] == lc.PRICE_IDENTITY_MISMATCH
    assert out["price_provenance"] is None and out["price_used"] is None and out["checks"] is None


CLEAN_CA = {"checked_from": "2025-07-01", "checked_through": "2025-07-11", "split_or_bonus_dates": []}
NO_CURRENCY = {k: v for k, v in GOOD.items() if k != "currency"}


def test_A_unverified_identity_blocks_even_with_raw_basis_and_clean_corporate_actions(monkeypatch):
    out, _ = check(monkeypatch, NO_CURRENCY, price_basis=pr.RAW_BASIS, corporate_action_check=CLEAN_CA)
    assert out["state"] == lc.STATE_NOT_EVALUATED and out["block_code"] == lc.PRICE_IDENTITY_UNVERIFIED
    assert out["checks"] is None and out["price_used"] is None


def test_D_match_raw_and_clean_corporate_actions_reaches_limit_evaluation(monkeypatch):
    out, _ = check(monkeypatch, GOOD, price_basis=pr.RAW_BASIS, corporate_action_check=CLEAN_CA)
    assert out["state"] == lc.STATE_WITHIN and out["block_code"] is None
    assert out["checks"]["max_loss"]["status"] == pr.LIMIT_WITHIN and out["price_used"]["close"] == 110.0


@pytest.mark.parametrize("wrong", [{"symbol": "AAB.IS"}, {"exchangeName": "NMS"}, {"currency": "USD"}])
def test_EFG_mismatch_blocks_before_any_gate(monkeypatch, wrong):
    out, _ = check(monkeypatch, GOOD | wrong, price_basis=pr.RAW_BASIS, corporate_action_check=CLEAN_CA)
    assert out["block_code"] == lc.PRICE_IDENTITY_MISMATCH and out["checks"] is None and out["price_used"] is None


@pytest.mark.parametrize("missing", ["currency", "exchangeName", "symbol"])
def test_H_unverified_never_presented_as_result_and_precedes_basis_gate(monkeypatch, missing):
    meta = {k: v for k, v in GOOD.items() if k != missing}
    out, _ = check(monkeypatch, meta)  # üretim beyanı (düzeltilmiş Yahoo) ile de kimlik kapısı önce
    assert out["block_code"] == lc.PRICE_IDENTITY_UNVERIFIED
    assert out["state"] not in (lc.STATE_WITHIN, lc.STATE_EXCEEDED)
    assert out["checks"] is None and out["price_used"] is None and out.get("last_known_price") is None
    prov = out["price_provenance"]
    assert prov["identity_check"] == "UNVERIFIED" and prov["price_basis"] == "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
    assert {"currency": prov["currency"], "exchangeName": prov["exchange"], "symbol": prov["provider_symbol"]}[missing] is None
