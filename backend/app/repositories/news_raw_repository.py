from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.news_raw import NewsRawItem

COLLECTION = "news_raw"


class NewsRawRepository:
    """Not: Burada yalnızca aynı external_id'ye sahip haberin Firestore'da tekrar
    tekrar yeni doküman olarak birikmesini önleyen TEKNİK bir dedup vardır
    (doküman ID = external_id). Farklı kaynaklarda yayınlanan AYNI OLAYIN
    tekilleştirilmesi (semantik duplicate detection, ana doküman bölüm 9) bu
    aşamada YOK — EventIntelligenceEngine (AŞAMA 16+) ile ele alınacak.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def upsert(self, item: NewsRawItem) -> None:
        self._db.collection(COLLECTION).document(item.external_id).set(item.model_dump())

    def get_recent(self, symbol: str, limit: int = 20) -> list[NewsRawItem]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("related_assets", "array_contains", symbol))
            .stream()
        )
        records = [NewsRawItem(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.published_at, reverse=True)
        return records[:limit]
