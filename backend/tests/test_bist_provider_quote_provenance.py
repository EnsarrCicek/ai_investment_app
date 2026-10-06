"""Quote yanıtının fiyat türü/zaman/kimlik alanları — sahte sağlayıcı yanıtlarıyla, ağsız."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.market_data import bist_provenance_provider as pp
from app.services.market_data import bist_provider as bp


IST = "Europe/Istanbul"
GOOD_META = {"symbol": "ABC.IS", "exchangeName": "IST", "currency": "TRY"}


def _df(index, closes):
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [100] * len(closes)},
                        index=pd.DatetimeIndex(index))


class FakeTicker:
    """`history()` her çağrıda kendi yanıtının meta bilgisini saklar (yfinance iç davranışının sahtesi)."""

    def __init__(self, intraday, daily, intraday_meta=None, daily_meta=None, previous_close=10.0):
        self._resp = {"5m": (intraday, intraday_meta), "1d": (daily, daily_meta)}
        self.fast_info = {"previousClose": previous_close}
        self._price_history = SimpleNamespace(_history_metadata=None)
        self.calls = 0

    def history(self, period=None, interval="1d", **kw):
        self.calls += 1
        df, meta = self._resp["5m" if interval == "5m" else "1d"]
        self._price_history._history_metadata = dict(meta) if meta is not None else None
        return df


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(bp.time, "sleep", lambda *_a, **_k: None)


def quote(monkeypatch, ticker):
    monkeypatch.setattr(bp.yf, "Ticker", lambda _s: ticker)
    return pp.ProvenanceBistProvider().get_quote("ABC")


INTRA = _df(pd.to_datetime(["2026-10-05 11:50", "2026-10-05 11:55"]).tz_localize(IST), [12.0, 12.5])


def test_intraday_bar_close_with_verified_last_trade(monkeypatch):
    meta = GOOD_META | {"lastTrade": {"Price": 12.5, "Time": pd.Timestamp("2026-10-05 11:59:28", tz=IST)}}
    before = datetime.now(timezone.utc)
    q = quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta=meta))
    assert q.price_type == "INTRADAY_BAR_CLOSE" and q.interval == "5m" and q.fallback_used is False
    assert q.bar_start == q.timestamp == pd.Timestamp("2026-10-05 11:55", tz=IST).to_pydatetime()
    assert q.last_trade_at == datetime(2026, 10, 5, 8, 59, 28, tzinfo=timezone.utc)
    assert q.retrieved_at.tzinfo is not None and q.retrieved_at >= before
    assert (q.currency, q.exchange, q.identity_check) == ("TRY", "IST", "MATCH")


def test_last_trade_not_attached_when_price_or_time_differs(monkeypatch):
    other_price = GOOD_META | {"lastTrade": {"Price": 12.4, "Time": pd.Timestamp("2026-10-05 11:59", tz=IST)}}
    assert quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta=other_price)).last_trade_at is None
    outside_bar = GOOD_META | {"regularMarketPrice": 12.5, "regularMarketTime": pd.Timestamp("2026-10-05 12:03", tz=IST).timestamp()}
    assert quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta=outside_bar)).last_trade_at is None


def test_daily_fallback_is_marked_and_uses_daily_response_metadata(monkeypatch):
    daily = _df(pd.to_datetime(["2026-10-02", "2026-10-05"]).tz_localize(IST), [11.0, 11.5])
    q = quote(monkeypatch, FakeTicker(pd.DataFrame(), daily, intraday_meta={"symbol": "ABC.IS"}, daily_meta=GOOD_META))
    assert q.price_type == "DAILY_BAR_CLOSE" and q.interval == "1d"
    assert q.fallback_used is True and q.fallback_reason == "INTRADAY_EMPTY"
    assert q.last_trade_at is None and q.last_price == 11.5 and q.identity_check == "MATCH"


def test_missing_metadata_is_unverified_not_defaulted(monkeypatch):
    q = quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta={"symbol": "ABC.IS"}))
    assert q.currency is None and q.exchange is None and q.identity_check == "UNVERIFIED"
    q2 = quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta=None))
    assert q2.identity_check == "UNVERIFIED" and q2.last_trade_at is None


def test_identity_mismatch_refuses_quote(monkeypatch):
    for bad in ({"currency": "USD"}, {"exchangeName": "NMS"}, {"symbol": "ABD.IS"}):
        with pytest.raises(ValueError):
            quote(monkeypatch, FakeTicker(INTRA, None, intraday_meta=GOOD_META | bad))


def test_metadata_read_without_extra_request(monkeypatch):
    t = FakeTicker(INTRA, None, intraday_meta=GOOD_META)
    quote(monkeypatch, t)
    assert t.calls == 1  # yalnız gün içi istek (önceki kapanış fast_info'dan)


def test_old_style_quote_still_serializes_without_new_fields():
    from app.models.market_data import Quote
    q = Quote(asset_id="ABC", timestamp=datetime(2026, 10, 5, tzinfo=timezone.utc), last_price=1, previous_close=1, change=0,
              change_percent=0, open=1, high=1, low=1, volume=1, source="x")
    d = q.model_dump()
    assert d["price_type"] is None and d["fallback_used"] is None and d["retrieved_at"] is None
