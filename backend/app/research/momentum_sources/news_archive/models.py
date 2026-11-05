"""Arşivlenen haber/KAP kaydı. `published_at` kaynağın ORİJİNAL yayın zamanıdır (kazıma zamanı ASLA yerine
konmaz); yoksa None + UNVERIFIED. `received_at` gerçek alım anı. Olay türü yalnız başlık metninden (gelecek fiyat
bilgisi kullanılmaz)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from app.research.momentum_pilot.sources import CLOCK_SKEW_TOLERANCE, FORBIDDEN_PROVIDERS
from app.research.momentum_sources.common import (SECONDARY_ROLE, SourceContractError, raw_hash, require_aware,
                                                  require_identity, require_secondary_role)

EVENT_TYPES = ("financial_result", "contract", "investment", "capital_increase", "capital_decrease", "buyback",
               "insider", "regulatory", "partnership", "tender", "credit_rating", "dividend", "other")
TS_PUBLISHED = "PUBLISHED_AT_FROM_SOURCE"
TS_PUBLISHED_AFTER_RECEIVED = "PUBLISHED_AFTER_RECEIVED_CLOCK_SKEW"  # kayıt korunur, işaretlenir
TS_UNVERIFIED = "UNVERIFIED"

# Yalnız başlık metni; sıra önemli (ilk eşleşen). Gelecek fiyat bilgisi YOK.
_RULES = (
    ("capital_decrease", r"sermaye azalt"), ("capital_increase", r"bedelli|bedelsiz|sermaye art[ıi]r"),
    ("buyback", r"geri al[ıi]m"), ("dividend", r"temett[üu]|kar pay[ıi]|kâr pay[ıi]"),
    ("financial_result", r"bilan[çc]o|finansal sonu[çc]|finansal tablo|net kar|net kâr"),
    ("credit_rating", r"kredi derecelendirme|not[uü]n[uü] (?:teyit|yükselt|düşür)|fitch|moody|s&p"),
    ("tender", r"ihale"), ("contract", r"s[öo]zle[şs]me|sipari[şs]"),
    ("partnership", r"i[şs]birli[ğg]i|ortakl[ıi]k|ortak giri[şs]im"), ("investment", r"yat[ıi]r[ıi]m"),
    ("insider", r"pay al[ıi]m sat[ıi]m bildirimi|i[çc]eriden"), ("regulatory", r"\bspk\b|bddk|epdk|rekabet kurulu"),
)


def classify_headline(headline: str) -> str:
    h = headline.lower()
    for name, pat in _RULES:
        if re.search(pat, h):
            return name
    return "other"


def _sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewsArchiveItem:
    provider: str
    source: str | None
    symbol: str
    company: str | None
    published_at: datetime | None
    received_at: datetime
    headline: str
    event_type: str
    event_importance: str | None
    source_url_hash: str | None
    content_hash: str
    raw_hash: str
    published_at_semantics: str
    identity_status: str = "UNVERIFIED"
    source_role: str = SECONDARY_ROLE
    item_key: str | None = None  # sağlayıcının kalıcı öğe kimliği (ör. foreks:<haber_id>)

    def __post_init__(self):
        require_secondary_role(self.source_role)
        require_identity(self.identity_status)
        require_aware(self.published_at, "published_at")
        require_aware(self.received_at, "received_at")
        if self.event_type not in EVENT_TYPES:
            raise SourceContractError(f"bilinmeyen olay türü: {self.event_type}")
        if self.provider.lower() in FORBIDDEN_PROVIDERS:
            raise SourceContractError("sentetik/sahte sağlayıcı kabul edilmez")

    @property
    def timestamp_status(self) -> str:
        if self.published_at is None:
            return TS_UNVERIFIED
        if self.published_at > self.received_at + CLOCK_SKEW_TOLERANCE:
            return TS_PUBLISHED_AFTER_RECEIVED
        return TS_PUBLISHED

    @property
    def source_timestamp(self) -> datetime | None:
        return self.published_at


def from_raw_item(item, provider: str, semantics: str) -> list[NewsArchiveItem]:
    """Mevcut `NewsRawItem` → ilgili her sembol için bir arşiv kaydı (aynı raw_hash; birleştirme yok)."""
    payload = {"provider": provider, "external_id": item.external_id, "title": item.title, "summary": item.summary,
               "url": item.url, "publisher": item.publisher,
               "published_at": item.published_at.isoformat() if item.published_at else None}
    rh = raw_hash(payload)
    content = _sha(f"{item.title}\n{item.summary}")
    return [NewsArchiveItem(provider=provider, source=item.publisher, symbol=s, company=None,
                            published_at=item.published_at, received_at=item.received_at, headline=item.title,
                            event_type=classify_headline(item.title), event_importance=None,
                            source_url_hash=_sha(item.url) if item.url else None, content_hash=content, raw_hash=rh,
                            published_at_semantics=semantics, item_key=item.external_id or None)
            for s in sorted(set(item.related_assets))]
