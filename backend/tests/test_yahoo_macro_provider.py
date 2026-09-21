from datetime import datetime, timedelta, timezone

import pandas as pd

from app.services.macro import yahoo_macro_provider as provider_module
from app.services.macro.yahoo_macro_provider import TICKERS, YahooMacroProvider


class _FakeTicker:
    def __init__(self, closes, dates=None):
        self._closes = closes
        self._dates = dates

    def history(self, period):
        if self._closes is None:
            return pd.DataFrame()
        if self._dates is not None:
            index = pd.DatetimeIndex(self._dates)
        else:
            # Varsayılan: en son bar "bugün" (UTC, tz-aware) olacak şekilde geriye
            # doğru günlük DatetimeIndex -- gerçek yfinance davranışını yansıtır
            # (HATA 16C öncesi fixture'lar RangeIndex kullanıyordu, bu HATA 16C'nin
            # observed_at çıkarımını sessizce test edilemez bırakırdı).
            end = pd.Timestamp.now(tz="UTC").normalize()
            index = pd.date_range(end=end, periods=len(self._closes), freq="D", tz="UTC")
        return pd.DataFrame({"Close": self._closes}, index=index)


def test_get_indicator_changes_computes_pct_change_over_twenty_bar_window(monkeypatch):
    # window=20 (varsayılan) -> geçmiş >= 21 bar gerektirir; past=closes[-21],
    # current=closes[-1].
    closes = [100.0] * 20 + [110.0]
    fake = _FakeTicker(closes)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    assert set(result.keys()) == set(TICKERS.keys())
    for key in TICKERS:
        assert result[key]["value"] == 110.0
        assert result[key]["pct_change"] == 10.0


def test_get_indicator_changes_excludes_empty_history(monkeypatch):
    fake = _FakeTicker(None)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    assert result == {}


def test_get_indicator_changes_excludes_insufficient_history(monkeypatch):
    closes = [100.0] * 10  # 10 < window+1(=21)
    fake = _FakeTicker(closes)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    assert result == {}


def test_get_indicator_changes_includes_exact_boundary_length(monkeypatch):
    # len == window+1 (21) sınırda dahil edilmeli (yalnızca strictly-less hariç tutar).
    closes = [100.0] * 20 + [105.0]
    assert len(closes) == 21
    fake = _FakeTicker(closes)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    assert set(result.keys()) == set(TICKERS.keys())


def test_get_indicator_changes_handles_per_ticker_partial_failure(monkeypatch):
    good_closes = [100.0] * 20 + [105.0]
    bad_symbol = TICKERS["dxy"]

    def fake_ticker_factory(symbol):
        if symbol == bad_symbol:
            return _FakeTicker([100.0] * 5)  # yetersiz geçmiş
        return _FakeTicker(good_closes)

    monkeypatch.setattr(provider_module.yf, "Ticker", fake_ticker_factory)

    result = YahooMacroProvider().get_indicator_changes()

    assert "dxy" not in result
    assert set(result.keys()) == set(TICKERS.keys()) - {"dxy"}
    # HATA 16C: başarılı ticker'lar için observed_at hâlâ mevcut olmalı --
    # kısmi provider hatası freshness metadata çıkarımını bozmaz.
    for key in result:
        assert result[key]["observed_at"] is not None


# ---------------------------------------------------------------------------
# HATA 16C — observed_at extraction / timezone handling
# ---------------------------------------------------------------------------


def test_get_indicator_changes_observed_at_is_utc_aware_and_recent(monkeypatch):
    closes = [100.0] * 20 + [110.0]
    fake = _FakeTicker(closes)  # varsayılan tarihler: en son bar "bugün" UTC
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    now = datetime.now(timezone.utc)
    for key in TICKERS:
        observed_at = result[key]["observed_at"]
        assert isinstance(observed_at, datetime)
        assert observed_at.tzinfo is not None
        assert observed_at.tzinfo.utcoffset(observed_at) == timedelta(0)
        assert abs((now - observed_at).total_seconds()) < 2 * 24 * 3600


def test_get_indicator_changes_converts_naive_index_to_utc(monkeypatch):
    # yfinance normalde tz-aware index döner, ama garanti değildir (HATA 16C
    # audit notu) -- tz-naive bir index UTC olarak KABUL EDİLİR, None DEĞİL.
    closes = [100.0] * 20 + [105.0]
    naive_dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=len(closes), freq="D")
    fake = _FakeTicker(closes, dates=naive_dates)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    for key in TICKERS:
        observed_at = result[key]["observed_at"]
        assert observed_at is not None
        assert observed_at.tzinfo is not None


def test_get_indicator_changes_normalizes_non_utc_timezone_to_utc(monkeypatch):
    # Farklı borsa saat dilimlerinden gelen tz-aware timestamp'lar UTC'ye
    # normalize edilmeli (HATA 16C madde 9: timezone-safe karşılaştırma).
    closes = [100.0] * 20 + [108.0]
    end_utc = pd.Timestamp.now(tz="UTC").normalize()
    index_utc = pd.date_range(end=end_utc, periods=len(closes), freq="D", tz="UTC")
    offset_tz = timezone(timedelta(hours=5))
    index_offset = index_utc.tz_convert(offset_tz)
    fake = _FakeTicker(closes, dates=index_offset)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake)

    result = YahooMacroProvider().get_indicator_changes()

    for key in TICKERS:
        observed_at = result[key]["observed_at"]
        assert observed_at.tzinfo == timezone.utc
