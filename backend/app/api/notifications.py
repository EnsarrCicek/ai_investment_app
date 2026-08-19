from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.models.fcm_token import FcmToken
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.repositories.notification_record_repository import NotificationRecordRepository
from app.schemas.notifications import RegisterTokenRequest
from app.services.notifications.fcm_sender import send_test_notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/register-token")
def register_token(payload: RegisterTokenRequest, user_id: str = Depends(get_current_user_id)):
    token = FcmToken(user_id=user_id, token=payload.token, updated_at=datetime.now(timezone.utc))
    FcmTokenRepository().set(token)
    return {"registered": True}


@router.post("/test")
def send_test(user_id: str = Depends(get_current_user_id)):
    """AŞAMA 48/20: Ayarlar ekranındaki "Test Bildirimi Gönder" butonu —
    gerçek bir cihazda FCM'in uçtan uca çalışıp çalışmadığını doğrulamak için.
    """
    sent = send_test_notification(user_id)
    if not sent:
        raise HTTPException(
            status_code=400,
            detail="Bildirim gönderilemedi — cihaz kayıtlı değil ya da FCM hatası oluştu.",
        )
    return {"sent": True}


@router.get("/history")
def get_history(user_id: str = Depends(get_current_user_id)):
    return NotificationRecordRepository().list_for_user(user_id)
