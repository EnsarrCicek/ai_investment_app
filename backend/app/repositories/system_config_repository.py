from app.core.firebase import get_firestore_client

COLLECTION = "system_config"


class SystemConfigRepository:
    """Ana doküman kural 13: skor ağırlıkları hard-code edilmez, Firestore system_config üzerinden yönetilir."""

    def __init__(self):
        self._db = get_firestore_client()

    def get(self, config_id: str, defaults: dict) -> dict:
        ref = self._db.collection(COLLECTION).document(config_id)
        doc = ref.get()
        if not doc.exists:
            ref.set(defaults)
            return defaults
        return {**defaults, **doc.to_dict()}
