from abc import ABC, abstractmethod

import pandas as pd

from app.models.market_data import MarketData


class MarketDataProvider(ABC):
    """Provider arayüzü — engine'ler doğrudan bir veri kaynağına bağlanmaz (ana doküman bölüm 67)."""

    @abstractmethod
    def get_latest(self, symbol: str) -> MarketData: ...

    @abstractmethod
    def get_history(self, symbol: str, period: str = "6mo") -> pd.DataFrame:
        """Open/High/Low/Close/Volume sütunlu, tarih indeksli geçmiş veri döndürür."""
        ...
