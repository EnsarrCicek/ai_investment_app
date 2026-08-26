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
    def get_history(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Open/High/Low/Close/Volume sütunlu, tarih indeksli geçmiş veri döndürür.

        `interval`, yfinance'in desteklediği herhangi bir değer olabilir
        (ör. "5m" gün-içi grafik için, "1wk"/"1mo"/"3mo" uzun dönem grafikler
        için) — `period` ile tutarlı olmalıdır (yfinance kısıtları geçerlidir,
        ör. "5m" interval en fazla ~60 gün geriye gidebilir).

        HATA 2C (25.08.2026): `start`/`end` (ikisi birlikte) verilirse `period`
        yok sayılır — açık tarih aralığı modu. Yalnızca `TechnicalAnalysisEngine`'in
        pre-roll sözleşmesi için (bkz. `history_window.py`); diğer tüm
        çağıranlar `period` kullanmaya devam eder.
        """
        ...
