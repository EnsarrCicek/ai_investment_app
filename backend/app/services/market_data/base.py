from abc import ABC, abstractmethod

import pandas as pd

from app.models.market_data import MarketData, Quote


class MarketDataProvider(ABC):
    """Provider arayüzü — engine'ler doğrudan bir veri kaynağına bağlanmaz (ana doküman bölüm 67)."""

    @abstractmethod
    def get_latest(self, symbol: str) -> MarketData: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """Güncel fiyat, önceki kapanış, günlük değişim/yüzde — gerçek timestamp ile."""
        ...

    @abstractmethod
    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        """Open/High/Low/Close/Volume sütunlu, tarih indeksli geçmiş veri döndürür.

        `interval`, yfinance'in desteklediği herhangi bir değer olabilir
        (ör. "5m" gün-içi grafik için, "1wk"/"1mo"/"3mo" uzun dönem grafikler
        için) — `period` ile tutarlı olmalıdır (yfinance kısıtları geçerlidir,
        ör. "5m" interval en fazla ~60 gün geriye gidebilir).
        """
        ...
