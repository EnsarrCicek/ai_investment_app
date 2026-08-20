from app.core.firebase import get_firestore_client

COLLECTION = "fund_notification_log"


class FundNotificationLogRepository:
    """notification_log_repository.py ile aynı prensip (scheduler olmadığı
    için tekrar bildirimi önleyen dedup) — fon tarafına özgü iki ayrı durum:

    1) Aylık öneri: bu ay zaten bildirildi mi (year_month, ör. "2026-08").
    2) Fon değiştirme önerisi: bu tutulan fon için AYNI öneri bugün zaten
       gönderildi mi (öneri değişirse ya da gün değişirse tekrar gönderilir).
    """

    def __init__(self):
        self._db = get_firestore_client()

    def get_last_monthly_notified(self, user_id: str) -> str | None:
        doc = self._db.collection(COLLECTION).document(f"{user_id}_monthly").get()
        if not doc.exists:
            return None
        return doc.to_dict().get("year_month")

    def set_last_monthly_notified(self, user_id: str, year_month: str) -> None:
        self._db.collection(COLLECTION).document(f"{user_id}_monthly").set(
            {"user_id": user_id, "year_month": year_month}
        )

    def get_last_switch_suggestion(self, user_id: str, held_fund_code: str) -> dict | None:
        doc = self._db.collection(COLLECTION).document(f"{user_id}_switch_{held_fund_code}").get()
        if not doc.exists:
            return None
        return doc.to_dict()

    def set_last_switch_suggestion(self, user_id: str, held_fund_code: str, suggested_code: str, date: str) -> None:
        self._db.collection(COLLECTION).document(f"{user_id}_switch_{held_fund_code}").set(
            {
                "user_id": user_id,
                "held_fund_code": held_fund_code,
                "suggested_code": suggested_code,
                "date": date,
            }
        )
