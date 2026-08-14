import pandas as pd
import yfinance as yf

from app.models.market_data import MarketData
from app.services.market_data.base import MarketDataProvider


class BistProvider(MarketDataProvider):
    """BIST hisseleri için Yahoo Finance tabanlı market data adaptörü."""

    SOURCE = "yahoo_finance"

    def get_latest(self, symbol: str) -> MarketData:
        ticker = yf.Ticker(f"{symbol}.IS")
        history = ticker.history(period="5d")
        if history.empty:
            raise ValueError(f"'{symbol}' için market data bulunamadı")

        row = history.iloc[-1]
        return MarketData(
            asset_id=symbol,
            timestamp=history.index[-1].to_pydatetime(),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
            source=self.SOURCE,
        )

    def get_history(self, symbol: str, period: str = "6mo") -> pd.DataFrame:
        ticker = yf.Ticker(f"{symbol}.IS")
        history = ticker.history(period=period)
        if history.empty:
            raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı")
        return history[["Open", "High", "Low", "Close", "Volume"]]
