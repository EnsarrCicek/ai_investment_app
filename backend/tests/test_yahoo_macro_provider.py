import pandas as pd

from app.services.macro import yahoo_macro_provider as provider_module
from app.services.macro.yahoo_macro_provider import TICKERS, YahooMacroProvider


class _FakeTicker:
    def __init__(self, closes):
        self._closes = closes

    def history(self, period):
        if self._closes is None:
            return pd.DataFrame()
        return pd.DataFrame({"Close": self._closes})


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
