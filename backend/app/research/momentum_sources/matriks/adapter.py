"""Matriks adaptörü — mevcut kaynak sözleşmesini (`momentum_pilot.sources`) uygular; resmi doküman ve kimlik bilgisi
olmadan HER bağlantı yöntemi `MatriksConfigurationRequired` fırlatır. Uç nokta / REST yolu / MQTT konusu yok.
"""

from __future__ import annotations

from datetime import datetime

from app.research.momentum_pilot.sources import IntradayPriceSource, NewsEventSource, OrderBookSource, OrderFlowSource
from app.research.momentum_sources.common import CapabilitySet
from app.research.momentum_sources.matriks.config import MatriksConfig
from app.research.momentum_sources.matriks.models import CAPABILITIES

PROVIDER = "matriks"


def default_capabilities() -> CapabilitySet:
    """Hepsi UNKNOWN: resmi dokümana referansla `declare` edilmeden değişmez."""
    return CapabilitySet(CAPABILITIES)


class MatriksAdapter(IntradayPriceSource, OrderFlowSource, OrderBookSource, NewsEventSource):
    def __init__(self, config: MatriksConfig | None = None, capabilities: CapabilitySet | None = None):
        self.config = config or MatriksConfig.from_env()
        self.capabilities = capabilities or default_capabilities()

    def __repr__(self) -> str:
        return f"MatriksAdapter({self.config.redacted()})"

    # ---- bağlantı (doküman gelene kadar kapalı)
    def connect(self) -> None:
        self.config.require()
        raise NotImplementedError("transport implementation pending official documentation")

    def subscribe_trades(self, symbols: list[str]) -> None:
        self.config.require()
        raise NotImplementedError

    def disconnect(self) -> None:
        return None

    # ---- mevcut sözleşme
    def bars(self, symbol: str, interval: str, start: datetime, end: datetime):
        self.config.require()
        raise NotImplementedError

    def trades(self, symbol: str, start: datetime, end: datetime):
        self.config.require()
        raise NotImplementedError

    def snapshots(self, symbol: str, start: datetime, end: datetime, depth: int):
        self.config.require()
        raise NotImplementedError

    def events(self, start: datetime, end: datetime, symbols: list[str] | None = None):
        self.config.require()
        raise NotImplementedError

    def status(self) -> dict:
        return {"provider": PROVIDER, "configured": self.config.is_configured(), "missing": self.config.missing(),
                "config": self.config.redacted(), "capabilities": self.capabilities.as_dict(),
                "live_integration": "ACTIVE" if self.config.is_configured() else
                "NOT ACTIVE — WAITING FOR OFFICIAL DOCS/CREDENTIALS"}
