"""Sağlayıcıdan bağımsız KAP araştırma modelleri. Yalnız kanonik kavramlar; resmi alanlara eşleme bilinmiyorsa
değer None (uydurma yok). Sembol / ISIN / borsa şirket adından ÇIKARILMAZ; yalnız resmi API meta verisinden gelir.

* `source_timestamp` = resmi KAP yayın zamanı (yoksa None → UNVERIFIED); `received_at` = bizim gerçek alım anımız.
  Geriye dönük çekilen veride bile received_at, source_timestamp'a EŞİTLENMEZ.
* `source_role` her zaman EXPERIMENTAL_SECONDARY.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.research.momentum_pilot import sources as src
from app.research.momentum_sources.common import (SECONDARY_ROLE, SourceContractError, check_received,
                                                  provider_latency, require_aware, require_identity,
                                                  require_secondary_role, timestamp_status)

PROVIDER = "kap_official"


@dataclass(frozen=True)
class KapDisclosure:
    received_at: datetime
    raw_hash: str
    provider: str = PROVIDER
    disclosure_id: str | None = None  # resmi kimlik (semantiği doğrulanmadan kayıt anahtarı olarak kullanılmaz)
    source_timestamp: datetime | None = None
    member_code: str | None = None
    member_name: str | None = None
    symbol: str | None = None
    isin: str | None = None
    disclosure_type: str | None = None
    subject: str | None = None
    summary: str | None = None
    detail_available: bool | None = None
    attachments_available: bool | None = None
    disclosure_index: int | None = None
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        check_received(self.source_timestamp, self.received_at)
        if self.provider.lower() in src.FORBIDDEN_PROVIDERS:
            raise SourceContractError("sentetik/sahte sağlayıcı kabul edilmez")
        if len(self.raw_hash) != 64:
            raise SourceContractError("raw_hash SHA-256 olmalı")

    @property
    def timestamp_status(self) -> str:
        return timestamp_status(self.source_timestamp)

    @property
    def archival_discovery_lag(self) -> timedelta | None:
        """received_at − source_timestamp: arşiv keşif gecikmesi (ağ gecikmesi değil)."""
        return provider_latency(self.source_timestamp, self.received_at)


@dataclass(frozen=True)
class KapMember:
    received_at: datetime
    raw_hash: str
    provider: str = PROVIDER
    member_id: str | None = None
    member_code: str | None = None
    member_name: str | None = None
    source_timestamp: datetime | None = None
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        require_aware(self.received_at, "received_at")
        check_received(self.source_timestamp, self.received_at)


@dataclass(frozen=True)
class KapSecurity:
    received_at: datetime
    raw_hash: str
    provider: str = PROVIDER
    member_id: str | None = None
    member_code: str | None = None
    symbol: str | None = None  # yalnız resmi API meta verisinden
    isin: str | None = None
    security_type: str | None = None
    exchange: str | None = None  # varsayılmaz
    source_timestamp: datetime | None = None
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        check_received(self.source_timestamp, self.received_at)


def symbol_from_company_name(name: str) -> str:
    """Şirket adından sembol/ISIN/borsa çıkarımı yapılmaz (resmi meta veri gerekir)."""
    raise SourceContractError("symbol/ISIN/exchange are never inferred from company name")
