from datetime import datetime, timezone

import pytest

from app.models.market_data import MarketData
from app.services.market_data.base import MarketDataProvider


class FakeMarketDataProvider(MarketDataProvider):
    """Testler için Firestore/Yahoo Finance'e hiç gitmeyen sahte provider."""

    def __init__(self, close_price: float = 100.0, history_df=None):
        self._close_price = close_price
        self._history_df = history_df

    def get_latest(self, symbol: str) -> MarketData:
        return MarketData(
            asset_id=symbol,
            timestamp=datetime.now(timezone.utc),
            open=self._close_price,
            high=self._close_price,
            low=self._close_price,
            close=self._close_price,
            volume=0,
            source="fake",
        )

    def get_history(self, symbol: str, period: str = "6mo"):
        if self._history_df is None:
            raise NotImplementedError
        return self._history_df


@pytest.fixture
def fake_provider():
    return FakeMarketDataProvider
