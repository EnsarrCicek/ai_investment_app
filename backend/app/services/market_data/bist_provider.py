import pandas as pd
import yfinance as yf

from app.models.market_data import MarketData, Quote
from app.services.market_data.base import MarketDataProvider


class BistProvider(MarketDataProvider):
    """BIST hisseleri için Yahoo Finance (yfinance) tabanlı, tamamen ücretsiz
    market data adaptörü. Yahoo'nun kendi verisi hafif gecikmelidir (gün içi
    barlarda gözlemlenen gecikme ~15 dk); bu asla gizlenmez — get_quote/
    get_history her zaman verinin gerçek timestamp'ini döner, hesaplanmış/
    uydurma bir "şimdi" değeri üretilmez.
    """

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

    def get_quote(self, symbol: str) -> Quote:
        ticker = yf.Ticker(f"{symbol}.IS")
        intraday = ticker.history(period="1d", interval="5m")
        if intraday.empty:
            raise ValueError(f"'{symbol}' için güncel fiyat bulunamadı")

        previous_close = ticker.fast_info.get("previousClose")
        if previous_close is None:
            raise ValueError(f"'{symbol}' için önceki kapanış bulunamadı")
        previous_close = float(previous_close)

        last_price = float(intraday.iloc[-1]["Close"])
        change = last_price - previous_close
        change_percent = (change / previous_close * 100) if previous_close else None

        return Quote(
            asset_id=symbol,
            timestamp=intraday.index[-1].to_pydatetime(),
            last_price=last_price,
            previous_close=previous_close,
            change=change,
            change_percent=change_percent,
            open=float(intraday.iloc[0]["Open"]),
            high=float(intraday["High"].max()),
            low=float(intraday["Low"].min()),
            volume=int(intraday["Volume"].sum()),
            source=self.SOURCE,
        )

    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        ticker = yf.Ticker(f"{symbol}.IS")
        history = ticker.history(period=period, interval=interval)
        if history.empty:
            raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı (period={period}, interval={interval})")
        return history[["Open", "High", "Low", "Close", "Volume"]]
