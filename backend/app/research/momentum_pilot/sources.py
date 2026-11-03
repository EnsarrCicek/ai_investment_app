"""Momentum — gelecekteki veri kaynakları için araştırma arayüzleri ve öznitelik TANIMLARI (veri yok, uydurma yok).

* Hiçbir ücretli sağlayıcı entegre edilmez; sınıflar yalnız sözleşmedir (`NotImplementedError`).
* Ortak meta veri: provider, symbol, exchange, currency (TRY/IST VARSAYILMAZ; bilinmiyorsa None), source_timestamp,
  received_at, provider_latency (= received_at − source_timestamp), identity_status, raw_hash, source_role.
* Yeni kaynak `EXPERIMENTAL_SECONDARY` rolüyle başlar; Yahoo mevcut referanstır. Sağlayıcılar ASLA sessizce
  birleştirilmez: aynı olay birden çok kaynakta ayrı kayıt olarak durur.
* Öznitelikler yalnız gerçek kayıtlardan hesaplanabilir; sentetik / boş kaynakla hesaplama reddedilir.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

REFERENCE = "REFERENCE_PRIMARY"  # mevcut Yahoo Windows toplayıcısı
EXPERIMENTAL_SECONDARY = "EXPERIMENTAL_SECONDARY"
MOBILE_SHADOW = "MOBILE_SHADOW"
SOURCE_ROLES = (REFERENCE, EXPERIMENTAL_SECONDARY, MOBILE_SHADOW)
IDENTITY = ("MATCH", "UNVERIFIED", "MISMATCH")
FORBIDDEN_PROVIDERS = ("synthetic", "fake", "simulated", "mock")
CLOCK_SKEW_TOLERANCE = timedelta(seconds=2)


class SourceContractError(ValueError):
    pass


def raw_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                     default=str).encode()).hexdigest()


@dataclass(frozen=True)
class SourceMeta:
    provider: str
    symbol: str
    exchange: str | None
    currency: str | None
    source_timestamp: datetime  # sağlayıcının olay/bar/haber zamanı (published_at varsa o)
    received_at: datetime  # bizim aldığımız an
    identity_status: str
    raw_hash: str
    source_role: str = EXPERIMENTAL_SECONDARY
    received_must_follow_source: bool = True  # haber gibi saat kayması olası akışlarda False yapılabilir

    def __post_init__(self):
        for t in (self.source_timestamp, self.received_at):
            if t.tzinfo is None:
                raise SourceContractError("zaman damgası saat dilimsiz (varsayılan TSİ/UTC yazılmaz)")
        if self.identity_status not in IDENTITY:
            raise SourceContractError(f"bilinmeyen kimlik durumu: {self.identity_status}")
        if self.source_role not in SOURCE_ROLES:
            raise SourceContractError(f"bilinmeyen kaynak rolü: {self.source_role}")
        if self.provider.lower() in FORBIDDEN_PROVIDERS:
            raise SourceContractError("sentetik/sahte sağlayıcı kabul edilmez")
        if (self.received_must_follow_source
                and self.received_at + CLOCK_SKEW_TOLERANCE < self.source_timestamp):
            raise SourceContractError("received_at, source_timestamp'tan önce olamaz")
        if not (isinstance(self.raw_hash, str) and len(self.raw_hash) == 64):
            raise SourceContractError("raw_hash SHA-256 olmalı")

    @property
    def provider_latency(self) -> timedelta:
        return self.received_at - self.source_timestamp


@dataclass(frozen=True)
class PriceBar:
    meta: SourceMeta
    interval: str
    bar_start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    is_partial: bool


@dataclass(frozen=True)
class Trade:
    meta: SourceMeta
    price: float
    size: float
    aggressor_side: str | None  # "BUY" / "SELL" / None (sağlayıcı vermiyorsa tahmin YOK)


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class BookSnapshot:
    meta: SourceMeta
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


@dataclass(frozen=True)
class NewsEvent:
    meta: SourceMeta  # source_timestamp = ORİJİNAL published_at; kazıma zamanı değil
    event_source: str
    published_at: datetime
    company: str | None
    event_type: str
    event_importance: str | None
    title: str
    event_hash: str = field(default="")

    def __post_init__(self):
        if self.published_at != self.meta.source_timestamp:
            raise SourceContractError("haberde source_timestamp = published_at olmalı (kazıma zamanı değil)")
        if self.event_type not in NEWS_EVENT_CLASSES:
            raise SourceContractError(f"bilinmeyen olay sınıfı: {self.event_type}")


class IntradayPriceSource(ABC):
    @abstractmethod
    def bars(self, symbol: str, interval: str, start: datetime, end: datetime) -> list[PriceBar]: ...


class OrderFlowSource(ABC):
    @abstractmethod
    def trades(self, symbol: str, start: datetime, end: datetime) -> list[Trade]: ...


class OrderBookSource(ABC):
    @abstractmethod
    def snapshots(self, symbol: str, start: datetime, end: datetime, depth: int) -> list[BookSnapshot]: ...


class NewsEventSource(ABC):
    @abstractmethod
    def events(self, start: datetime, end: datetime, symbols: list[str] | None = None) -> list[NewsEvent]: ...


# ------------------------------------------------------------------ birleştirme yasağı / gerçek veri şartı
def assert_single_provider(records) -> str:
    """Bir öznitelik hesabının tüm girdileri TEK sağlayıcı + tek rolden gelmeli (sessiz birleştirme yok)."""
    provs = {(r.meta.provider, r.meta.source_role) for r in records}
    if len(provs) != 1:
        raise SourceContractError(f"sağlayıcılar birleştirilemez: {sorted(provs)}")
    return next(iter(provs))[0]


def require_real_records(records) -> None:
    if not records:
        raise SourceContractError("gerçek kaynak kaydı yok: öznitelik hesaplanmaz (uydurma veri yok)")
    assert_single_provider(records)


def keep_separate(*record_lists) -> dict[str, list]:
    """Aynı olay birden çok kaynakta olabilir: sağlayıcıya göre AYRI listeler döner, birleştirmez."""
    out: dict[str, list] = {}
    for lst in record_lists:
        for r in lst:
            out.setdefault(f"{r.meta.provider}|{r.meta.source_role}", []).append(r)
    return out


# ------------------------------------------------------------------ öznitelik tanımları (veri gelene dek yalnız tanım)
ORDER_FLOW_FEATURES = {
    "buy_volume": "sum of trade size with aggressor_side == BUY in window",
    "sell_volume": "sum of trade size with aggressor_side == SELL in window",
    "net_aggressive_volume": "buy_volume - sell_volume",
    "buy_sell_ratio": "buy_volume / sell_volume (undefined if sell_volume == 0)",
    "order_flow_imbalance": "(buy_volume - sell_volume) / (buy_volume + sell_volume)",
    "ofi_1m": "order_flow_imbalance over trailing 1 minute", "ofi_3m": "... trailing 3 minutes",
    "ofi_5m": "... trailing 5 minutes", "ofi_15m": "... trailing 15 minutes",
    "large_trade_count": "trades with size >= prior-session 99th percentile trade size (baseline from prior sessions)",
    "large_trade_net_direction": "(large BUY count - large SELL count) / large_trade_count",
    "volume_weighted_aggressor_imbalance": "sum(size * sign(side)) / sum(size) over trailing 5 minutes",
}
ORDER_FLOW_REQUIRES = ("trade timestamps", "trade size", "aggressor side from provider (not inferred)")
ORDER_BOOK_FEATURES = {
    "bid_volume_L1": "size at best bid", "ask_volume_L1": "size at best ask",
    "bid_volume_L5": "sum size bid levels 1..5", "ask_volume_L5": "sum size ask levels 1..5",
    "book_imbalance_L1": "(bid_L1 - ask_L1) / (bid_L1 + ask_L1)",
    "book_imbalance_L5": "(bid_L5 - ask_L5) / (bid_L5 + ask_L5)",
    "microprice": "(ask_px * bid_sz + bid_px * ask_sz) / (bid_sz + ask_sz) at L1",
    "spread_bps": "(ask_px - bid_px) / mid * 1e4", "spread_change": "spread_bps - spread_bps 5 minutes earlier",
    "bid_wall_change": "change in max single-level bid size within L5 vs 5 minutes earlier",
    "ask_wall_change": "change in max single-level ask size within L5 vs 5 minutes earlier",
    "depth_slope": "regression slope of cumulative size vs price distance across L1..L5 (bid minus ask)",
    "liquidity_withdrawal": "drop of ask_volume_L5 vs its trailing 15-minute median",
    "imbalance_acceleration": "book_imbalance_L5 change over last 1 minute minus change over previous 1 minute",
}
ORDER_BOOK_REQUIRES = ("Level 2 depth >= 5 levels", "snapshot timestamps", "bid/ask price and size")
NEWS_EVENT_SCHEMA = ("event_source", "published_at", "received_at", "company", "symbol", "event_type",
                     "event_importance", "event_hash")
NEWS_EVENT_CLASSES = ("financial_result", "contract", "investment", "capital_increase", "buyback", "insider",
                      "regulatory", "partnership", "tender", "credit_rating", "other")
NEWS_TIMESTAMP_RULE = "use original published_at when present; never infer from article scrape time"

PARALLEL_COLLECTION_RULES = {
    "reference": "Yahoo remains the existing reference (REFERENCE_PRIMARY)",
    "new_source_role": EXPERIMENTAL_SECONDARY + " until validated",
    "merge_policy": "never silently merge providers; same event may exist in multiple sources as separate records",
    "stored_fields": ["source_timestamp", "received_at", "provider", "raw_hash", "source_role", "identity_status"],
    "holdout": "raw collection may continue; no labels/alerts/events/model outcomes for FUTURE_HOLDOUT",
}


def spec() -> dict:
    return {"order_flow_features": ORDER_FLOW_FEATURES, "order_flow_requires": list(ORDER_FLOW_REQUIRES),
            "order_book_features": ORDER_BOOK_FEATURES, "order_book_requires": list(ORDER_BOOK_REQUIRES),
            "news_event_schema": list(NEWS_EVENT_SCHEMA), "news_event_classes": list(NEWS_EVENT_CLASSES),
            "news_timestamp_rule": NEWS_TIMESTAMP_RULE, "parallel_collection": PARALLEL_COLLECTION_RULES,
            "common_metadata": [f for f in SourceMeta.__dataclass_fields__] + ["provider_latency (derived)"]}


