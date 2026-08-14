from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.portfolio_position import PortfolioPosition

COLLECTION = "portfolio_positions"


class PortfolioRepository:
    """Not: ai_decisions/technical_analyses'in aksine bu kullanıcı verisidir (bölüm 37) —
    immutable DEĞİLDİR; kullanıcı kendi pozisyonunu düzenleyebilir/silebilir.

    GÜVENLİK NOTU: Auth/Login ekranı henüz yazılmadı (bkz. KURULUM_GUNLUGU AŞAMA 4).
    Bu yüzden user_id şu an istemciden düz parametre olarak alınıyor — bu geçici bir
    MVP kısayoludur. Production öncesi mutlaka Firebase Auth token'ından doğrulanmalı
    ve Firestore Security Rules ile "kullanıcı yalnız kendi verisini okur/yazar"
    kuralı (ana doküman bölüm 34) uygulanmalıdır.
    """

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, position: PortfolioPosition) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(position.model_dump())
        return doc_ref.id

    def list_for_user(self, user_id: str) -> list[tuple[str, PortfolioPosition]]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .stream()
        )
        return [(doc.id, PortfolioPosition(**doc.to_dict())) for doc in docs]

    def delete(self, position_id: str) -> None:
        self._db.collection(COLLECTION).document(position_id).delete()
