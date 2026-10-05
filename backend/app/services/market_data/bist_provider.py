import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from app.models.market_data import MarketData, Quote
from app.services.market_data.base import MarketDataProvider

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 2.0


EXPECTED_EXCHANGE = "IST"
# yfinance `history()` varsayılanı auto_adjust=True: geçmiş kurumsal işlemlere göre DÜZELTİLMİŞ seri.
YAHOO_PRICE_BASIS = "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
EXPECTED_CURRENCY = "TRY"
INTRADAY_INTERVAL = "5m"
INTRADAY_BAR = timedelta(minutes=5)


def _response_metadata(ticker) -> dict:
    """Son `history()` yanıtının Yahoo 'meta' bölümü — EK İSTEK YAPMADAN. yfinance 1.5.2'nin genel
    `history_metadata` özelliği eksik alan olduğunda yeni bir gün içi istek atabildiği için kullanılmaz;
    aynı yanıtta saklanan iç sözlük okunur. Bulunamazsa {} (alanlar bilinmiyor kalır)."""
    meta = getattr(getattr(ticker, "_price_history", None), "_history_metadata", None)
    return dict(meta) if isinstance(meta, dict) else {}


class ProviderIdentityError(ValueError):
    """Sağlayıcının bildirdiği sembol/borsa/para birimi beklenenle açıkça uyuşmuyor (ValueError alt sınıfı:
    mevcut çağıranların ValueError yakalama davranışı değişmez)."""


def _identity(symbol: str, meta: dict) -> tuple[str | None, str | None, str]:
    """(currency, exchange, identity_check). Uyuşmazlıkta ProviderIdentityError; eksikse UNVERIFIED (varsayılan
    yazılmaz). Beklenen değerler yalnız karşılaştırma içindir, sonuç alanını doldurmaz."""
    reported = {"symbol": meta.get("symbol"), "exchange": meta.get("exchangeName"), "currency": meta.get("currency")}
    expected = {"symbol": f"{symbol}.IS", "exchange": EXPECTED_EXCHANGE, "currency": EXPECTED_CURRENCY}
    wrong = {k: v for k, v in reported.items() if v is not None and v != expected[k]}
    if wrong:
        raise ProviderIdentityError(f"'{symbol}' için sağlayıcı kimliği beklenenle uyuşmuyor: {wrong}")
    status = "MATCH" if all(v is not None for v in reported.values()) else "UNVERIFIED"
    return reported["currency"], reported["exchange"], status


def _to_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    ts = pd.Timestamp(value)
    return ts.tz_convert("UTC").to_pydatetime() if ts.tzinfo else None


