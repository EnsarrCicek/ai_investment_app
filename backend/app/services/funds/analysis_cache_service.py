"""Hesaplanmış fon sıralamasını TTL'li önbellekten okur, bayatsa yeniden
hesaplar (benchmark_service.py ile aynı desen). Fon NAV'ları günde bir kez
güncellendiğinden TTL diğer 15 dk'lık önbelleklerden çok daha uzun (6 saat).
"""

from datetime import datetime, timezone

from app.engines.funds.analysis_engine import DEFAULT_KIND, FundAnalysisEngine
from app.models.fund_analysis import FundAnalysis
from app.repositories.fund_analysis_cache_repository import FundAnalysisCacheRepository

CACHE_TTL_SECONDS = 6 * 3600  # 6 saat


def get_ranked_funds(
    engine: FundAnalysisEngine | None = None,
    cache_repo: FundAnalysisCacheRepository | None = None,
    kind: str = DEFAULT_KIND,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> list[FundAnalysis]:
    cache_repo = cache_repo or FundAnalysisCacheRepository()
    cached = cache_repo.get(kind)
    if cached is not None:
        results, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < max_age_seconds:
            return [FundAnalysis(**r) for r in results]

    engine = engine or FundAnalysisEngine()
    results = engine.analyze_all(kind=kind)
    cache_repo.set(kind, [r.model_dump() for r in results], datetime.now(timezone.utc))
    return results
