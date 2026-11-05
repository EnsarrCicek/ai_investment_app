"""Matriks ortam değişkeni yapılandırması (gizli değer kaynak koduna/loga YAZILMAZ).

Değişkenler (hiçbiri zorunlu değil; ASCII ad önerilir, `MATRİKS_` yazımı da okunur):
    MATRIKS_TRANSPORT   REST | MQTT | SOCKET | XML
    MATRIKS_BASE_URL
    MATRIKS_USERNAME
    MATRIKS_PASSWORD
    MATRIKS_API_KEY

Bir taşıma yalnız resmi dokümanı projeye eklendiğinde `DOCUMENTED_TRANSPORTS`'a girer. Şu an boştur: hangi
değişken ayarlanırsa ayarlansın bağlantı `MatriksConfigurationRequired` ile reddedilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.research.momentum_sources.common import Secret

PLACEHOLDER_TRANSPORTS = ("REST", "MQTT", "SOCKET", "XML")
DOCUMENTED_TRANSPORTS: frozenset[str] = frozenset()  # resmi doküman gelince ve incelendikten sonra doldurulur
DOCUMENTATION_REF: str | None = None  # örn. sağlanan doküman dosyasının yolu + sürümü


class MatriksConfigurationRequired(RuntimeError):
    """Resmi doküman / taşıma / kimlik bilgisi olmadan Matriks bağlantısı yapılamaz."""


def _env(name: str) -> str | None:
    for key in (f"MATRIKS_{name}", f"MATRİKS_{name}"):
        v = os.environ.get(key)
        if v:
            return v
    return None


@dataclass(frozen=True)
class MatriksConfig:
    transport: str | None
    base_url: str | None
    username: Secret
    password: Secret
    api_key: Secret

    @classmethod
    def from_env(cls) -> "MatriksConfig":
        t = _env("TRANSPORT")
        return cls(t.upper() if t else None, _env("BASE_URL"), Secret(_env("USERNAME")), Secret(_env("PASSWORD")),
                   Secret(_env("API_KEY")))

    def missing(self) -> list[str]:
        out = []
        if DOCUMENTATION_REF is None:
            out.append("official technical documentation (see REQUIRED_VENDOR_INFO.md)")
        if self.transport is None:
            out.append("MATRIKS_TRANSPORT")
        elif self.transport not in PLACEHOLDER_TRANSPORTS:
            out.append(f"unsupported transport placeholder '{self.transport}'")
        elif self.transport not in DOCUMENTED_TRANSPORTS:
            out.append(f"transport '{self.transport}' not enabled (no official documentation supplied)")
        if not (self.api_key or (self.username and self.password)):
            out.append("credentials (api key or username/password)")
        return out

    def is_configured(self) -> bool:
        return not self.missing()

    def require(self) -> None:
        miss = self.missing()
        if miss:
            raise MatriksConfigurationRequired("Matriks live integration NOT ACTIVE; missing: " + "; ".join(miss))

    def redacted(self) -> dict:
        """Loglanabilir görünüm: gizli değerler yalnız ayarlı/ayarsız olarak."""
        return {"transport": self.transport, "base_url_set": self.base_url is not None,
                "username_set": bool(self.username), "password_set": bool(self.password),
                "api_key_set": bool(self.api_key), "documented_transports": sorted(DOCUMENTED_TRANSPORTS),
                "documentation_ref": DOCUMENTATION_REF}

    def __repr__(self) -> str:
        return f"MatriksConfig({self.redacted()})"

    __str__ = __repr__
