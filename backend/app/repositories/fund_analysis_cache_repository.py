from datetime import datetime

from app.core.firebase import get_firestore_client

COLLECTION = "system_cache"
DOCUMENT_ID_PREFIX = "fund_analysis_"


class FundAnalysisCacheRepository:
    """Hesaplanmış (sıralanmış) fon analiz sonucu için tek belgelik önbellek —
    benchmark_cache_repository.py ile aynı prensip. FundSnapshotRepository'nin
    (ham TEFAS anlık görüntüleri, KALICI) AKSİNE bu, TÜREV/hesaplanmış sonucu
    kısa süreli (TTL'li) önbellekler — fon NAV'ları günde bir kez güncellenir,
    her istek için ~2000 fonu yeniden sıralamak yerine.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def get(self, kind: str) -> tuple[list[dict], datetime] | None:
        doc = self._db.collection(COLLECTION).document(f"{DOCUMENT_ID_PREFIX}{kind}").get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data["results"], data["fetched_at"]

    def set(self, kind: str, results: list[dict], fetched_at: datetime) -> None:
        self._db.collection(COLLECTION).document(f"{DOCUMENT_ID_PREFIX}{kind}").set(
            {"results": results, "fetched_at": fetched_at}
        )
