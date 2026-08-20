from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.fund_position import FundPosition

COLLECTION = "fund_positions"


class FundPositionRepository:
    def __init__(self):
        self._db = get_firestore_client()

    def add(self, position: FundPosition) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(position.model_dump())
        return doc_ref.id

    def list_for_user(self, user_id: str) -> list[FundPosition]:
        docs = self._db.collection(COLLECTION).where(filter=FieldFilter("user_id", "==", user_id)).stream()
        return [FundPosition(**doc.to_dict()) for doc in docs]

    def delete_for_fund(self, user_id: str, fund_code: str) -> None:
        docs = (
            self._db.collection(COLLECTION)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .where(filter=FieldFilter("fund_code", "==", fund_code))
            .stream()
        )
        for doc in docs:
            doc.reference.delete()
