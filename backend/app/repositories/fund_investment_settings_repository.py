from app.core.firebase import get_firestore_client
from app.models.fund_investment_settings import FundInvestmentSettings

COLLECTION = "fund_investment_settings"


class FundInvestmentSettingsRepository:
    """Kullanıcı başına tek kayıt (doküman ID = user_id) — fcm_token_repository.py
    ile aynı desen."""

    def __init__(self):
        self._db = get_firestore_client()

    def set(self, settings: FundInvestmentSettings) -> None:
        self._db.collection(COLLECTION).document(settings.user_id).set(settings.model_dump())

    def get(self, user_id: str) -> FundInvestmentSettings | None:
        doc = self._db.collection(COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        return FundInvestmentSettings(**doc.to_dict())
