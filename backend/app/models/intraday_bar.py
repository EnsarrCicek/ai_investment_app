from datetime import datetime

from pydantic import BaseModel


class IntradayBar(BaseModel):
    """5 dakikalık gün-içi bar (AŞAMA 48/14b — VWAP ve BIST seans-zamanlaması
    rejimi için gerekli; yfinance intraday veriyi yalnızca ~60 gün geriye
    saklıyor, bu yüzden kendi geçmişimizi biriktirmemiz gerekiyor — bkz.
    scripts/fetch_intraday_bars.py).

    `session_date` (YYYY-MM-DD, Europe/Istanbul takvim günü) ayrı bir alan
    olarak tutulur — "bir varlığın belirli bir seans günündeki tüm barları"
    sorgusu, timestamp üzerinde aralık sorgusu yerine tek bir eşitlik
    filtresiyle (composite index gerektirmeden) yapılabilsin diye.
    """

    asset_id: str
    session_date: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
