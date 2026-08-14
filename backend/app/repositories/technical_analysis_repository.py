from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.technical_analysis import TechnicalAnalysis

COLLECTION = "technical_analyses"


class TechnicalAnalysisRepository:
    """Kural 5-6: geçmiş analizler değiştirilmez/silinmez; her çalıştırma yeni bir kayıt oluşturur."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, analysis: TechnicalAnalysis) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(analysis.model_dump())
        return doc_ref.id

    def get_latest(self, asset: str) -> TechnicalAnalysis | None:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        records = [TechnicalAnalysis(**doc.to_dict()) for doc in docs]
        if not records:
            return None
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[0]
