from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.news_analysis import NewsAnalysis

COLLECTION = "news_analyses"


class NewsAnalysisRepository:
    """ai_decisions/technical_analyses ile aynı ilke: immutable — yalnızca
    add/list vardır, update/delete yoktur.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, analysis: NewsAnalysis) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(analysis.model_dump())
        return doc_ref.id

    def get_by_news_id(self, news_id: str) -> NewsAnalysis | None:
        docs = list(
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("news_id", "==", news_id))
            .limit(1)
            .stream()
        )
        if not docs:
            return None
        return NewsAnalysis(**docs[0].to_dict())

    def list_for_asset(self, asset: str, limit: int = 20) -> list[NewsAnalysis]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        records = [NewsAnalysis(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]
