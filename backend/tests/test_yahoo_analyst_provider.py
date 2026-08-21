import pandas as pd

from app.services.analysts import yahoo_analyst_provider as provider_module
from app.services.analysts.yahoo_analyst_provider import YahooAnalystProvider


class _FakeTicker:
    def __init__(self, price_targets, recommendations_df):
        self.analyst_price_targets = price_targets
        self.recommendations = recommendations_df


def test_get_raw_parses_price_targets_and_recommendations(monkeypatch):
    recs = pd.DataFrame(
        [
            {"period": "0m", "strongBuy": 3, "buy": 8, "hold": 2, "sell": 0, "strongSell": 0},
            {"period": "-1m", "strongBuy": 3, "buy": 7, "hold": 2, "sell": 0, "strongSell": 0},
        ]
    )
    fake_ticker = _FakeTicker(
        price_targets={"current": 301.25, "high": 580.0, "low": 330.0, "mean": 463.5, "median": 460.0},
        recommendations_df=recs,
    )
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    raw = YahooAnalystProvider().get_raw("THYAO")

    assert raw["price_targets"]["mean"] == 463.5
    assert len(raw["recommendations"]) == 2
    assert raw["recommendations"][0] == {
        "period": "0m",
        "strong_buy": 3,
        "buy": 8,
        "hold": 2,
        "sell": 0,
        "strong_sell": 0,
    }


def test_get_raw_handles_empty_recommendations(monkeypatch):
    fake_ticker = _FakeTicker(price_targets={"current": 2.27}, recommendations_df=pd.DataFrame())
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: fake_ticker)

    raw = YahooAnalystProvider().get_raw("SASA")

    assert raw["price_targets"] == {"current": 2.27}
    assert raw["recommendations"] == []


def test_get_raw_tolerates_ticker_errors(monkeypatch):
    class _BrokenTicker:
        @property
        def analyst_price_targets(self):
            raise ValueError("boom")

        @property
        def recommendations(self):
            raise ValueError("boom")

    monkeypatch.setattr(provider_module.yf, "Ticker", lambda _symbol: _BrokenTicker())

    raw = YahooAnalystProvider().get_raw("XYZ")

    assert raw == {"price_targets": {}, "recommendations": []}
