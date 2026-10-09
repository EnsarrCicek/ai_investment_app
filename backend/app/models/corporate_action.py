"""Kurumsal işlem doğrulamasının kanonik veri modeli (kaynaktan bağımsız).

Üç ayrı kavram:
* `InstrumentIdentity`  — sembolün hangi tarih aralığında hangi ISIN'e karşılık geldiği (tarihsel eşleme).
* `CorporateActionEvent` — tek bir kurumsal işlem bildirimi (düzeltme/iptal durumu ve kaynak bilgisiyle).
* `CorporateActionCoverage` — "bu aralık, bu olay türleri için EKSİKSİZ kontrol edildi" kaydı.

"Olay bulunamadı" ile "aralık eksiksiz kontrol edildi ve olay yok" AYNI DEĞİLDİR: olay listesi boş olabilir, ama
doğrulama yalnız aralığı kapsayan tam bir coverage kaydıyla mümkündür (bkz. `corporate_action_verifier`).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

XIST = "XIST"  # Borsa İstanbul pay piyasası MIC

# Olay türleri
SPLIT = "SPLIT"
REVERSE_SPLIT = "REVERSE_SPLIT"
BONUS = "BONUS"  # bedelsiz sermaye artırımı
RIGHTS = "RIGHTS"  # bedelli sermaye artırımı (rüçhan)
MERGER = "MERGER"
DEMERGER = "DEMERGER"
SYMBOL_CHANGE = "SYMBOL_CHANGE"
CASH_DIVIDEND = "CASH_DIVIDEND"

EVENT_TYPES = frozenset({SPLIT, REVERSE_SPLIT, BONUS, RIGHTS, MERGER, DEMERGER, SYMBOL_CHANGE, CASH_DIVIDEND})
# Adet/maliyet tabanını (veya ham fiyat ile maliyet karşılaştırmasını) değiştirebilen türler: doğrulama için
# coverage bu türlerin TAMAMINI kapsamalı. Nakit temettü fiyat bazlı maliyet modelinde adet/maliyet düzeltmesi
# gerektirmez; kaydedilir ama zorunlu kapsam değildir.
REQUIRED_EVENT_TYPES = frozenset({SPLIT, REVERSE_SPLIT, BONUS, RIGHTS, MERGER, DEMERGER, SYMBOL_CHANGE})

# Bildirim durumu
EVENT_ACTIVE = "ACTIVE"  # geçerli (düzeltme bildirimi de ACTIVE olur ve `original_event_id` taşır)
EVENT_SUPERSEDED = "SUPERSEDED"  # bir düzeltmeyle yerine yenisi geçti
EVENT_CANCELLED = "CANCELLED"  # iptal edildi
EVENT_STATUS_UNKNOWN = "UNKNOWN"  # kaynak düzeltme/iptal durumunu bildirmedi
EVENT_STATUSES = frozenset({EVENT_ACTIVE, EVENT_SUPERSEDED, EVENT_CANCELLED, EVENT_STATUS_UNKNOWN})

# Kimlik durumu
IDENTITY_VERIFIED = "VERIFIED"
IDENTITY_UNVERIFIED = "UNVERIFIED"

# Coverage tamlığı
COVERAGE_COMPLETE = "COMPLETE"
COVERAGE_PARTIAL = "PARTIAL"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def firestore_dict(self) -> dict:
        """Firestore'a güvenli gösterim: `date`/`datetime`/`frozenset` JSON uyumlu tiplere (ISO metni, liste)
        çevrilir. Düz `model_dump()` `date` içerdiği için Firestore'a YAZILAMAZ; bu modeller yazılırken bu kullanılır."""
        return self.model_dump(mode="json")


# Alış tarihi kaynağı
ACQUISITION_SOURCE_APP_RECORDED = "APP_RECORDED_TIMESTAMP"  # uygulamada kaydın oluşturulduğu an (işlem zamanı DEĞİL)
ACQUISITION_SOURCE_UNSPECIFIED = "UNSPECIFIED"  # eski kayıt / kaynak belirtilmemiş


class AcquisitionDateEvidence(_Frozen):
    """Elde tutma başlangıcının (en erken alışın) kanıtı. `verified=True` yalnız doğrulanmış bir işlem kaynağından
    (ör. aracı kurum işlem defteri) gelebilir; uygulamada butona basılan an, elle giriş ve eski kayıtlar DAİMA
    doğrulanmamıştır. Bugün hiçbir üretim yolu `verified=True` üretmez."""

    acquired_at: datetime
    verified: bool
    source: str
    reference: str | None = None
    recorded_at: datetime | None = None


class SourceProvenance(_Frozen):
    source: str  # kaynak tanımlayıcısı (ör. lisanslı veri sağlayıcı adı)
    source_reference: str | None = None  # URL veya kaynak içi referans
    retrieved_at: datetime
    source_revision: str | None = None  # kaynak veri sürümü/revizyonu
    provider_version: str  # ayrıştırıcı/sağlayıcı kod sürümü


