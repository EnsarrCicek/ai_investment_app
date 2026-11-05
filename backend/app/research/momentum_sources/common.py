"""İkincil kaynakların ortak semantiği: rol, kimlik, zaman damgası durumu, gecikme, yetenek beyanı, gizli değer.

* `source_timestamp` sağlayıcının ORİJİNAL zamanıdır; yoksa uydurulmaz → `timestamp_status = UNVERIFIED`.
* `received_at` bizim gerçek alım anımızdır; geriye tarihlenemez (source_timestamp'tan önce olamaz, küçük saat
  kayması toleransı hariç).
* Kimlik yalnız sağlayıcı meta verisinden: TRY / IST / BIST sembolden VARSAYILMAZ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.research.momentum_pilot.sources import (CLOCK_SKEW_TOLERANCE, EXPERIMENTAL_SECONDARY, IDENTITY,
                                                 SourceContractError, raw_hash)

SECONDARY_ROLE = EXPERIMENTAL_SECONDARY
TS_VERIFIED = "PROVIDER_TIMESTAMP"
TS_UNVERIFIED = "UNVERIFIED"
SUPPORTED, UNSUPPORTED, UNKNOWN = "SUPPORTED", "UNSUPPORTED", "UNKNOWN"
CAPABILITY_STATES = (SUPPORTED, UNSUPPORTED, UNKNOWN)

__all__ = ["SECONDARY_ROLE", "TS_VERIFIED", "TS_UNVERIFIED", "SUPPORTED", "UNSUPPORTED", "UNKNOWN", "IDENTITY",
           "SourceContractError", "raw_hash", "require_aware", "timestamp_status", "check_received",
           "provider_latency", "require_secondary_role", "require_identity", "CapabilitySet", "Secret"]


def require_aware(t: datetime | None, name: str) -> None:
    if t is not None and t.tzinfo is None:
        raise SourceContractError(f"{name} saat dilimsiz (varsayılan TSİ/UTC yazılmaz)")


def timestamp_status(source_timestamp: datetime | None) -> str:
    return TS_VERIFIED if source_timestamp is not None else TS_UNVERIFIED


def check_received(source_timestamp: datetime | None, received_at: datetime) -> None:
    """received_at geriye tarihlenemez. source_timestamp yoksa kontrol edilecek bir şey yok (uydurulmaz)."""
    require_aware(received_at, "received_at")
    require_aware(source_timestamp, "source_timestamp")
    if source_timestamp is not None and received_at + CLOCK_SKEW_TOLERANCE < source_timestamp:
        raise SourceContractError("received_at, source_timestamp'tan önce olamaz (geriye tarihleme yasak)")


def provider_latency(source_timestamp: datetime | None, received_at: datetime) -> timedelta | None:
    return None if source_timestamp is None else received_at - source_timestamp


def require_secondary_role(role: str) -> None:
    if role != SECONDARY_ROLE:
        raise SourceContractError(f"araştırma süresince ikincil kaynak rolü {SECONDARY_ROLE} olmalı (verilen: {role})")


def require_identity(status: str) -> None:
    if status not in IDENTITY:
        raise SourceContractError(f"bilinmeyen kimlik durumu: {status}")


@dataclass
class CapabilitySet:
    """Yetenek beyanı. Varsayılan UNKNOWN; SUPPORTED/UNSUPPORTED yalnız resmi dokümana referansla verilir
    (pazarlama adından çıkarım yok)."""

    names: tuple[str, ...]
    states: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.states.setdefault(n, UNKNOWN)

    def declare(self, name: str, state: str, documentation_ref: str) -> None:
        if name not in self.names:
            raise SourceContractError(f"bilinmeyen yetenek: {name}")
        if state not in CAPABILITY_STATES:
            raise SourceContractError(f"geçersiz yetenek durumu: {state}")
        if state != UNKNOWN and not (documentation_ref and documentation_ref.strip()):
            raise SourceContractError("SUPPORTED/UNSUPPORTED yalnız resmi doküman referansıyla beyan edilir")
        self.states[name] = state
        self.evidence[name] = documentation_ref

    def as_dict(self) -> dict:
        return {n: {"state": self.states[n], "evidence": self.evidence.get(n)} for n in self.names}


class Secret:
    """Gizli değer: repr/str maskeli; yalnız `reveal()` ile okunur (log/hata mesajına girmez)."""

    __slots__ = ("_v",)

    def __init__(self, value: str | None):
        self._v = value or None

    def __bool__(self) -> bool:
        return self._v is not None

    def reveal(self) -> str | None:
        return self._v

    def __repr__(self) -> str:
        return "Secret(<set>)" if self._v else "Secret(<unset>)"

    __str__ = __repr__
