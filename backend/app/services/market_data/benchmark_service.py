"""XU100 (BIST100 endeksi) kapanış serisini TTL'li önbellekten okur, bayatsa
yeniden çeker (AŞAMA 48/17).

relative_strength.py, her varlığın XU100'e göre göreli gücünü hesaplamak için
endeksin günlük kapanış serisine ihtiyaç duyar. Bu seri TÜM semboller için
AYNIDIR — TechnicalAnalysisEngine her sembolü hesaplarken ayrı ayrı XU100
çekseydi, Dashboard'un 100 sembolü tek seferde yüklediği göz önüne alınırsa
AŞAMA 44'te çözülen N+1 istek sorununu geri getirirdi. Bu yüzden XU100
serisi burada, technical_analyses ile aynı TTL (15 dk) mantığıyla, TEK bir
Firestore belgesinde önbelleklenir — 100 sembolün ilkinde bir kez çekilir,
geri kalan 99'u önbellekten okur.

Dönen seri `datetime.date` anahtarlıdır (Timestamp değil) — yfinance'in
tz-aware DatetimeIndex'i ile önbellekten geri okunan (tz bilgisi taşımayan)
seri arasındaki uyumsuzluğu baştan önler; relative_strength.py iki seriyi
INDEX'e göre eşleştirdiğinden bu, "hiç ortak tarih bulunamadı" gibi sessiz
bir hataya düşmemek için önemlidir.

Benchmark verisi kendisi bir teknik gösterge DEĞİLDİR (XU100'ün kendi
TechnicalAnalysis'i hesaplanmaz) — yalnızca ham kapanış fiyatı serisi
saklanır.
"""

from datetime import date, datetime, timezone

import pandas as pd

from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

BENCHMARK_SYMBOL = "XU100"
CACHE_TTL_SECONDS = 900  # technical_analyses ile aynı 15 dakika


def _to_date_indexed_series(close_by_date: dict[str, float]) -> pd.Series:
    series = pd.Series(close_by_date, dtype=float)
    series.index = [date.fromisoformat(d) for d in series.index]
    return series.sort_index()


def get_benchmark_close_series(
    provider: MarketDataProvider | None = None,
    cache_repo: BenchmarkCacheRepository | None = None,
    period: str = "6mo",
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> pd.Series:
    cache_repo = cache_repo or BenchmarkCacheRepository()
    cached = cache_repo.get()
    if cached is not None:
        close_by_date, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < max_age_seconds:
            return _to_date_indexed_series(close_by_date)

    provider = provider or BistProvider()
    df = provider.get_history(BENCHMARK_SYMBOL, period=period)
    close_by_date = {ts.date().isoformat(): float(val) for ts, val in df["Close"].items()}
    cache_repo.set(close_by_date, datetime.now(timezone.utc))
    return _to_date_indexed_series(close_by_date)