def _verified_last_trade(meta: dict, price: float, bar_start: datetime) -> datetime | None:
    """Son işlem zamanı yalnız AYNI yanıtta, AYNI fiyatla ve bar aralığı içinde bildirilmişse."""
    if bar_start.tzinfo is None:
        return None
    start = bar_start.astimezone(timezone.utc)
    candidates = []
    lt = meta.get("lastTrade")
    if isinstance(lt, dict):
        candidates.append((lt.get("Price"), lt.get("Time")))
    candidates.append((meta.get("regularMarketPrice"), meta.get("regularMarketTime")))
    for cand_price, cand_time in candidates:
        at = _to_utc(cand_time)
        if cand_price is None or at is None:
            continue
        if abs(float(cand_price) - price) < 1e-9 and start <= at < start + INTRADAY_BAR:
            return at
    return None


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
        currency, exchange, identity_check = _identity(symbol, _response_metadata(ticker))

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
            currency=currency,
            exchange=exchange,
            identity_check=identity_check,
            price_basis=YAHOO_PRICE_BASIS,
        )

    def get_quote(self, symbol: str) -> Quote:
        ticker = yf.Ticker(f"{symbol}.IS")
        intraday = _fetch_with_retry(lambda: ticker.history(period="1d", interval=INTRADAY_INTERVAL))
        retrieved_at = datetime.now(timezone.utc)
        daily = None

        if not intraday.empty:
            last_price = float(intraday.iloc[-1]["Close"])
            timestamp = intraday.index[-1].to_pydatetime()
            open_price = float(intraday.iloc[0]["Open"])
            high = float(intraday["High"].max())
            low = float(intraday["Low"].min())
            volume = int(intraday["Volume"].sum())
            meta = _response_metadata(ticker)
            provenance = {"price_type": "INTRADAY_BAR_CLOSE", "interval": INTRADAY_INTERVAL, "fallback_used": False,
                          "fallback_reason": None,
                          "last_trade_at": _verified_last_trade(meta, last_price, timestamp)}
        else:
            # Yahoo'nun 5 dakikalık gün-içi verisi ara sıra (özellikle seans
            # açılışında) boş dönebiliyor — bu GERÇEK bir delisting değil
            # (bkz. KURULUM_GUNLUGU.md AŞAMA 48/16). Bu durumda günlük bar'a
            # düşülür; timestamp yine verinin GERÇEK ait olduğu günü gösterir,
            # sahte bir "şimdi" değeri üretilmez.
            daily = _fetch_with_retry(lambda: ticker.history(period="5d"))
            retrieved_at = datetime.now(timezone.utc)
            if daily.empty:
                raise ValueError(f"'{symbol}' için güncel fiyat bulunamadı")
            meta = _response_metadata(ticker)
            provenance = {"price_type": "DAILY_BAR_CLOSE", "interval": "1d", "fallback_used": True,
                          "fallback_reason": "INTRADAY_EMPTY", "last_trade_at": None}
            row = daily.iloc[-1]
            last_price = float(row["Close"])
            timestamp = daily.index[-1].to_pydatetime()
            open_price = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            volume = int(row["Volume"])

        currency, exchange, identity_check = _identity(symbol, meta)  # fiyat yanıtının kendi meta bilgisi

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
            bar_start=timestamp,
            retrieved_at=retrieved_at,
            currency=currency,
            exchange=exchange,
            identity_check=identity_check,
            **provenance,
        )

    def get_history_with_provenance(self, symbol: str, period: str = "6mo", interval: str = "1d") -> tuple[pd.DataFrame, dict]:
        """`get_history(period=...)` ile aynı tek istek + aynı yanıtın kimlik meta bilgisi (EK İSTEK YOK).

        Döner: (OHLCV DataFrame, provenance). provenance: requested_symbol, provider_symbol, currency, exchange,
        identity_check (MATCH | UNVERIFIED), source, retrieved_at (bu çağrının yanıt alındığı UTC anı). Kimlik
        uyuşmazlığında ProviderIdentityError. Fiyat temeli hakkında İDDİA TAŞIMAZ (yfinance varsayılanı düzeltilmiş seri)."""
        ticker = yf.Ticker(f"{symbol}.IS")
        history = _fetch_with_retry(lambda: ticker.history(period=period, interval=interval))
        retrieved_at = datetime.now(timezone.utc)
        if history.empty:
            raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı (period={period}, interval={interval})")
        meta = _response_metadata(ticker)
        currency, exchange, identity_check = _identity(symbol, meta)
        provenance = {"requested_symbol": symbol, "provider_symbol": meta.get("symbol"), "currency": currency,
                      "exchange": exchange, "identity_check": identity_check, "source": self.SOURCE,
                      "retrieved_at": retrieved_at}
        return history[["Open", "High", "Low", "Close", "Volume"]], provenance

    def get_history(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """HATA 2C (25.08.2026): İki AYRI mod destekler — `period` (varsayılan,
        geriye dönük uyumlu, `BacktestEngine` ve diğer tüm mevcut çağıranlar
        bunu kullanmaya devam eder) VEYA açık `start`/`end` (yalnızca
        `TechnicalAnalysisEngine`'in pre-roll sözleşmesi için, bkz.
        `history_window.py`). İKİSİ BİRDEN Yahoo'ya asla gönderilmez.

        `start`/`end` verilirse İKİSİ DE verilmelidir. Ölçüldü: yfinance'te
        `end` EXCLUSIVE'dir — bugünü de kapsamak isteyen çağıran `end` için
        yarının tarihini geçirmelidir (bkz. `history_window.compute_history_window`).
        """
        if start is not None or end is not None:
            if start is None or end is None:
                raise ValueError("get_history: 'start' ve 'end' birlikte verilmelidir (period ile karıştırılamaz)")
            ticker = yf.Ticker(f"{symbol}.IS")
            history = _fetch_with_retry(lambda: ticker.history(start=start, end=end, interval=interval))
            if history.empty:
                raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı (start={start}, end={end}, interval={interval})")
            return history[["Open", "High", "Low", "Close", "Volume"]]

        ticker = yf.Ticker(f"{symbol}.IS")
        history = _fetch_with_retry(lambda: ticker.history(period=period, interval=interval))
        if history.empty:
            raise ValueError(f"'{symbol}' için geçmiş veri bulunamadı (period={period}, interval={interval})")
        return history[["Open", "High", "Low", "Close", "Volume"]]
