from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.ai_decision import AIDecision

COLLECTION = "ai_decisions"


class AIDecisionRepository:
    """Kural 5 ve bölüm 33 (Immutable Decision): kasıtlı olarak update/delete metodu YOKTUR.

    Fiyat sonradan değişse bile geçmiş bir karar kaydı asla güncellenmez; yeni
    değerlendirme her zaman yeni bir doküman olarak eklenir.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, decision: AIDecision) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(decision.model_dump())
        return doc_ref.id

    def get_latest(self, asset: str) -> AIDecision | None:
        records = self.list_for_asset(asset, limit=1)
        return records[0] if records else None

    def get_by_id(self, decision_id: str) -> AIDecision | None:
        """HATA 18C: belirli bir persisted kararı kimliğiyle geri çağırır --
        `ExplanationEngine`'in decision-bound (historical) modu için.
        Salt-okunur bir ek: append-only sözleşmeyi (Kural 5) ihlal ETMEZ."""
        doc = self._db.collection(COLLECTION).document(decision_id).get()
        if not doc.exists:
            return None
        return AIDecision(**doc.to_dict())

    def list_for_asset(self, asset: str, limit: int = 20) -> list[AIDecision]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        records = [AIDecision(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]
