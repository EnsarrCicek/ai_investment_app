from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import get_firestore_client
from app.models.ipo import IpoNote

COLLECTION = "ipo_notes"


class IpoNoteRepository:
    """Kullanıcının halka arzlarla ilgili kendi gözlem notları — AŞAMA 67:
    kullanıcı isteği 'bu kadar alış bu kadar satış var, satmalısın gibi
    verileri girersem tutmasını istiyorum.' Notlar KALICI ve değiştirilemez
    (yalnızca eklenir/silinir, düzenlenmez) — bir günlük/journal gibi."""

    def __init__(self):
        self._db = get_firestore_client()

    def add(self, note: IpoNote) -> str:
        _, doc_ref = self._db.collection(COLLECTION).add(note.model_dump(exclude={"id"}))
        return doc_ref.id

    def list_for_user(self, user_id: str, company_name: str | None = None) -> list[IpoNote]:
        query = self._db.collection(COLLECTION).where(filter=FieldFilter("user_id", "==", user_id))
        if company_name:
            query = query.where(filter=FieldFilter("company_name", "==", company_name))
        docs = list(query.stream())
        notes = [IpoNote(id=doc.id, **doc.to_dict()) for doc in docs]
        notes.sort(key=lambda n: n.created_at, reverse=True)
        return notes

    def delete(self, user_id: str, note_id: str) -> bool:
        doc_ref = self._db.collection(COLLECTION).document(note_id)
        doc = doc_ref.get()
        if not doc.exists or doc.to_dict().get("user_id") != user_id:
            return False
        doc_ref.delete()
        return True
