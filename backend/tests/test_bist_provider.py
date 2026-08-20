import pandas as pd
import pytest

from app.services.market_data import bist_provider as bist_provider_module
from app.services.market_data.bist_provider import BistProvider


def _daily_df(rows):
    index = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


class _FakeFastInfo(dict):
    pass


class _FakeTicker:
    def __init__(self, intraday_df, daily_df, previous_close):
        self._intraday_df = intraday_df
        self._daily_df = daily_df
        self.fast_info = _FakeFastInfo(previousClose=previous_close)

    def history(self, period=None, interval=None, **kwargs):
        if interval == "5m":
            return self._intraday_df
        return self._daily_df


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(bist_provider_module.time, "sleep", lambda *_args, **_kwargs: None)


def test_get_quote_falls_back_to_daily_bar_when_intraday_empty(monkeypatch):
    daily = _daily_df(
        [
            ("2026-08-18", 298.5, 302.5, 297.75, 300.5, 27_211_586),
            ("2026-08-20", 302.0, 302.0, 302.0, 302.0, 315_940),
        ]
    )
    fake_ticker = _FakeTicker(intraday_df=pd.DataFrame(), daily_df=daily, previous_close=301.25)
    monkeypatch.setattr(bist_provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    quote = BistProvider().get_quote("THYAO")

    assert quote.last_price == 302.0
    assert quote.previous_close == 301.25
    assert quote.open == 302.0
    assert quote.volume == 315_940
    assert quote.timestamp.date().isoformat() == "2026-08-20"


def test_get_quote_derives_previous_close_from_daily_when_fast_info_missing(monkeypatch):
    daily = _daily_df(
        [
            ("2026-08-18", 298.5, 302.5, 297.75, 300.5, 27_211_586),
            ("2026-08-20", 302.0, 302.0, 302.0, 302.0, 315_940),
        ]
    )
    fake_ticker = _FakeTicker(intraday_df=pd.DataFrame(), daily_df=daily, previous_close=None)
    monkeypatch.setattr(bist_provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    quote = BistProvider().get_quote("THYAO")

    assert quote.previous_close == 300.5


def test_get_quote_raises_when_both_intraday_and_daily_are_empty(monkeypatch):
    fake_ticker = _FakeTicker(intraday_df=pd.DataFrame(), daily_df=pd.DataFrame(), previous_close=301.25)
    monkeypatch.setattr(bist_provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    with pytest.raises(ValueError):
        BistProvider().get_quote("THYAO")


def test_get_quote_uses_intraday_when_available(monkeypatch):
    intraday = pd.DataFrame(
        {
            "Open": [301.0, 301.5],
            "High": [302.0, 302.5],
            "Low": [300.5, 301.0],
            "Close": [301.5, 302.0],
            "Volume": [1000, 1500],
        },
        index=pd.to_datetime(["2026-08-20 10:00", "2026-08-20 10:05"]),
    )
    fake_ticker = _FakeTicker(intraday_df=intraday, daily_df=pd.DataFrame(), previous_close=300.0)
    monkeypatch.setattr(bist_provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    quote = BistProvider().get_quote("THYAO")

    assert quote.last_price == 302.0
    assert quote.open == 301.0
    assert quote.volume == 2500
