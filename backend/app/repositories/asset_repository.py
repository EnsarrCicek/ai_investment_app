from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.asset import Asset

COLLECTION = "assets"


class AssetRepository:
    def __init__(self):
        self._db = get_firestore_client()

    def upsert(self, asset: Asset) -> None:
        self._db.collection(COLLECTION).document(asset.symbol).set(asset.model_dump())

    def get_by_symbol(self, symbol: str) -> Asset | None:
        doc = self._db.collection(COLLECTION).document(symbol).get()
        if not doc.exists:
            return None
        return Asset(**doc.to_dict())

    def list_active(self) -> list[Asset]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("active", "==", True))
            .stream()
        )
        return [Asset(**doc.to_dict()) for doc in docs]
