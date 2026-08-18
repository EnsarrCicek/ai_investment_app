from app.core.firebase import get_firestore_client
from app.models.token_usage import TokenUsageLog

COLLECTION = "token_usage_logs"


class TokenUsageRepository:
    """news_analyses ile aynı ilke: immutable — yalnızca add/list vardır."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, log: TokenUsageLog) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(log.model_dump())
        return doc_ref.id

    def list_all(self) -> list[TokenUsageLog]:
        docs = self._db.collection(COLLECTION).stream()
        return [TokenUsageLog(**doc.to_dict()) for doc in docs]
