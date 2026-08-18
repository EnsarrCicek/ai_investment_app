from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions

from app.core.firebase import get_firestore_client


def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
    """Firebase ID token'ı doğrulayıp gerçek kullanıcı UID'sini döner.

    Client'ın gönderdiği herhangi bir user_id'ye güvenilmez (AŞAMA 4/34) —
    kullanıcı kimliği yalnızca doğrulanmış token'dan çıkarılır.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yetkilendirme başlığı eksik veya geçersiz")

    token = authorization.removeprefix("Bearer ").strip()
    get_firestore_client()  # Firebase Admin app'in başlatıldığından emin olur
    try:
        decoded = firebase_auth.verify_id_token(token)
    except firebase_exceptions.FirebaseError as exc:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş oturum") from exc

    return decoded["uid"]


def get_current_user_id_optional(authorization: str | None = Header(default=None)) -> str | None:
    """get_current_user_id ile aynı, ama token yoksa/geçersizse 401 fırlatmak yerine
    None döner. Herkese açık uç noktalarda (ör. GET /decisions/{symbol}) "eğer bir
    kullanıcı oturum açmışsa ek bir şey yap" davranışı için — çağrının kendisi auth
    zorunlu tutmaz.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    get_firestore_client()
    try:
        decoded = firebase_auth.verify_id_token(token)
    except firebase_exceptions.FirebaseError:
        return None

    return decoded["uid"]
