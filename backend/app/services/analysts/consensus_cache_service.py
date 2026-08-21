"""Sembol başına analist konsensüsünü TTL'li önbellekten okur, bayatsa
yeniden hesaplar (services/funds/analysis_cache_service.py ile aynı desen).
Analist tavsiyeleri/hedef fiyatları günde birkaç kez değişebilir ama saatlik
takip gerektirmez; TTL fon analizindeki (6 saat) ile aynı büyüklükte.
"""

from datetime import datetime, timezone

from app.engines.analysts.consensus import build_consensus
from app.models.analyst_consensus import AnalystConsensus
from app.repositories.analyst_consensus_cache_repository import AnalystConsensusCacheRepository
from app.services.analysts.yahoo_analyst_provider import YahooAnalystProvider

CACHE_TTL_SECONDS = 6 * 3600  # 6 saat


def get_analyst_consensus(
    symbol: str,
    provider: YahooAnalystProvider | None = None,
    cache_repo: AnalystConsensusCacheRepository | None = None,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> AnalystConsensus:
    cache_repo = cache_repo or AnalystConsensusCacheRepository()
    cached = cache_repo.get(symbol)
    if cached is not None:
        result, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < max_age_seconds:
            return AnalystConsensus(**result)

    provider = provider or YahooAnalystProvider()
    now = datetime.now(timezone.utc)
    raw = provider.get_raw(symbol)
    consensus = build_consensus(symbol, raw, now)
    cache_repo.set(symbol, consensus.model_dump(), now)
    return consensus
