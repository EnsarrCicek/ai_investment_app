"""Matriks ham alan → kanonik alan eşleme sözleşmesi.

Resmi doküman gelene kadar TÜM eşlemeler UNKNOWN'dur. Türkçe/İngilizce alan adı TAHMİN EDİLMEZ. Doküman geldiğinde
her eşleme, doküman referansıyla (`documentation_ref`) birlikte açıkça doldurulur; UNKNOWN bir alanın okunması
`MatriksConfigurationRequired` fırlatır.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.momentum_sources.matriks.config import MatriksConfigurationRequired

UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FieldMapping:
    canonical: str
    vendor_field: str = UNKNOWN  # TODO: resmi dokümandan
    unit_or_format: str = UNKNOWN  # TODO: ör. zaman dilimi, hassasiyet, ondalık ayırıcı
    documentation_ref: str | None = None


CANONICAL_FIELDS = (
    # işlem (trade tick)
    "symbol", "exchange", "currency", "trade_id", "trade_timestamp", "price", "quantity", "buyer_member",
    "seller_member", "aggressor_side", "sequence_number",
    # emir akışı / analitik
    "order_flow_buy_volume", "order_flow_sell_volume", "order_arrival", "order_cancel",
    # emir defteri
    "book_level", "bid_price", "bid_quantity", "ask_price", "ask_quantity", "book_update_type", "book_sequence",
    # haber / KAP
    "news_published_at", "news_headline", "kap_disclosure_id",
)

REGISTRY: dict[str, FieldMapping] = {f: FieldMapping(f) for f in CANONICAL_FIELDS}


def resolve(canonical: str) -> FieldMapping:
    m = REGISTRY[canonical]
    if m.vendor_field == UNKNOWN or m.documentation_ref is None:
        raise MatriksConfigurationRequired(f"field mapping for '{canonical}' is UNKNOWN (no official documentation)")
    return m


def map_record(raw: dict, canonical_fields: tuple[str, ...]) -> dict:
    """Ham sağlayıcı kaydını kanonik alanlara eşler; bilinmeyen eşleme varsa çalışmaz (tahmin yok)."""
    return {c: raw.get(resolve(c).vendor_field) for c in canonical_fields}


def unknown_fields() -> list[str]:
    return [c for c, m in REGISTRY.items() if m.vendor_field == UNKNOWN or m.documentation_ref is None]
