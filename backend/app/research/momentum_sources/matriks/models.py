"""Matriks (ve benzeri düşük gecikmeli BIST kaynakları) için ham araştırma modelleri. Uydurma alan yok.

* `TradeTick`: sağlayıcının işlem kaydı. `aggressor_side` yalnız sağlayıcının BELGELENMİŞ alanından gelirse
  BUY/SELL olabilir (`aggressor_provenance = PROVIDER_FIELD`); aracı kurum (buyer/seller member) bilgisinden
  agresör tarafı TÜRETİLMEZ.
* `OrderFlowSnapshot`: yalnız gerçek tick'lerden ve yalnız TÜM tick'lerin sağlayıcı agresör tarafı varsa
  hesaplanır; aksi halde alanlar None, durum UNSUPPORTED.
* `OrderBookSnapshot`: L1/L5/L10/L25 isteğe bağlı derinlik; türetilmiş öznitelikler yalnız ham seviye varsa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.research.momentum_pilot import sources as src
from app.research.momentum_sources.common import (SECONDARY_ROLE, TS_VERIFIED, SourceContractError, check_received,
                                                  provider_latency, raw_hash, require_identity,
                                                  require_secondary_role, timestamp_status)

AGGRESSOR = ("BUY", "SELL", "UNKNOWN")
PROVIDER_FIELD = "PROVIDER_FIELD"
DEPTHS = (1, 5, 10, 25)
UPDATE_TYPES = ("SNAPSHOT", "DELTA", "UNKNOWN")
CAPABILITIES = ("real_time_trades", "trade_timestamp", "price", "quantity", "buyer_member", "seller_member",
                "aggressor_side", "bid_ask", "level1", "level5", "level10", "level25", "order_flow", "order_arrival",
                "order_cancel", "buyer_seller_analytics", "historical_ticks", "historical_order_flow",
                "historical_depth", "news", "kap")


def aggressor_from_members(buyer_member: str | None, seller_member: str | None) -> str:
    """Belgelenmiş resmi kural OLMADAN aracı kurum bilgisinden agresör tarafı çıkarılmaz."""
    raise SourceContractError("no documented rule: buyer/seller member does not imply aggressor side")


@dataclass(frozen=True)
class TradeTick:
    provider: str
    symbol: str
    received_at: datetime
    price: float
    quantity: float
    raw_hash: str
    identity_status: str = "UNVERIFIED"
    exchange: str | None = None
    currency: str | None = None
    trade_id: str | None = None
    source_timestamp: datetime | None = None
    buyer_member: str | None = None
    seller_member: str | None = None
    aggressor_side: str = "UNKNOWN"
    aggressor_provenance: str | None = None
    source_role: str = SECONDARY_ROLE

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        check_received(self.source_timestamp, self.received_at)
        if self.provider.lower() in src.FORBIDDEN_PROVIDERS:
            raise SourceContractError("sentetik/sahte sağlayıcı kabul edilmez")
        if self.aggressor_side not in AGGRESSOR:
            raise SourceContractError(f"geçersiz agresör tarafı: {self.aggressor_side}")
        if self.aggressor_side != "UNKNOWN" and self.aggressor_provenance != PROVIDER_FIELD:
            raise SourceContractError("agresör tarafı yalnız sağlayıcının belgelenmiş alanından gelebilir")
        if len(self.raw_hash) != 64:
            raise SourceContractError("raw_hash SHA-256 olmalı")

    @property
    def timestamp_status(self) -> str:
        return timestamp_status(self.source_timestamp)

    @property
    def provider_latency(self) -> timedelta | None:
        return provider_latency(self.source_timestamp, self.received_at)

    @staticmethod
    def hash_raw(payload) -> str:
        return raw_hash(payload)


ORDER_FLOW_FIELDS = ("buy_volume", "sell_volume", "net_aggressive_volume", "buy_sell_ratio", "ofi_1m", "ofi_3m",
                     "ofi_5m", "ofi_15m", "large_buy_count", "large_sell_count", "large_trade_net",
                     "aggressor_volume_imbalance")


@dataclass(frozen=True)
class OrderFlowSnapshot:
    provider: str
    symbol: str
    received_at: datetime
    raw_hash: str
    status: str  # COMPUTED_FROM_PROVIDER_TICKS / UNSUPPORTED
    source_timestamp: datetime | None = None
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE
    buy_volume: float | None = None
    sell_volume: float | None = None
    net_aggressive_volume: float | None = None
    buy_sell_ratio: float | None = None
    ofi_1m: float | None = None
    ofi_3m: float | None = None
    ofi_5m: float | None = None
    ofi_15m: float | None = None
    large_buy_count: int | None = None
    large_sell_count: int | None = None
    large_trade_net: float | None = None
    aggressor_volume_imbalance: float | None = None

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        check_received(self.source_timestamp, self.received_at)

    @property
    def timestamp_status(self) -> str:
        return timestamp_status(self.source_timestamp)

    def fields(self) -> dict:
        return {k: getattr(self, k) for k in ORDER_FLOW_FIELDS}

    @classmethod
    def from_ticks(cls, ticks: list[TradeTick], at: datetime, received_at: datetime,
                   window: timedelta = timedelta(minutes=5), large_threshold: float | None = None) -> "OrderFlowSnapshot":
        """`at` = anlık görüntü zamanı (yalnız source_timestamp ≤ at olan tick'ler; nedensel). Agresör tarafı
        sağlayıcıdan gelmeyen tek bir tick bile varsa veya zaman damgası doğrulanmamışsa alanlar None kalır.
        `large_threshold` önceki seans tabanından verilmezse büyük işlem alanları None."""
        if not ticks:
            raise SourceContractError("gerçek tick yok: emir akışı hesaplanmaz (uydurma veri yok)")
        provider, symbol = ticks[0].provider, ticks[0].symbol
        if any(t.provider != provider or t.symbol != symbol for t in ticks):
            raise SourceContractError("tek sağlayıcı ve tek sembol olmalı (birleştirme yok)")
        payload = {"provider": provider, "symbol": symbol, "at": at.isoformat(),
                   "ticks": sorted(t.raw_hash for t in ticks), "large_threshold": large_threshold}
        rh = raw_hash(payload)
        usable = all(t.timestamp_status == TS_VERIFIED and t.aggressor_side in ("BUY", "SELL")
                     and t.aggressor_provenance == PROVIDER_FIELD for t in ticks)
        if not usable:
            return cls(provider, symbol, received_at, rh, "UNSUPPORTED", at)
        past = [t for t in ticks if t.source_timestamp <= at]

        def vol(side, w):
            return sum(t.quantity for t in past if t.aggressor_side == side and t.source_timestamp > at - w)

        def ofi(w):
            b, s = vol("BUY", w), vol("SELL", w)
            return (b - s) / (b + s) if b + s > 0 else None
        b, s = vol("BUY", window), vol("SELL", window)
        kw = {"buy_volume": b, "sell_volume": s, "net_aggressive_volume": b - s,
              "buy_sell_ratio": b / s if s > 0 else None, "aggressor_volume_imbalance": ofi(window),
              **{f"ofi_{m}m": ofi(timedelta(minutes=m)) for m in (1, 3, 5, 15)}}
        if large_threshold is not None:
            big = [t for t in past if t.source_timestamp > at - window and t.quantity >= large_threshold]
            lb = sum(t.aggressor_side == "BUY" for t in big)
            ls = sum(t.aggressor_side == "SELL" for t in big)
            kw.update(large_buy_count=lb, large_sell_count=ls, large_trade_net=(lb - ls) / len(big) if big else None)
        return cls(provider, symbol, received_at, rh, "COMPUTED_FROM_PROVIDER_TICKS", at, **kw)


@dataclass(frozen=True)
class BookLevel:
    bid_price: float | None = None
    bid_quantity: float | None = None
    ask_price: float | None = None
    ask_quantity: float | None = None


@dataclass(frozen=True)
class OrderBookSnapshot:
    provider: str
    symbol: str
    received_at: datetime
    depth: int
    levels: tuple[BookLevel, ...]
    raw_hash: str
    source_timestamp: datetime | None = None
    update_type: str = "UNKNOWN"
    sequence: str | None = None
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        check_received(self.source_timestamp, self.received_at)
        if self.depth not in DEPTHS:
            raise SourceContractError(f"derinlik {DEPTHS} içinden olmalı")
        if len(self.levels) > self.depth:
            raise SourceContractError("seviye sayısı beyan edilen derinliği aşamaz")
        if self.update_type not in UPDATE_TYPES:
            raise SourceContractError(f"güncelleme türü {UPDATE_TYPES} içinden olmalı")

    @property
    def timestamp_status(self) -> str:
        return timestamp_status(self.source_timestamp)


# ------------------------------------------------------------------ defter öznitelikleri (yalnız ham veri varsa)
def _side_sum(book: OrderBookSnapshot, n: int, side: str) -> float | None:
    if len(book.levels) < n:
        return None
    vals = [getattr(lv, f"{side}_quantity") for lv in book.levels[:n]]
    return None if any(v is None for v in vals) else float(sum(vals))


def book_imbalance(book: OrderBookSnapshot, n: int) -> float | None:
    b, a = _side_sum(book, n, "bid"), _side_sum(book, n, "ask")
    return None if b is None or a is None or b + a == 0 else (b - a) / (b + a)


def microprice(book: OrderBookSnapshot) -> float | None:
    if not book.levels:
        return None
    lv = book.levels[0]
    if None in (lv.bid_price, lv.bid_quantity, lv.ask_price, lv.ask_quantity) or lv.bid_quantity + lv.ask_quantity == 0:
        return None
    return (lv.ask_price * lv.bid_quantity + lv.bid_price * lv.ask_quantity) / (lv.bid_quantity + lv.ask_quantity)


def spread_bps(book: OrderBookSnapshot) -> float | None:
    if not book.levels or book.levels[0].bid_price is None or book.levels[0].ask_price is None:
        return None
    b, a = book.levels[0].bid_price, book.levels[0].ask_price
    mid = (a + b) / 2
    return (a - b) / mid * 1e4 if mid > 0 else None


def depth_slope(book: OrderBookSnapshot, n: int = 5) -> float | None:
    """Kümülatif miktarın fiyat mesafesine göre eğimi (alış − satış); n seviye eksiksiz değilse None."""
    mid_src = book.levels[0] if book.levels else None
    if len(book.levels) < n or mid_src is None or mid_src.bid_price is None or mid_src.ask_price is None:
        return None
    mid = (mid_src.bid_price + mid_src.ask_price) / 2
    out = []
    for side, sign in (("bid", -1), ("ask", 1)):
        xs, ys, cum = [], [], 0.0
        for lv in book.levels[:n]:
            p, q = getattr(lv, f"{side}_price"), getattr(lv, f"{side}_quantity")
            if p is None or q is None:
                return None
            cum += q
            xs.append(sign * (p - mid))
            ys.append(cum)
        mx, my = sum(xs) / n, sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        out.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den > 0 else None)
    return None if None in out else out[0] - out[1]


def wall_change(book: OrderBookSnapshot, prev: OrderBookSnapshot, side: str, n: int = 5) -> float | None:
    def wall(b):
        if len(b.levels) < n:
            return None
        q = [getattr(lv, f"{side}_quantity") for lv in b.levels[:n]]
        return None if any(v is None for v in q) else max(q)
    a, p = wall(book), wall(prev)
    return None if a is None or p is None else a - p


def liquidity_withdrawal(book: OrderBookSnapshot, trailing_ask_l5_median: float | None) -> float | None:
    a = _side_sum(book, 5, "ask")
    return None if a is None or not trailing_ask_l5_median else (trailing_ask_l5_median - a) / trailing_ask_l5_median


def imbalance_acceleration(now: OrderBookSnapshot, prev: OrderBookSnapshot, prev2: OrderBookSnapshot,
                           n: int = 5) -> float | None:
    x = [book_imbalance(b, n) for b in (now, prev, prev2)]
    return None if None in x else (x[0] - x[1]) - (x[1] - x[2])
