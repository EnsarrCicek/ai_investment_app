"""Resmi KAP API adaptörü — mevcut `NewsEventSource` sözleşmesini uygular. Resmi doküman, yetki ve API anahtarı
olmadan HER çağrı `KapConfigurationRequired` fırlatır (fail-closed). Herkese açık site kullanılmaz.

`KapServiceClient` yalnız SEMANTİK işlemleri tanımlar (son bildirim indeksi, indeksten sonraki bildirimler,
bildirim detayı, üyeler); HTTP yolu / yöntem / parametre adı resmi dokümandan gelecektir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.research.momentum_pilot.sources import NewsEventSource
from app.research.momentum_sources.kap import field_mapping as fm
from app.research.momentum_sources.kap.config import KapConfig
from app.research.momentum_sources.kap.models import PROVIDER, KapDisclosure


class KapServiceClient(ABC):
    """Resmi servislerin anlamsal karşılıkları (lastDisclosureIndex, disclosures, disclosureDetail, members)."""

    @abstractmethod
    def last_disclosure_index(self) -> int: ...

    @abstractmethod
    def disclosures_after(self, index: int, max_records: int) -> list[KapDisclosure]: ...

    @abstractmethod
    def disclosure_detail(self, disclosure_id: str) -> dict: ...


class KapOfficialAdapter(KapServiceClient, NewsEventSource):
    def __init__(self, config: KapConfig | None = None):
        self.config = config or KapConfig.from_env()

    def __repr__(self) -> str:
        return f"KapOfficialAdapter({self.config.redacted()})"

    def _require(self):
        self.config.require(fm.endpoints_mapped())
        raise NotImplementedError("HTTP transport pending official integration documentation")

    def last_disclosure_index(self) -> int:
        self._require()

    def disclosures_after(self, index: int, max_records: int) -> list[KapDisclosure]:
        self._require()

    def disclosure_detail(self, disclosure_id: str) -> dict:
        self._require()

    def events(self, start: datetime, end: datetime, symbols: list[str] | None = None):
        self._require()

    def status(self) -> dict:
        mapped = fm.endpoints_mapped()
        state = self.config.access_state(mapped)
        return {"provider": PROVIDER, "access_state": state, "config": self.config.redacted(),
                "missing": self.config.missing(mapped), "services": fm.registry(),
                "unknown_fields": fm.unknown_fields(),
                "disclosure_id_semantics_confirmed": fm.DISCLOSURE_ID_SEMANTICS_CONFIRMED,
                "public_site_scraping": "DISABLED / NOT IMPLEMENTED",
                "live_integration": "WAITING FOR AUTHORIZATION/API DOCUMENTATION" if state != "ACTIVE" else "ACTIVE"}
