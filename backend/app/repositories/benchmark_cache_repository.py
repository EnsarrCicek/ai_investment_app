from datetime import datetime

from app.core.firebase import get_firestore_client

COLLECTION = "system_cache"
DOCUMENT_ID = "benchmark_xu100_close_series"


class BenchmarkCacheRepository:
    """XU100 (BIST100 endeksi) günlük kapanış serisi için tek belgelik önbellek
    (bkz. services/market_data/benchmark_service.py). Bir koleksiyon değil tek
    bir belge kullanılır — technical_analyses'in aksine, burada saklanan sembol
    bazlı bir geçmiş değil, tüm semboller için ORTAK tek bir seridir.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def get(self) -> tuple[dict[str, float], datetime] | None:
        doc = self._db.collection(COLLECTION).document(DOCUMENT_ID).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data["close_by_date"], data["fetched_at"]

    def set(self, close_by_date: dict[str, float], fetched_at: datetime) -> None:
        self._db.collection(COLLECTION).document(DOCUMENT_ID).set(
            {"close_by_date": close_by_date, "fetched_at": fetched_at}
        )
