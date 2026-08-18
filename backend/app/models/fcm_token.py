from datetime import datetime

from pydantic import BaseModel


class FcmToken(BaseModel):
    user_id: str
    token: str
    updated_at: datetime
