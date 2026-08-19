from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.portfolio_transaction import PortfolioTransaction

COLLECTION = "portfolio_transactions"


class PortfolioTransactionRepository:
    """Kural 5-6 ile aynı ilke: geçmiş işlemler değiştirilmez/silinmez."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, transaction: PortfolioTransaction) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(transaction.model_dump())
        return doc_ref.id

    def list_for_user(self, user_id: str) -> list[PortfolioTransaction]:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .stream()
        )
        records = [PortfolioTransaction(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.sell_date, reverse=True)
        return records
