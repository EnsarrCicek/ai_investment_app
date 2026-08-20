from datetime import datetime, timedelta, timezone

from app.models.fund_analysis import FundAnalysis
from app.services.funds.analysis_cache_service import CACHE_TTL_SECONDS, get_ranked_funds


def _fund(code, score):
    return FundAnalysis(
        fund_code=code,
        fund_name=f"{code} FONU",
        price=100.0,
        portfolio_size=10_000_000.0,
        investor_count=100,
        composite_score=score,
        as_of_date="2026-08-20",
        generated_at=datetime.now(timezone.utc),
    )


class _FakeCacheRepo:
    def __init__(self, cached=None):
        self._cached = cached
        self.set_calls = []

    def get(self, kind):
        return self._cached

    def set(self, kind, results, fetched_at):
        self.set_calls.append((kind, results))
        self._cached = (results, fetched_at)


class _FakeEngine:
    def __init__(self, results):
        self._results = results
        self.analyze_all_calls = 0

    def analyze_all(self, kind="YAT"):
        self.analyze_all_calls += 1
        return self._results


def test_computes_and_caches_when_no_cache_exists():
    engine = _FakeEngine([_fund("A", 10.0)])
    cache_repo = _FakeCacheRepo(cached=None)

    results = get_ranked_funds(engine=engine, cache_repo=cache_repo)

    assert len(results) == 1
    assert engine.analyze_all_calls == 1
    assert len(cache_repo.set_calls) == 1


def test_returns_cached_results_without_recomputing_when_fresh():
    cached_dump = [_fund("A", 10.0).model_dump()]
    cached = (cached_dump, datetime.now(timezone.utc) - timedelta(seconds=60))
    engine = _FakeEngine([])  # çağrılırsa boş döner, testte çağrılmadığı doğrulanır
    cache_repo = _FakeCacheRepo(cached=cached)

    results = get_ranked_funds(engine=engine, cache_repo=cache_repo)

    assert len(results) == 1
    assert results[0].fund_code == "A"
    assert engine.analyze_all_calls == 0


def test_recomputes_when_cache_is_stale():
    cached_dump = [_fund("OLD", 1.0).model_dump()]
    stale = (cached_dump, datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS + 60))
    engine = _FakeEngine([_fund("NEW", 99.0)])
    cache_repo = _FakeCacheRepo(cached=stale)

    results = get_ranked_funds(engine=engine, cache_repo=cache_repo)

    assert engine.analyze_all_calls == 1
    assert results[0].fund_code == "NEW"
    assert len(cache_repo.set_calls) == 1
