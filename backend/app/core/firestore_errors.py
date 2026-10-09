"""Firestore kota hatasının (RESOURCE_EXHAUSTED) merkezi HTTP karşılığı.

Kota dolduğunda istek 500 (iç hata) gibi görünmemeli: geçici bir hizmet kesintisidir → 503 + açık kod. Bu işleyici
hiçbir yedek veri ÜRETMEZ; yalnız yerel LAN modunda varlık listesi ve dashboard kendi açık işaretli yollarını
kullanır (bkz. app/services/assets/asset_catalog.py, app/services/decisions/dashboard.py).
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from google.api_core.exceptions import ResourceExhausted

FIRESTORE_QUOTA_EXHAUSTED = "FIRESTORE_QUOTA_EXHAUSTED"
RETRY_AFTER_SECONDS = 300


async def resource_exhausted_handler(_request: Request, _exc: ResourceExhausted) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        content={"detail": {"code": FIRESTORE_QUOTA_EXHAUSTED,
                            "message": "Veri tabanı kotası geçici olarak doldu; daha sonra tekrar deneyin."}},
    )


def register(app) -> None:
    app.add_exception_handler(ResourceExhausted, resource_exhausted_handler)
