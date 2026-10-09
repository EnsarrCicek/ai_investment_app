"""Kurumsal işlem doğrulayıcısı — satış (`plan_sale`), açık pozisyon K/Z'si (`calculate_pnl`) ve limit kontrolü
(`check_limits`) için TEK algoritma.

Soru: pozisyonun `en erken alış tarihi → değerleme/satış tarihi` aralığında adet/maliyet tabanını değiştirebilecek
kurumsal işlemler EKSİKSİZ kontrol edildi mi ve bu aralıkta düzeltme gerektiren olay yok mu?

Doğrulama (verified=True, reason=MATCH) ancak şunların hepsiyle (öncelik sırası):
  1. kaynak yanıtı var (yoksa COVERAGE_MISSING — "olay bulunamadı" ASLA "olay yok" sayılmaz),
  2. elde tutma başlangıcı (en erken alış) DOĞRULANMIŞ bir işlem kaynağından (ACQUISITION_DATE_UNVERIFIED). Düz
     `buy_date` — uygulamada kaydın oluşturulduğu an, elle giriş, eski kayıt — gerçek alış tarihi kanıtı DEĞİLDİR,
  3. sembol → ISIN eşlemesi doğrulanmış, XIST, ve tüm aralık için geçerli (IDENTITY_UNVERIFIED / IDENTITY_MISMATCH),
  4. aralığı (iki uç dahil) kapsayan, zorunlu tüm olay türlerini içeren COMPLETE coverage; kayıtlar ancak araya
     beklenen BIST seansı girmiyorsa birleşir (COVERAGE_INCOMPLETE),
  5. aralıktaki her bildirimin düzeltme/iptal durumu belli (CORRECTION_STATUS_UNVERIFIED),
  6. aralıkta desteklenmeyen (UNSUPPORTED_EVENT) veya adet/maliyet düzeltmesi gerektiren
     (EVENT_REQUIRES_POSITION_ADJUSTMENT) geçerli olay yok. Nakit temettü engel değildir (listelenir).

Kurumsal işlem DÜZELTMESİ YAPILMAZ; olay varsa sonuç doğrulanmamıştır (kayıtlı adet/maliyet otomatik doğru sayılmaz).
Olay penceresi İKİ UÇ DAHİL: `required_from <= effective_date <= required_through`. Alış ve olayın gün içi/seans
sırası kanıtı olmadığından alış günündeki olayın alış fiyatına "zaten yansıdığı" VARSAYILMAZ (yanlış pozitif
yerine yanlış negatif). Bu yüzden `position_review`'in kendi tarih filtresine (`başlangıç < olay`) olay tarihi
taşınmaz; doğrulanmamış her sonuç oraya "kontrol yok" olarak gider (bkz. `position_review_check`).

Üretimde lisansı doğrulanmış bir kaynak bağlı DEĞİLDİR: varsayılan sağlayıcı her zaman `None` döner →
COVERAGE_MISSING. Sahte/varsayılan "olay yok" üretilmez.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable, Protocol

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import corporate_action as ca
from app.models.portfolio_position import PortfolioPosition
from app.services.market_data.trading_calendar import expected_trading_sessions

VERIFIER_VERSION = "corporate-action-verifier-v1"

MATCH = "MATCH"
COVERAGE_MISSING = "COVERAGE_MISSING"
COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
ACQUISITION_DATE_UNVERIFIED = "ACQUISITION_DATE_UNVERIFIED"
CORRECTION_STATUS_UNVERIFIED = "CORRECTION_STATUS_UNVERIFIED"
UNSUPPORTED_EVENT = "UNSUPPORTED_EVENT"
EVENT_REQUIRES_POSITION_ADJUSTMENT = "EVENT_REQUIRES_POSITION_ADJUSTMENT"
SOURCE_ERROR = "SOURCE_ERROR"
INVALID_RANGE = "INVALID_RANGE"

# Kayıtlı adet/maliyetin düzeltilmesini gerektiren (aynı enstrümanda kalan) olaylar.
ADJUSTMENT_EVENT_TYPES = frozenset({ca.SPLIT, ca.REVERSE_SPLIT, ca.BONUS, ca.RIGHTS})
# Enstrüman kimliğini değiştiren olaylar: otomatik takip modeli yok → desteklenmez.
IDENTITY_CHANGING_EVENT_TYPES = frozenset({ca.MERGER, ca.DEMERGER, ca.SYMBOL_CHANGE})
NON_ADJUSTING_EVENT_TYPES = frozenset({ca.CASH_DIVIDEND})

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


class CorporateActionProvider(Protocol):
    """Kaynaktan bağımsız arayüz. Ağ/API ayrıntısı uygulamaya aittir. Dönüş deterministik olmalı ve her kayıt kaynak
    bilgisi taşımalıdır. Kaynak yoksa/erişilemezse `None` döner — boş olay listesi ile 'olay yok' beyan EDİLMEZ."""

    def get_corporate_action_coverage(self, symbol: str, start: date, end: date) -> ca.CorporateActionSourceResult | None:
        ...


class UnavailableCorporateActionProvider:
    """Üretim varsayılanı: lisansı doğrulanmış kurumsal işlem kaynağı bağlı değil."""

    def get_corporate_action_coverage(self, symbol: str, start: date, end: date) -> None:
        return None


def default_corporate_action_provider() -> CorporateActionProvider:
    return UnavailableCorporateActionProvider()


def istanbul_date(value: datetime | date) -> date:
    if isinstance(value, datetime):
        return value.astimezone(ISTANBUL_TZ).date() if value.tzinfo else value.date()
    return value


def acquisition_evidence(lots: Iterable[PortfolioPosition]) -> ca.AcquisitionDateEvidence:
    """Pozisyonun elde tutma başlangıcı kanıtı: en erken lot alışı. Yalnız TÜM lotların alış tarihi doğrulanmışsa
    doğrulanmıştır (doğrulanmamış bir lotun gerçek alışı kayıtlı en erken tarihten önce olabilir)."""
    lots = list(lots)
    first = min(lots, key=lambda p: p.buy_date)
    verified = all(p.acquisition_date_verified for p in lots)
    sources = {p.acquisition_date_source or ca.ACQUISITION_SOURCE_UNSPECIFIED for p in lots}
    return ca.AcquisitionDateEvidence(acquired_at=first.buy_date, verified=verified,
                                      source=sources.pop() if len(sources) == 1 else "MIXED",
                                      reference=first.acquisition_date_reference if verified else None,
                                      recorded_at=first.created_at)


def _evidence(value: ca.AcquisitionDateEvidence | datetime | date) -> ca.AcquisitionDateEvidence:
    """Düz tarih/zaman → doğrulanmamış kanıt (kaynak belirtilmemiş). Doğrulama hiçbir zaman düz tarihe dayanmaz."""
    if isinstance(value, ca.AcquisitionDateEvidence):
        return value
    when = value if isinstance(value, datetime) else datetime(value.year, value.month, value.day, tzinfo=ISTANBUL_TZ)
    return ca.AcquisitionDateEvidence(acquired_at=when, verified=False, source=ca.ACQUISITION_SOURCE_UNSPECIFIED)


def _result(symbol: str, start: date, end: date, reason: str, *, identity: ca.InstrumentIdentity | None = None,
            span: tuple[date, date] | None = None, source: str | None = None,
            events: Iterable[ca.CorporateActionEvent] = ()) -> ca.CorporateActionVerification:
    return ca.CorporateActionVerification(
        verified=reason == MATCH, reason=reason, symbol=symbol, required_from=start, required_through=end,
        checked_from=span[0] if span else None, checked_through=span[1] if span else None, source=source,
        instrument_identity_status=identity.identity_status if identity else None,
        isin=identity.isin if identity else None, events=tuple(events), verifier_version=VERIFIER_VERSION)


def _identity_reason(identity: ca.InstrumentIdentity | None, symbol: str, start: date, end: date) -> str | None:
    if identity is None or identity.isin is None or identity.identity_status != ca.IDENTITY_VERIFIED:
        return IDENTITY_UNVERIFIED
    if not _ISIN.match(identity.isin):
        return IDENTITY_UNVERIFIED
    if identity.symbol.upper() != symbol or identity.mic != ca.XIST:
        return IDENTITY_MISMATCH
    # Eşleme tüm elde tutma aralığı için geçerli olmalı (sembol yeniden kullanımı/değişimi).
    if identity.valid_from is None or identity.valid_from > start:
        return IDENTITY_UNVERIFIED
    if identity.valid_through is not None and identity.valid_through < end:
        return IDENTITY_UNVERIFIED
    return None


def _contiguous(prev_through: date, next_from: date) -> bool:
    """Bitişik: sonraki kayıt bir önceki bitişin ertesi günü veya öncesinde başlar, YA DA aradaki günlerin hiçbiri
    beklenen BIST seansı değildir (hafta sonu/resmî tatil). Takvim o yılı desteklemiyorsa (None) bitişik SAYILMAZ."""
    if next_from <= prev_through + timedelta(days=1):
        return True
    return expected_trading_sessions(prev_through + timedelta(days=1), next_from - timedelta(days=1)) == []


def _covering_span(coverage: Iterable[ca.CorporateActionCoverage], start: date,
                   end: date) -> tuple[tuple[date, date] | None, set[str]]:
    """Uygun (COMPLETE, zorunlu türlerin tamamı) kayıtları bitişik aralıklarda birleştirir; [start, end]'i içeren
    birleşik aralığı ve kullanılan kaynakları döner (bitişiklik: `_contiguous`)."""
    usable = sorted((c for c in coverage if c.completeness == ca.COVERAGE_COMPLETE
                     and ca.REQUIRED_EVENT_TYPES <= c.covered_event_types),
                    key=lambda c: (c.checked_from, c.checked_through))
    spans: list[list] = []
    for c in usable:
        if spans and _contiguous(spans[-1][1], c.checked_from):
            spans[-1][1] = max(spans[-1][1], c.checked_through)
            spans[-1][2].add(c.provenance.source)
        else:
            spans.append([c.checked_from, c.checked_through, {c.provenance.source}])
    for frm, thru, sources in spans:
        if frm <= start and thru >= end:
            return (frm, thru), sources
    return None, set()


def verify_corporate_actions(symbol: str, acquisition: ca.AcquisitionDateEvidence | datetime | date,
                             required_through: datetime | date,
                             provider: CorporateActionProvider | None = None) -> ca.CorporateActionVerification:
    """Kanonik doğrulama. `acquisition`: elde tutma başlangıcı kanıtı (düz tarih/zaman → doğrulanmamış).
    `provider=None` → üretim varsayılanı (kaynak yok → COVERAGE_MISSING)."""
    symbol = symbol.upper()
    acquisition = _evidence(acquisition)
    start, end = istanbul_date(acquisition.acquired_at), istanbul_date(required_through)
    if start > end:
        return _result(symbol, start, end, INVALID_RANGE)
    provider = provider or default_corporate_action_provider()
    try:
        response = provider.get_corporate_action_coverage(symbol, start, end)
    except Exception:  # noqa: BLE001 — kaynak hatası doğrulanmamış sonuçtur
        return _result(symbol, start, end, SOURCE_ERROR)
    if response is None:
        return _result(symbol, start, end, COVERAGE_MISSING)
    if not acquisition.verified:
        return _result(symbol, start, end, ACQUISITION_DATE_UNVERIFIED)

    identity = response.identity
    reason = _identity_reason(identity, symbol, start, end)
    if reason:
        return _result(symbol, start, end, reason, identity=identity)
    if any(c.isin != identity.isin or c.mic != ca.XIST or c.symbol.upper() != symbol for c in response.coverage) or \
            any(e.isin != identity.isin for e in response.events):
        return _result(symbol, start, end, IDENTITY_MISMATCH, identity=identity)

    if not response.coverage:
        return _result(symbol, start, end, COVERAGE_MISSING, identity=identity)
    span, sources = _covering_span(response.coverage, start, end)
    if span is None:
        return _result(symbol, start, end, COVERAGE_INCOMPLETE, identity=identity)
    source = ",".join(sorted(sources))

    by_id = {e.event_id: e for e in response.events}
    in_window = [e for e in response.events if start <= e.effective_date <= end]
    active: list[ca.CorporateActionEvent] = []
    correction_unverified = False
    for e in in_window:
        if e.status not in ca.EVENT_STATUSES or e.status == ca.EVENT_STATUS_UNKNOWN:
            correction_unverified = True
        elif e.status == ca.EVENT_CANCELLED:
            continue
        elif e.status == ca.EVENT_SUPERSEDED:
            # Yerine geçen geçerli bir düzeltme bildirimi bulunmalı; yoksa hangi değerin geçerli olduğu belirsiz.
            if not any(r.original_event_id == e.event_id and r.status == ca.EVENT_ACTIVE for r in response.events):
                correction_unverified = True
        else:  # ACTIVE
            if e.original_event_id is not None:
                original = by_id.get(e.original_event_id)
                if original is None or original.status not in (ca.EVENT_SUPERSEDED, ca.EVENT_CANCELLED):
                    correction_unverified = True  # düzeltme zinciri doğrulanamadı
            active.append(e)
    if correction_unverified:
        return _result(symbol, start, end, CORRECTION_STATUS_UNVERIFIED, identity=identity, span=span, source=source,
                       events=active)
    types = {e.event_type for e in active}
    if types - ca.EVENT_TYPES or types & IDENTITY_CHANGING_EVENT_TYPES:
        return _result(symbol, start, end, UNSUPPORTED_EVENT, identity=identity, span=span, source=source, events=active)
    if types & ADJUSTMENT_EVENT_TYPES:
        return _result(symbol, start, end, EVENT_REQUIRES_POSITION_ADJUSTMENT, identity=identity, span=span,
                       source=source, events=active)
    return _result(symbol, start, end, MATCH, identity=identity, span=span, source=source, events=active)


def position_review_check(v: ca.CorporateActionVerification) -> dict | None:
    """Doğrulama sonucunu `position_review`'in `corporate_action_checks` girdisine çevirir (kararı verifier verir;
    review yalnız taşır). Doğrulanmış → olaysız tam kontrol. Doğrulanmamış HER sonuç (düzeltme gerektiren olay dahil)
    → None: review bunu CORPORATE_ACTIONS_UNVERIFIED yapar. Olay tarihleri bilinçli olarak TAŞINMAZ: review'in
    `başlangıç < olay` filtresi alış günündeki olayı düşürüp sonucu yeniden geçerli sayabilirdi. Kesin gerekçe
    çağıranın çıktısındaki `corporate_action_verification` özetindedir."""
    if not v.verified:
        return None
    return {"checked_from": v.checked_from.isoformat(), "checked_through": v.checked_through.isoformat(),
            "split_or_bonus_dates": [], "source": v.source}


def effective_transaction_verification(transaction_id: str, snapshot_verified: bool | None,
                                       records: Iterable[ca.TransactionBasisVerification],
                                       required_from: date, required_through: date
                                       ) -> tuple[bool, str | None, ca.TransactionBasisVerification | None]:
    """Değişmez satış kaydının okuma zamanındaki doğrulama durumu: (verified, reason, dayanak kayıt).

    Satış anı anlık görüntüsü doğrulanmışsa o geçerlidir. Değilse, AYNI işlem ve AYNI aralık için en son
    (verified_at) ekleme-yalnız doğrulama kaydı kullanılır; aralığı farklı kayıt yok sayılır. Kayıt yoksa
    doğrulanmamış kalır."""
    if snapshot_verified is True:
        return True, MATCH, None
    matching = [r for r in records if r.transaction_id == transaction_id
                and r.required_from == required_from and r.required_through == required_through]
    if not matching:
        return False, None, None
    latest = max(matching, key=lambda r: r.verified_at)
    return latest.verified, latest.reason, latest
