"""Halka arz listesini/detayını TTL'li önbellekten okur, bayatsa yeniden
çeker (services/funds/analysis_cache_service.py ile aynı desen)."""

from datetime import datetime, timezone

from app.models.ipo import IpoDetail, IpoListing
from app.repositories.ipo_cache_repository import IpoCacheRepository
from app.services.ipo.halkarz_provider import HalkArzProvider

CACHE_TTL_SECONDS = 6 * 3600  # 6 saat — halka arz takvimi günde birkaç kez güncellenir


def slug_from_url(detail_url: str) -> str:
    return detail_url.rstrip("/").rsplit("/", 1)[-1]


def get_ipo_listings(
    provider: HalkArzProvider | None = None,
    cache_repo: IpoCacheRepository | None = None,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> list[IpoListing]:
    cache_repo = cache_repo or IpoCacheRepository()
    cached = cache_repo.get_listings()
    if cached is not None:
        results, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < max_age_seconds:
            return [IpoListing(**r) for r in results]

    provider = provider or HalkArzProvider()
    results = provider.get_listings()
    cache_repo.set_listings([r.model_dump() for r in results], datetime.now(timezone.utc))
    return results


def get_ipo_detail(
    detail_url: str,
    provider: HalkArzProvider | None = None,
    cache_repo: IpoCacheRepository | None = None,
    max_age_seconds: int = CACHE_TTL_SECONDS,
) -> IpoDetail | None:
    cache_repo = cache_repo or IpoCacheRepository()
    slug = slug_from_url(detail_url)
    cached = cache_repo.get_detail(slug)
    if cached is not None:
        result, fetched_at = cached
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < max_age_seconds:
            return IpoDetail(**result)

    provider = provider or HalkArzProvider()
    detail = provider.get_detail(detail_url)
    if detail is None:
        return None
    cache_repo.set_detail(slug, detail.model_dump(), datetime.now(timezone.utc))
    return detail
