from datetime import datetime

from app.core.firebase import get_firestore_client

COLLECTION = "system_cache"
LISTINGS_DOC_ID = "ipo_listings"
DETAIL_DOC_ID_PREFIX = "ipo_detail_"


class IpoCacheRepository:
    """Halka arz listesi/detayı için TTL'li önbellek — fund_analysis_cache_repository.py
    ile aynı prensip (system_cache koleksiyonu). halkarz.com'a her istekte
    scrape yapmamak için."""

    def __init__(self):
        self._db = get_firestore_client()

    def get_listings(self) -> tuple[list[dict], datetime] | None:
        doc = self._db.collection(COLLECTION).document(LISTINGS_DOC_ID).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data["results"], data["fetched_at"]

    def set_listings(self, results: list[dict], fetched_at: datetime) -> None:
        self._db.collection(COLLECTION).document(LISTINGS_DOC_ID).set(
            {"results": results, "fetched_at": fetched_at}
        )

    def get_detail(self, slug: str) -> tuple[dict, datetime] | None:
        doc = self._db.collection(COLLECTION).document(f"{DETAIL_DOC_ID_PREFIX}{slug}").get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data["result"], data["fetched_at"]

    def set_detail(self, slug: str, result: dict, fetched_at: datetime) -> None:
        self._db.collection(COLLECTION).document(f"{DETAIL_DOC_ID_PREFIX}{slug}").set(
            {"result": result, "fetched_at": fetched_at}
        )
