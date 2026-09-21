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

    def get_by_news_id(self, news_id: str, asset: str) -> NewsAnalysis | None:
        """`asset` de filtreye dahildir: Foreks gibi TEK bir haberin BİRDEN ÇOK
        BIST varlığına değindiği kaynaklar eklenince, aynı news_id'nin farklı
        varlıklar için AYRI (farklı sentiment/reasoning) analizleri olabilir —
        yalnızca news_id'ye bakmak, başka bir varlık için üretilmiş analizi
        yanlışlıkla "bu varlık için zaten analiz edildi" sanabilirdi.
        """
        docs = list(
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("news_id", "==", news_id))
            .where(filter=FieldFilter("asset", "==", asset))
            .limit(1)
            .stream()
        )
        if not docs:
            return None
        return NewsAnalysis(**docs[0].to_dict())

    def list_for_asset(self, asset: str, limit: int | None = 20) -> list[NewsAnalysis]:
        """HATA 15B FINAL: `limit=None` -- bu asset için TÜM (Firestore
        sorgusu zaten baştan `where(asset==...)` dışında bir cap İÇERMİYORDU;
        eski kod yalnızca Python tarafında `records[:limit]` ile kesiyordu)
        kayıtları created_at azalan sıralı döner (bu yalnızca dedup'a giden
        HAM girdi sırasıdır -- HATA 15F: nihai "son N benzersiz olay"
        penceresinin sıralaması `app.services.news.news_selection`'da
        temsilcinin `published_at`'ine göre YENİDEN hesaplanır, bkz. o modül).
        `DecisionEngine.decide_for_asset()` artık limiti dedup'tan ÖNCE değil SONRA uyguluyor
        -- aksi halde en yeni `limit` ham slot'u aynı olayın tekrarları
        işgal ettiğinde, o olaydan eskiye giden BAĞIMSIZ olaylar hiç
        okunmadan pencereden dışarı kalıyordu (bkz. `decision/engine.py`
        `decide_for_asset` docstring'i, HATA 15B FINAL bölüm 1-2)."""
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        records = [NewsAnalysis(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.created_at, reverse=True)
        if limit is None:
            return records
        return records[:limit]
