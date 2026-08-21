from datetime import datetime

from app.core.firebase import get_firestore_client

COLLECTION = "system_cache"
DOCUMENT_ID_PREFIX = "analyst_consensus_"


class AnalystConsensusCacheRepository:
    """Sembol başına hesaplanmış analist konsensüsü için TTL'li önbellek —
    fund_analysis_cache_repository.py ile aynı prensip (system_cache koleksiyonu,
    her sembol için ayrı belge)."""

    def __init__(self):
        self._db = get_firestore_client()

    def get(self, symbol: str) -> tuple[dict, datetime] | None:
        doc = self._db.collection(COLLECTION).document(f"{DOCUMENT_ID_PREFIX}{symbol}").get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data["result"], data["fetched_at"]

    def set(self, symbol: str, result: dict, fetched_at: datetime) -> None:
        self._db.collection(COLLECTION).document(f"{DOCUMENT_ID_PREFIX}{symbol}").set(
            {"result": result, "fetched_at": fetched_at}
        )
