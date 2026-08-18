from app.core.firebase import get_firestore_client
from app.models.fcm_token import FcmToken

COLLECTION = "fcm_tokens"


class FcmTokenRepository:
    """Kullanıcı başına tek bir FCM cihaz token'ı saklar (doküman ID = user_id).
    Yeni bir kayıt eskisinin üzerine yazar — bu MVP'de kullanıcı tek cihazdan
    giriş yaptığı varsayılıyor.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def set(self, token: FcmToken) -> None:
        self._db.collection(COLLECTION).document(token.user_id).set(token.model_dump())

    def get(self, user_id: str) -> str | None:
        doc = self._db.collection(COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("token")
