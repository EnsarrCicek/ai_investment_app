from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.services.market_data.benchmark_service import CACHE_TTL_SECONDS, get_benchmark_close_series


class _FakeBenchmarkCacheRepo:
    def __init__(self, cached: tuple[dict, datetime] | None = None):
        self._cached = cached
        self.set_calls: list[dict] = []

    def get(self):
        return self._cached

    def set(self, close_by_date, fetched_at):
        self.set_calls.append(close_by_date)
        self._cached = (close_by_date, fetched_at)


def _history_df(rows: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    idx = pd.date_range(end=pd.Timestamp.now(tz="Europe/Istanbul").normalize(), periods=rows, freq="D")
    return pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": 1000.0}, index=idx
    )


def test_fetches_and_caches_when_no_cache_exists(fake_provider):
    provider = fake_provider(history_df=_history_df())
    cache_repo = _FakeBenchmarkCacheRepo(cached=None)

    series = get_benchmark_close_series(provider=provider, cache_repo=cache_repo)

    assert len(series) == 30
    assert all(isinstance(idx, date) for idx in series.index)
    assert len(cache_repo.set_calls) == 1  # yeni veri önbelleğe yazıldı


def test_returns_cached_series_without_calling_provider_when_fresh(fake_provider):
    close_by_date = {"2026-08-01": 100.0, "2026-08-02": 101.0}
    cached = (close_by_date, datetime.now(timezone.utc) - timedelta(seconds=60))  # 1 dakika önce
    provider = fake_provider(history_df=None)  # get_history çağrılırsa NotImplementedError patlar
    cache_repo = _FakeBenchmarkCacheRepo(cached=cached)

    series = get_benchmark_close_series(provider=provider, cache_repo=cache_repo)

    assert len(series) == 2
    assert series[date(2026, 8, 1)] == 100.0
    assert cache_repo.set_calls == []  # önbellek tazeyken yeniden yazılmadı


def test_refetches_when_cache_is_stale(fake_provider):
    stale_cached = ({"2026-01-01": 90.0}, datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS + 60))
    provider = fake_provider(history_df=_history_df())
    cache_repo = _FakeBenchmarkCacheRepo(cached=stale_cached)

    series = get_benchmark_close_series(provider=provider, cache_repo=cache_repo)

    assert len(series) == 30
    assert len(cache_repo.set_calls) == 1


def test_returned_series_is_sorted_by_date(fake_provider):
    close_by_date = {"2026-08-03": 102.0, "2026-08-01": 100.0, "2026-08-02": 101.0}
    cached = (close_by_date, datetime.now(timezone.utc))
    provider = fake_provider(history_df=None)
    cache_repo = _FakeBenchmarkCacheRepo(cached=cached)

    series = get_benchmark_close_series(provider=provider, cache_repo=cache_repo)

    assert list(series.index) == [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)]
