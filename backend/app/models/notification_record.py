from datetime import datetime

from pydantic import BaseModel


class NotificationRecord(BaseModel):
    """Kullanıcıya GÖNDERİLMİŞ bir bildirimin değiştirilemez kaydı (AŞAMA
    48/20) — Ayarlar > Bildirimler ekranında "AL/SAT bildirimi geldi mi"
    sorusuna cevap vermek için. `notification_log` (yalnızca dedup amaçlı
    "son bildirilen karar") ile KARIŞTIRILMAMALI; bu gerçek bir gönderim
    geçmişidir (ana doküman kural 6: geçmiş asla değiştirilmez/silinmez).
    """

    user_id: str
    asset: str | None = None  # test bildirimlerinde None
    kind: str  # "TEST" / "BUY" / "SELL"
    title: str
    body: str
    created_at: datetime
