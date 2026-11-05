"""Resmi KAP servis kaydı ve alan eşleme sözleşmesi.

* `SERVICES`: yalnız resmi KAP dokümantasyonunda ADI doğrulanmış servisler. Resmi açıklama metni elde olmadığından
  `official_description = NOT_SUPPLIED`; uç nokta yolu, HTTP yöntemi, istek/yanıt şeması UNKNOWN.
* `FIELDS`: kanonik alan → resmi yanıt alanı; hepsi UNKNOWN. Türkçe/İngilizce alan adı TAHMİN EDİLMEZ. Eşlemeler
  ancak resmi yanıt örneği / şema dokümanı geldiğinde, `documentation_ref` ile doldurulur.
* `DISCLOSURE_ID_SEMANTICS_CONFIRMED = False`: resmi bildirim kimliğinin tekilliği/monotonluğu doğrulanana kadar
  kimlik tabanlı kayıt/tekrar politikası çalıştırılmaz (kimlik uydurulmaz).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.momentum_sources.kap.config import KapConfigurationRequired

UNKNOWN = "UNKNOWN"
NOT_SUPPLIED = "NOT_SUPPLIED"
CONFIRMED_SERVICE = "CONFIRMED_SERVICE"
DISCLOSURE_ID_SEMANTICS_CONFIRMED = False

SERVICE_NAMES = ("disclosures", "disclosureDetail", "downloadAttachment", "lastDisclosureIndex", "members",
                 "memberDetail", "funds", "fundDetail", "memberSecurities", "blockedDisclosures", "caEventStatus")


@dataclass(frozen=True)
class ServiceSpec:
    service_name: str
    official_description: str = NOT_SUPPLIED
    availability: str = CONFIRMED_SERVICE
    endpoint_path: str = UNKNOWN
    http_method: str = UNKNOWN
    request_schema: str = UNKNOWN
    response_schema: str = UNKNOWN
    documentation_ref: str | None = None

    @property
    def mapped(self) -> bool:
        return UNKNOWN not in (self.endpoint_path, self.http_method, self.request_schema, self.response_schema) \
            and self.documentation_ref is not None


SERVICES: dict[str, ServiceSpec] = {n: ServiceSpec(n) for n in SERVICE_NAMES}


@dataclass(frozen=True)
class FieldMapping:
    canonical: str
    official_field: str = UNKNOWN
    documentation_ref: str | None = None


CANONICAL_FIELDS = (
    # bildirim
    "disclosure_id", "published_at", "member_code", "member_name", "symbol", "isin", "disclosure_type", "subject",
    "summary", "detail_available", "attachments_available", "disclosure_index",
    # üye / menkul kıymet
    "member_id", "security_type",
)
FIELDS: dict[str, FieldMapping] = {f: FieldMapping(f) for f in CANONICAL_FIELDS}


def endpoints_mapped(services=("lastDisclosureIndex", "disclosures", "disclosureDetail")) -> bool:
    return all(SERVICES[s].mapped for s in services)


def resolve_service(name: str) -> ServiceSpec:
    spec = SERVICES[name]
    if not spec.mapped:
        raise KapConfigurationRequired(f"service '{name}' is confirmed by name only; endpoint/method/schema UNKNOWN")
    return spec


def resolve_field(canonical: str) -> FieldMapping:
    m = FIELDS[canonical]
    if m.official_field == UNKNOWN or m.documentation_ref is None:
        raise KapConfigurationRequired(f"field mapping for '{canonical}' is UNKNOWN (no official schema)")
    return m


def unknown_fields() -> list[str]:
    return [c for c, m in FIELDS.items() if m.official_field == UNKNOWN or m.documentation_ref is None]


def registry() -> list[dict]:
    from dataclasses import asdict
    return [{**asdict(s), "mapped": s.mapped} for s in SERVICES.values()]
