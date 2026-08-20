import time

import pandas as pd
import yfinance as yf

from app.models.market_data import MarketData, Quote
from app.services.market_data.base import MarketDataProvider

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 2.0


def _fetch_with_retry(fetch_fn, attempts: int = DEFAULT_RETRY_ATTEMPTS, delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS):
    """yfinance, eş zamanlı istek altında (ör. Dashboard'un 10'arlı batch'leri)
    ara sıra geçici bir ağ hatası ya da yanıltıcı "possibly delisted" uyarısıyla
    birlikte boş DataFrame döndürebiliyor — bu GERÇEK bir delisting değil,
    Yahoo'nun rate-limit/ağ davranışıdır (bkz. KURULUM_GUNLUGU.md AŞAMA 48/16:
    AKSEN/HEKTS/ISMEN/PATEK için gözlemlendi, izole tekrar denemede hepsi
    sorunsuz veri döndürdü). Bu yüzden ilk deneme boş/hatalı sonuç verirse
    kısa bir bekleme sonrası tekrar denenir; tüm denemeler başarısız olursa
    son sonuç (boş DataFrame ya da fırlatılan istisna) olduğu gibi çağırana
    bırakılır — çağıran zaten "veri yok" durumunu ele alıyor.
    """
    last_result = None
    last_exception: Exception | None = None
    for attempt in range(attempts):
        try:
            last_result = fetch_fn()
            last_exception = None
            if not last_result.empty:
                return last_result
        except Exception as exc:  # yfinance farklı istisna tipleri fırlatabilir
            last_exception = exc
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    if last_exception is not None:
        raise last_exception
    return last_result


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
        history = _fetch_with_retry(lambda: ticker.history(period="5d"))
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
        intraday = _fetch_with_retry(lambda: ticker.history(period="1d", interval="5m"))
        daily = None

        if not intraday.empty:
            last_price = float(intraday.iloc[-1]["Close"])
            timestamp = intraday.index[-1].to_pydatetime()
            open_price = float(intraday.iloc[0]["Open"])
            high = float(intraday["High"].max())
            low = float(intraday["Low"].min())
            volume = int(intraday["Volume"].sum())
        else:
            # Yahoo'nun 5 dakikalık gün-içi verisi ara sıra (özellikle seans
            # açılışında) boş dönebiliyor — bu GERÇEK bir delisting değil
            # (bkz. KURULUM_GUNLUGU.md AŞAMA 48/16). Bu durumda günlük bar'a
            # düşülür; timestamp yine verinin GERÇEK ait olduğu günü gösterir,
            # sahte bir "şimdi" değeri üretilmez.
            daily = _fetch_with_retry(lambda: ticker.history(period="5d"))
            if daily.empty:
                raise ValueError(f"'{symbol}' için güncel fiyat bulunamadı")
            row = daily.iloc[-1]
            last_price = float(row["Close"])
            timestamp = daily.index[-1].to_pydatetime()
            open_price = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            volume = int(row["Volume"])

        previous_close = ticker.fast_info.get("previousClose")
        if previous_close is None:
            if daily is None:
                daily = _fetch_with_retry(lambda: ticker.history(period="5d"))
            if len(daily) >= 2:
                previous_close = float(daily.iloc[-2]["Close"])
        if previous_close is None:
            raise ValueError(f"'{symbol}' için önceki kapanış bulunamadı")
        previous_close = float(previous_close)

        change = last_price - previous_close
        change_percent = (change / previous_close * 100) if previous_close else None

        return Quote(
            asset_id=symbol,
            timestamp=timestamp,
            last_price=last_price,
            previous_close=previous_close,
            change=change,
            change_percent=change_percent,
            open=open_price,
            high=high,
            low=low,
            volume=volume,
            source=self.SOURCE,
        )

    def get_history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        ticker = yf.Ticker(f"{symbol}.IS")
        history = _fetch_with_retry(lambda: ticker.history(period=period, interval=interval))
        if history.empty:
            raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı (period={period}, interval={interval})")
        return history[["Open", "High", "Low", "Close", "Volume"]]
