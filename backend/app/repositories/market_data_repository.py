from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.market_data import MarketData

COLLECTION = "market_data"


class MarketDataRepository:
    """Ana doküman kural 6: yeni veri geldiğinde eski kayıt güncellenmez, yeni kayıt eklenir."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, data: MarketData) -> None:
        self._db.collection(COLLECTION).add(data.model_dump())

    def list_for_asset(self, asset_id: str, limit: int = 50) -> list[MarketData]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("asset_id", "==", asset_id))
            .stream()
        )
        records = [MarketData(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[:limit]
