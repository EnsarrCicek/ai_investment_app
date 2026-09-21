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
        """HATA 15F: `received_at` sistemin bu makaleyi İLK gözlemlediği anı
        temsil eder ve bu yüzden IMMUTABLE olmalıdır (bölüm 12) -- ama
        `.set()` tüm dokümanı üzerine yazdığı için, aynı `external_id` daha
        sonra tekrar fetch edilip upsert edilince (provider'lar her cron
        çalışmasında `received_at = datetime.now(...)` üretiyor) bu alan
        SESSİZCE en son fetch zamanına ilerliyordu -- onaylanmış bir
        causality bug'ı. Kayıt zaten varsa, önce onun `received_at`'i
        okunup yeni değerin üzerine YAZILIR; diğer tüm alanlar (title/
        summary/source_reliability/published_at vb.) her zamanki gibi en
        son fetch'ten normal şekilde güncellenmeye devam eder."""
        existing = self.get_by_external_id(item.external_id)
        if existing is not None:
            item = item.model_copy(update={"received_at": existing.received_at})
        self._db.collection(COLLECTION).document(item.external_id).set(item.model_dump())

    def get_by_external_id(self, external_id: str) -> NewsRawItem | None:
        """HATA 15B: DecisionEngine'in skorlama-anı cross-source event dedup'ı
        için (bkz. event_dedup.py) bir NewsAnalysis'in kaynak ham haberine
        (başlık/yayın zamanı) geri dönebilmesi amacıyla eklendi."""
        doc = self._db.collection(COLLECTION).document(external_id).get()
        if not doc.exists:
            return None
        return NewsRawItem(**doc.to_dict())

    def get_recent(self, symbol: str, limit: int = 20) -> list[NewsRawItem]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("related_assets", "array_contains", symbol))
            .stream()
        )
        records = [NewsRawItem(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.published_at, reverse=True)
        return records[:limit]
