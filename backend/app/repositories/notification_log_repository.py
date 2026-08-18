from app.core.firebase import get_firestore_client

COLLECTION = "notification_log"


class NotificationLogRepository:
    """Bir kullanıcıya bir varlık için en son hangi kararın bildirildiğini tutar —
    scheduler olmadığı için aynı kararın her karar sorgusunda (Dashboard her
    açıldığında) tekrar tekrar bildirilmesini önlemek amacıyla.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def _doc_id(self, user_id: str, asset: str) -> str:
        return f"{user_id}_{asset}"

    def get_last_decision(self, user_id: str, asset: str) -> str | None:
        doc = self._db.collection(COLLECTION).document(self._doc_id(user_id, asset)).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("decision")

    def set_last_decision(self, user_id: str, asset: str, decision: str) -> None:
        self._db.collection(COLLECTION).document(self._doc_id(user_id, asset)).set(
            {"user_id": user_id, "asset": asset, "decision": decision}
        )
