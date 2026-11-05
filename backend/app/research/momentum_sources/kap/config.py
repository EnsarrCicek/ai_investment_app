"""KAP resmi API yapılandırması (ortam değişkenleri; gizli değer kaynakta/logda yok).

    KAP_BASE_URL         resmi temel adres (doküman gelince)
    KAP_API_KEY          aboneye verilen API anahtarı
    KAP_SOURCE_IP_MODE   yetkili kaynak IP düzeni (serbest metin; resmi doküman tanımlayınca doğrulanır)

Kimlik doğrulama başlık adı, sorgu parametreleri, yollar ve temel adres koda YAZILMAZ; resmi entegrasyon dokümanı
gelene kadar `DOCUMENTATION_REF` None'dır ve durum `WAITING_FOR_AUTHORIZATION`'dır.

Erişim durumları:
    WAITING_FOR_AUTHORIZATION  resmi entegrasyon dokümanı / yetki yok (şu an)
    NOT_CONFIGURED             doküman var, anahtar veya temel adres eksik
    ERROR                      yapılandırma geçersiz (ör. temel adres https değil)
    READY_FOR_SMOKE_TEST       doküman + anahtar + adres + uç nokta eşlemeleri tamam
    ACTIVE                     sınırlı smoke test başarıyla tamamlandı (çağıran açıkça bildirir)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.research.momentum_sources.common import Secret

NOT_CONFIGURED = "NOT_CONFIGURED"
WAITING_FOR_AUTHORIZATION = "WAITING_FOR_AUTHORIZATION"
READY_FOR_SMOKE_TEST = "READY_FOR_SMOKE_TEST"
ACTIVE = "ACTIVE"
ERROR = "ERROR"
ACCESS_STATES = (NOT_CONFIGURED, WAITING_FOR_AUTHORIZATION, READY_FOR_SMOKE_TEST, ACTIVE, ERROR)

DOCUMENTATION_REF: str | None = None  # resmi entegrasyon dokümanı (ad + sürüm + tarih) sağlanınca
PREREQUISITES = ("Borsa Istanbul data distribution agreement", "MKK authorization", "authorized source IP(s)",
                 "API KEY supplied to subscriber")
SUPPORT_CONTACT = "kapdestek@mkk.com.tr"  # resmi KAP bilgisine göre entegrasyon soruları; otomatik e-posta YOK


class KapConfigurationRequired(RuntimeError):
    """Resmi doküman / yetki / API anahtarı olmadan KAP API'sine bağlanılmaz."""


@dataclass(frozen=True)
class KapConfig:
    base_url: str | None
    api_key: Secret
    source_ip_mode: str | None

    @classmethod
    def from_env(cls) -> "KapConfig":
        return cls(os.environ.get("KAP_BASE_URL") or None, Secret(os.environ.get("KAP_API_KEY")),
                   os.environ.get("KAP_SOURCE_IP_MODE") or None)

    def access_state(self, endpoints_mapped: bool = False, smoke_test_passed: bool = False) -> str:
        if DOCUMENTATION_REF is None:
            return WAITING_FOR_AUTHORIZATION
        if self.base_url and not self.base_url.lower().startswith("https://"):
            return ERROR
        if not (self.base_url and self.api_key):
            return NOT_CONFIGURED
        if not endpoints_mapped:
            return NOT_CONFIGURED
        return ACTIVE if smoke_test_passed else READY_FOR_SMOKE_TEST

    def missing(self, endpoints_mapped: bool = False) -> list[str]:
        out = []
        if DOCUMENTATION_REF is None:
            out.append("official KAP API integration documentation (see REQUIRED_ACCESS.md)")
            out += [f"prerequisite: {p}" for p in PREREQUISITES]
        if not self.base_url:
            out.append("KAP_BASE_URL")
        if not self.api_key:
            out.append("KAP_API_KEY")
        if not endpoints_mapped:
            out.append("endpoint/method/schema mappings for official services (field_mapping.SERVICES)")
        return out

    def require(self, endpoints_mapped: bool = False) -> None:
        state = self.access_state(endpoints_mapped)
        if state not in (READY_FOR_SMOKE_TEST, ACTIVE):
            raise KapConfigurationRequired(f"KAP official API not available (state={state}); missing: "
                                           + "; ".join(self.missing(endpoints_mapped)))

    def redacted(self) -> dict:
        return {"base_url_set": self.base_url is not None, "api_key_set": bool(self.api_key),
                "source_ip_mode": self.source_ip_mode, "documentation_ref": DOCUMENTATION_REF}

    def __repr__(self) -> str:
        return f"KapConfig({self.redacted()})"

    __str__ = __repr__
