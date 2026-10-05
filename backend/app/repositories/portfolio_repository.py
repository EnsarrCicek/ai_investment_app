from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.portfolio_position import PortfolioPosition, merged_currency

COLLECTION = "portfolio_positions"


class PortfolioRepository:
    """Not: ai_decisions/technical_analiz'in aksine bu kullanıcı verisidir (bölüm 37) —
    immutable DEĞİLDİR; kullanıcı kendi pozisyonunu düzenleyebilir/silebilir.

    Güvenlik: user_id artık backend'de Firebase ID token'ından doğrulanıyor
    (bkz. app/core/auth.py, AŞAMA 4/34) — bu repository'ye her zaman zaten
    doğrulanmış bir user_id gelir.
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

    def get_position_for_asset(self, user_id: str, asset: str) -> PortfolioPosition | None:
        """Bu varlığa ait tüm lotları (varsa) tek bir birleşik pozisyona
        indirger — AŞAMA 45'te bildirim gate'i için: "bu kullanıcı bu
        hisseyi elinde tutuyor mu" sorusuna cevap verir. Hiç lot yoksa None.
        """
        docs = list(
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        if not docs:
            return None
        lots = [PortfolioPosition(**doc.to_dict()) for doc in docs]
        quantity = sum(lot.quantity for lot in lots)
        avg_buy_price = round(sum(lot.quantity * lot.buy_price for lot in lots) / quantity, 2)
        return PortfolioPosition(
            user_id=user_id,
            asset=asset,
            buy_price=avg_buy_price,
            buy_date=min(lot.buy_date for lot in lots),
            quantity=quantity,
            created_at=max(lot.created_at for lot in lots),
            currency=merged_currency(lots),
        )

    def delete_for_asset(self, user_id: str, asset: str) -> None:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .where(filter=FieldFilter("asset", "==", asset))
            .stream()
        )
        for doc in docs:
            doc.reference.delete()

    def replace_for_asset(self, user_id: str, asset: str, position: PortfolioPosition) -> str:
        """O varlığa ait tüm lotları tek bir yeni lotla değiştirir (AŞAMA 30-31
        Devam — Pozisyon Düzenleme). Görünüm zaten lotları birleştirdiği için
        (ortalama maliyet) düzenleme de "bu pozisyonu şu yeni değerlerle
        değiştir" olarak tanımlanıyor; münferit lot geçmişi bilinçli olarak
        feda ediliyor.
        """
        self.delete_for_asset(user_id, asset)
        return self.add(position)
