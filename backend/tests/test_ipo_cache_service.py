from datetime import datetime, timedelta, timezone

from app.models.ipo import IpoDetail, IpoListing
from app.services.ipo.cache_service import CACHE_TTL_SECONDS, get_ipo_detail, get_ipo_listings, slug_from_url


def _listing(name="ABC A.Ş."):
    return IpoListing(company_name=name, bist_code=None, detail_url="https://halkarz.com/abc-a-s/", date_text="")


def _detail(name="ABC A.Ş."):
    return IpoDetail(company_name=name, fields={"Fiyat": "10 TL"}, fetched_at=datetime.now(timezone.utc))


class _FakeListingsCacheRepo:
    def __init__(self, cached=None):
        self._listings_cached = cached
        self._detail_cached: dict[str, tuple] = {}
        self.set_listings_calls = 0
        self.set_detail_calls = 0

    def get_listings(self):
        return self._listings_cached

    def set_listings(self, results, fetched_at):
        self.set_listings_calls += 1
        self._listings_cached = (results, fetched_at)

    def get_detail(self, slug):
        return self._detail_cached.get(slug)

    def set_detail(self, slug, result, fetched_at):
        self.set_detail_calls += 1
        self._detail_cached[slug] = (result, fetched_at)


class _FakeProvider:
    def __init__(self, listings=None, detail=None):
        self._listings = listings or []
        self._detail = detail
        self.get_listings_calls = 0
        self.get_detail_calls = 0

    def get_listings(self):
        self.get_listings_calls += 1
        return self._listings

    def get_detail(self, url):
        self.get_detail_calls += 1
        return self._detail


def test_slug_from_url_strips_trailing_slash():
    assert slug_from_url("https://halkarz.com/abc-a-s/") == "abc-a-s"
    assert slug_from_url("https://halkarz.com/abc-a-s") == "abc-a-s"


def test_get_ipo_listings_fetches_and_caches_when_empty():
    provider = _FakeProvider(listings=[_listing()])
    cache_repo = _FakeListingsCacheRepo(cached=None)

    results = get_ipo_listings(provider=provider, cache_repo=cache_repo)

    assert len(results) == 1
    assert provider.get_listings_calls == 1
    assert cache_repo.set_listings_calls == 1


def test_get_ipo_listings_returns_cached_when_fresh():
    cached = ([_listing("CACHED").model_dump()], datetime.now(timezone.utc) - timedelta(seconds=60))
    provider = _FakeProvider(listings=[])
    cache_repo = _FakeListingsCacheRepo(cached=cached)

    results = get_ipo_listings(provider=provider, cache_repo=cache_repo)

    assert results[0].company_name == "CACHED"
    assert provider.get_listings_calls == 0


def test_get_ipo_listings_refetches_when_stale():
    stale = ([_listing("OLD").model_dump()], datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS + 60))
    provider = _FakeProvider(listings=[_listing("NEW")])
    cache_repo = _FakeListingsCacheRepo(cached=stale)

    results = get_ipo_listings(provider=provider, cache_repo=cache_repo)

    assert results[0].company_name == "NEW"
    assert provider.get_listings_calls == 1


def test_get_ipo_detail_fetches_and_caches_when_empty():
    provider = _FakeProvider(detail=_detail())
    cache_repo = _FakeListingsCacheRepo()

    result = get_ipo_detail("https://halkarz.com/abc-a-s/", provider=provider, cache_repo=cache_repo)

    assert result.company_name == "ABC A.Ş."
    assert provider.get_detail_calls == 1
    assert cache_repo.set_detail_calls == 1


def test_get_ipo_detail_returns_none_when_provider_returns_none():
    provider = _FakeProvider(detail=None)
    cache_repo = _FakeListingsCacheRepo()

    result = get_ipo_detail("https://halkarz.com/missing/", provider=provider, cache_repo=cache_repo)

    assert result is None
    assert cache_repo.set_detail_calls == 0