class InstrumentIdentity(_Frozen):
    """Sembol → ISIN eşlemesi, geçerlilik aralığıyla (sembol yeniden kullanımı/değişimi nedeniyle tarihsel)."""

    symbol: str
    isin: str | None
    mic: str | None
    identity_status: str  # VERIFIED / UNVERIFIED
    valid_from: date | None = None
    valid_through: date | None = None  # None = hâlâ geçerli
    provenance: SourceProvenance | None = None


class SplitTerms(_Frozen):
    old_shares: str  # Decimal metni
    new_shares: str


class RightsTerms(_Frozen):
    rights_ratio: str  # eski pay başına yeni pay (Decimal metni)
    subscription_price: str
    reference_price: str | None = None  # teorik/referans fiyat (varsa)


class ConversionTerms(_Frozen):
    """Birleşme/bölünme: eski enstrümandan yeni enstrüman(lar)a dönüşüm."""

    old_isin: str
    new_isins: tuple[str, ...]
    conversion_ratio: str


class SymbolChangeTerms(_Frozen):
    old_symbol: str
    new_symbol: str
    isin_continuous: bool | None  # ISIN aynı kaldı mı (bilinmiyorsa None)


class CorporateActionEvent(_Frozen):
    event_id: str
    symbol: str
    isin: str | None
    mic: str | None
    event_type: str
    effective_date: date  # hak kullanım / ex tarihi (ham fiyatın etkilendiği ilk seans)
    announcement_id: str | None
    status: str  # ACTIVE / SUPERSEDED / CANCELLED / UNKNOWN
    original_event_id: str | None = None  # düzeltme/iptal bildirimi hangi bildirimi etkiliyor
    split: SplitTerms | None = None  # SPLIT / REVERSE_SPLIT / BONUS (eski/yeni pay ilişkisi)
    rights: RightsTerms | None = None
    conversion: ConversionTerms | None = None
    symbol_change: SymbolChangeTerms | None = None
    provenance: SourceProvenance


class CorporateActionCoverage(_Frozen):
    """Bir enstrüman için `checked_from..checked_through` (iki uç dahil) aralığının `covered_event_types` için
    eksiksiz kontrol edildiği kaydı. `completeness != COMPLETE` ise doğrulamada kullanılmaz."""

    isin: str
    symbol: str
    mic: str
    checked_from: date
    checked_through: date
    covered_event_types: frozenset[str]
    completeness: str  # COMPLETE / PARTIAL
    provenance: SourceProvenance


class CorporateActionSourceResult(_Frozen):
    """Sağlayıcı yanıtı: kimlik + coverage kayıtları + olaylar. Kaynak yoksa sağlayıcı `None` döner (bu bir
    'olay yok' beyanı DEĞİLDİR)."""

    identity: InstrumentIdentity | None
    coverage: tuple[CorporateActionCoverage, ...] = ()
    events: tuple[CorporateActionEvent, ...] = ()


class CorporateActionVerification(_Frozen):
    """Kanonik doğrulama sonucu — satış, açık pozisyon K/Z'si ve limit kontrolü aynı sonucu kullanır."""

    verified: bool
    reason: str
    symbol: str
    required_from: date
    required_through: date
    checked_from: date | None = None
    checked_through: date | None = None
    source: str | None = None
    instrument_identity_status: str | None = None
    isin: str | None = None
    events: tuple[CorporateActionEvent, ...] = ()  # aralıktaki geçerli olaylar (nakit temettü dahil)
    verifier_version: str

    def summary(self) -> dict:
        """API/işlem kaydı için kısa görünüm."""
        return {"verified": self.verified, "reason": self.reason,
                "required_from": self.required_from.isoformat(), "required_through": self.required_through.isoformat(),
                "checked_from": self.checked_from.isoformat() if self.checked_from else None,
                "checked_through": self.checked_through.isoformat() if self.checked_through else None,
                "source": self.source, "instrument_identity_status": self.instrument_identity_status,
                "event_types": sorted({e.event_type for e in self.events}),
                "verifier_version": self.verifier_version}


class TransactionBasisVerification(_Frozen):
    """Eski (değişmez) satış kaydı için sonradan yapılan, ekleme-yalnız doğrulama kaydı. Satış kaydının kendisi
    DEĞİŞTİRİLMEZ; okuma yolu en güncel geçerli kaydı "X doğrulamasına göre doğrulandı" olarak gösterir.

    Önerilen koleksiyon: `portfolio_transaction_verifications` (belge kimliği rastgele; güncelleme/silme yok)."""

    transaction_id: str
    user_id: str
    asset: str
    required_from: date
    required_through: date
    verified: bool
    reason: str
    checked_from: date | None
    checked_through: date | None
    source: str | None
    isin: str | None
    verifier_version: str
    verified_at: datetime
