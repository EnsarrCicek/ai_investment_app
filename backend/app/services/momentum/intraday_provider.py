"""Gün içi (intraday) fiyat/hacim sağlayıcısı — erken momentum alarmı için.

Dondurulmuş `bist_provider.py` DEĞİŞTİRİLMEZ; yalnız onun ağ deneme yardımcısı (`_fetch_with_retry`) ve
`bist_provenance_provider`'ın kimlik doğrulaması (aynı yanıtın meta bilgisi, ek istek yok) yeniden kullanılır.

Yahoo/yfinance gözlemleri (12.10.2026, KTLEV.IS):
* aralıklar: 1m (~7 işlem günü geriye), 5m/15m/30m (~60 gün), 60m (daha uzun);
* zaman damgası barın BAŞLANGICIDIR, saat dilimi Europe/Istanbul; ilk bar 09:55 (açılış seansı);
* OHLCV tam; hacim var (KTLEV 5m barlarında hacmi 0 olan bar oranı %1.1);
* BIST verisi ~15 dk gecikmeli (15:54'te son bar 15:39);
* son bar sağlayıcıda hâlâ oluşuyor olabilir — motor yalnız tamamlanmış barları kullanır;
* `history()` varsayılanı düzeltilmiş seri; gün içi momentum yalnız göreli hareket ölçtüğünden fiyat temeli iddiası
  taşınmaz.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

import pandas as pd
import yfinance as yf

from app.services.market_data.bist_provenance_provider import _identity, _response_metadata
from app.services.market_data.bist_provider import _fetch_with_retry

SOURCE = "yahoo_finance"
SUPPORTED_INTERVALS = ("1m", "2m", "5m", "15m", "30m", "60m")


@dataclass(frozen=True)
class IntradayBars:
    symbol: str
    interval: str
    bars: pd.DataFrame  # Open/High/Low/Close/Volume, tz-aware bar BAŞLANGIÇ zamanları (Europe/Istanbul)
    provenance: dict  # requested_symbol, provider_symbol, currency, exchange, identity_check, source, retrieved_at


class IntradayMarketDataProvider(Protocol):
    def get_intraday(self, symbol: str, interval: str = "5m", period: str | None = None,
                     start: datetime | None = None, end: datetime | None = None) -> IntradayBars:
        ...


class YahooIntradayProvider:
    """Tek istek + aynı yanıtın kimlik meta bilgisi. Kimlik uyuşmazlığında `ProviderIdentityError` (ValueError)."""

    def get_intraday(self, symbol: str, interval: str = "5m", period: str | None = None,
                     start: datetime | None = None, end: datetime | None = None) -> IntradayBars:
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"desteklenmeyen aralık: {interval}")
        if (period is None) == (start is None or end is None):
            raise ValueError("ya 'period' ya da 'start' + 'end' verilmelidir")
        ticker = yf.Ticker(f"{symbol}.IS")
        if period is not None:
            history = _fetch_with_retry(lambda: ticker.history(period=period, interval=interval))
        else:
            history = _fetch_with_retry(lambda: ticker.history(start=start, end=end, interval=interval))
        retrieved_at = datetime.now(timezone.utc)
        if history.empty:
            raise ValueError(f"'{symbol}' için gün içi veri bulunamadı (interval={interval})")
        meta = _response_metadata(ticker)
        currency, exchange, identity_check = _identity(symbol, meta)
        provenance = {"requested_symbol": symbol, "provider_symbol": meta.get("symbol"), "currency": currency,
                      "exchange": exchange, "identity_check": identity_check, "source": SOURCE,
                      "retrieved_at": retrieved_at}
        return IntradayBars(symbol, interval, history[["Open", "High", "Low", "Close", "Volume"]], provenance)


class CachedIntradayProvider:
    """Süreç içi kısa ömürlü önbellek. Anahtar tam sözleşmeyi içerir (sembol, aralık, dönem/başlangıç/bitiş,
    kaynak). Süresi dolan kayıt ASLA sunulmaz. Aynı anahtar için eşzamanlı istekler tek yüklemeyi paylaşır."""

    def __init__(self, inner: IntradayMarketDataProvider, ttl_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self._inner, self._ttl, self._clock = inner, ttl_seconds, clock
        self._lock = threading.Lock()
        self._entries: dict[tuple, tuple[float, IntradayBars]] = {}
        self._key_locks: dict[tuple, threading.Lock] = {}

    def get_intraday(self, symbol: str, interval: str = "5m", period: str | None = None,
                     start: datetime | None = None, end: datetime | None = None) -> IntradayBars:
        key = (symbol.upper(), interval, period, start, end, SOURCE)
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:
                hit = self._entries.get(key)
            if hit is not None and self._clock() < hit[0]:
                return hit[1]
            value = self._inner.get_intraday(symbol, interval=interval, period=period, start=start, end=end)
            with self._lock:
                self._entries[key] = (self._clock() + self._ttl, value)
            return value
