from google.cloud.firestore_v1.base_query import BaseQuery

from app.core.firebase import get_firestore_client
from app.models.macro_snapshot import MacroSnapshot

COLLECTION = "macro_snapshots"


class MacroSnapshotRepository:
    """Kural 6: her çalıştırma yeni bir snapshot ekler, eskisi güncellenmez."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, snapshot: MacroSnapshot) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(snapshot.model_dump())
        return doc_ref.id

    def get_latest(self) -> MacroSnapshot | None:
        snapshot, _doc_id = self.get_latest_with_id()
        return snapshot

    def get_latest_with_id(self) -> tuple[MacroSnapshot | None, str | None]:
        docs = list(
            self._db.collection(COLLECTION)
            .order_by("created_at", direction=BaseQuery.DESCENDING)
            .limit(1)
            .stream()
        )
        if not docs:
            return None, None
        return MacroSnapshot(**docs[0].to_dict()), docs[0].id

    def get_by_id(self, snapshot_id: str) -> MacroSnapshot | None:
        """HATA 18C: `ExplanationEngine`'in decision-bound (historical) modu
        için -- persisted `AIDecision.macro_snapshot_id` referansını geri
        çağırır (`get_latest_with_id()`'in aksine, herhangi bir eski
        snapshot'ı, bugünkü tazelik durumundan BAĞIMSIZ getirir). Salt-okunur
        ek."""
        doc = self._db.collection(COLLECTION).document(snapshot_id).get()
        if not doc.exists:
            return None
        return MacroSnapshot(**doc.to_dict())
