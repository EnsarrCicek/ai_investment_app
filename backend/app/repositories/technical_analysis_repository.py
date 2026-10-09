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
        analysis, _doc_id = self.get_latest_with_id(asset)
        return analysis

    def get_latest_with_id(self, asset: str) -> tuple[TechnicalAnalysis | None, str | None]:
        # Not: where(asset==X) + order_by(created_at) Firestore'da composite
        # index gerektirir (yeni bir altyapı değişikliği olurdu). Bunun yerine
        # news_analysis_repository ile aynı desen: tek alanlı filtre + Python'da
        # sıralama — index gerektirmez.
        docs = list(
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        if not docs:
            return None, None
        records = [(doc.id, TechnicalAnalysis(**doc.to_dict())) for doc in docs]
        records.sort(key=lambda pair: pair[1].created_at, reverse=True)
        latest_id, latest = records[0]
        return latest, latest_id

    def list_created_since(self, cutoff) -> list[tuple[str, TechnicalAnalysis]]:
        """Toplu dashboard için: `created_at >= cutoff` olan TÜM varlıkların analizleri, tek sorguda. Tek alanlı aralık
        filtresi otomatik indeksle çalışır (composite index gerekmez). `get_latest_with_id` her çağrıda o varlığın TÜM
        geçmişini okur; cache tazelik penceresinden eski kayıt zaten cache hit olamayacağı için pencereli okuma
        sonucu değiştirmez (bkz. app/services/decisions/dashboard.py)."""
        docs = self._db.collection(COLLECTION).where(filter=FieldFilter("created_at", ">=", cutoff)).stream()
        return [(doc.id, TechnicalAnalysis(**doc.to_dict())) for doc in docs]

    def get_by_id(self, analysis_id: str) -> TechnicalAnalysis | None:
        """HATA 18C: `ExplanationEngine`'in decision-bound (historical) modu
        için -- persisted `AIDecision.technical_analysis_id` referansını
        geri çağırır. Salt-okunur ek."""
        doc = self._db.collection(COLLECTION).document(analysis_id).get()
        if not doc.exists:
            return None
        return TechnicalAnalysis(**doc.to_dict())
