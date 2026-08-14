import firebase_admin
from firebase_admin import credentials, firestore

from app.core.config import FIREBASE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS

_app = None


def get_firestore_client():
    global _app
    if _app is None:
        if GOOGLE_APPLICATION_CREDENTIALS:
            cred = credentials.Certificate(GOOGLE_APPLICATION_CREDENTIALS)
        else:
            cred = credentials.ApplicationDefault()
        _app = firebase_admin.initialize_app(
            cred, {"projectId": FIREBASE_PROJECT_ID}
        )
    return firestore.client()
