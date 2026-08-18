"""FCM bildirim gönderimi — AŞAMA 32, kapsam daraltması AŞAMA 45.

Bu projede bir zamanlayıcı (scheduler/cron) altyapısı yok; bildirimler gerçek
zamanlı/arka planda kendiliğinden gönderilmez. Bunun yerine, kullanıcı bir
kararı sorguladığında (GET /decisions/{symbol}) sonuç güçlü bir AL/SAT ise
ve bu, o kullanıcı için bu varlıkta daha önce bildirilmemiş yeni bir karar
ise bildirim gönderilir. Aynı kararın her sorguda tekrar tekrar
bildirilmemesi için NotificationLog ile basit bir "son bildirilen karar"
karşılaştırması yapılır.

AŞAMA 45 önemli değişiklik: çağıran taraf (app/api/decisions.py) artık bu
fonksiyonu YALNIZCA kullanıcının portföyünde o varlık varsa çağırıyor.
Sebep: Dashboard artık BIST100'ün tamamını sorguluyor (AŞAMA 43) — eskiden
"her sorgulanan varlık" bildirim tetikleyebiliyordu, bu da 100 hissenin
onlarcası için spam bildirime yol açardı. Bu fonksiyonun kendisi hâlâ
varlık-agnostik ve genel amaçlı — kapsam kararı çağıran tarafın
sorumluluğunda, test edilebilirliği bozmamak için.
"""

from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from app.models.ai_decision import AIDecision
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.repositories.notification_log_repository import NotificationLogRepository

STRONG_DECISIONS = {"BUY", "SELL"}
_DECISION_LABELS = {"BUY": "AL", "SELL": "SAT"}


def notify_if_strong_decision(
    user_id: str,
    decision: AIDecision,
    token_repo: FcmTokenRepository | None = None,
    log_repo: NotificationLogRepository | None = None,
    quantity_held: float | None = None,
) -> bool:
    """Koşullar sağlanıp bildirim gönderilirse True döner (testte doğrulamak için).

    `quantity_held` verilirse (çağıran taraf bu varlığın portföyde olduğunu
    zaten biliyorsa) bildirim metninde kaç adet elde olduğu da belirtilir —
    ek bir sorgu/hesaplama bu fonksiyon içinde YAPILMAZ, çağıran taraf sağlar.
    """
    if decision.decision not in STRONG_DECISIONS:
        return False

    log_repo = log_repo or NotificationLogRepository()
    if log_repo.get_last_decision(user_id, decision.asset) == decision.decision:
        return False  # Bu karar zaten bildirildi, tekrar gönderme

    token_repo = token_repo or FcmTokenRepository()
    token = token_repo.get(user_id)
    if not token:
        return False

    label = _DECISION_LABELS[decision.decision]
    body = f"Final skor: {decision.final_score:+.1f}, Güven: %{decision.confidence:.0f}"
    if quantity_held is not None:
        body = f"Elinizde {quantity_held:.0f} adet var. {body}"
    message = messaging.Message(
        notification=messaging.Notification(
            title=f"{decision.asset}: {label} sinyali",
            body=body,
        ),
        fid=token,
    )
    try:
        messaging.send(message)
    except firebase_exceptions.FirebaseError:
        return False

    log_repo.set_last_decision(user_id, decision.asset, decision.decision)
    return True
