from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_id
from app.models.fcm_token import FcmToken
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.schemas.notifications import RegisterTokenRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/register-token")
def register_token(payload: RegisterTokenRequest, user_id: str = Depends(get_current_user_id)):
    token = FcmToken(user_id=user_id, token=payload.token, updated_at=datetime.now(timezone.utc))
    FcmTokenRepository().set(token)
    return {"registered": True}
