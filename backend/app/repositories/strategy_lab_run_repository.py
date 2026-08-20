from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.strategy_lab_run import StrategyLabRun

COLLECTION = "strategy_lab_runs"


class StrategyLabRunRepository:
    def __init__(self):
        self._db = get_firestore_client()

    def add(self, run: StrategyLabRun) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(run.model_dump())
        return doc_ref.id

    def list_for_user(self, user_id: str, limit: int = 30) -> list[StrategyLabRun]:
        docs = self._db.collection(COLLECTION).where(filter=FieldFilter("user_id", "==", user_id)).stream()
        records = [StrategyLabRun(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]
