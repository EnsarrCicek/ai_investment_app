from pydantic import BaseModel


class RegisterTokenRequest(BaseModel):
    token: str
