"""HATA 12N3C1 — Technical V1 mutable oturum-çalıştırma (session-run)
saf operasyonel domain modeli.

Bu modül HİÇBİR I/O yapmaz -- Firestore/GCS/ağ/dosya sistemi erişimi
YOKTUR, `firebase_admin`/`google.cloud.firestore` import EDİLMEZ,
`SERVER_TIMESTAMP` sentinel'i buraya HİÇ GİRMEZ (bu, repository
katmanının -- `technical_v1_session_run_repository.py` -- münhasıran
kendi sorumluluğudur).

KRİTİK KAVRAM AYRIMI (HATA 12N3C-A/A2/A3'te kilitlendi, burada AÇIKÇA
tekrarlanır): `technical_v1_session_runs` KOLEKSİYONU BİLİMSEL KANIT
DEĞİLDİR. Bu, sıradan MUTABLE bir Firestore dokümanıdır -- create-only
sözleşme YOK, `record_content_sha256` YOK, ham hash/şema roundtrip
doğrulaması YOK. Eğer bu doküman şu bilimsel/değişmez depolarla
ÇELİŞİRSE:
  - `technical_v1_attempt_claims`/`technical_v1_attempt_results`
  - `technical_v1_evaluations`
  - `technical_v1_sessions`
DAİMA o değişmez depolar KAZANIR -- bu doküman herhangi bir zaman
yeniden üretilebilir/onarılabilir, KENDİSİ hiçbir zaman bir "gerçek"
kaynağı OLAMAZ. `technical_v1_session_runs` yalnızca UI/operatör
görünürlüğü/tanılama İÇİNDİR -- hiçbir bilimsel doğruluk-hassas karar
(finalizasyonu atla, manifest oluştur, vb.) bu dokümandan OKUNARAK
VERİLEMEZ.

`TechnicalV1SessionRunSnapshot` HER GEÇİŞTE (pass) baştan SIFIRDAN
yeniden inşa edilen TÜRETİLMİŞ bir anlık-görüntüdür -- 100 worker'dan
gelen ayrı append/remove/read-modify-write olaylarıyla ARTIMLI OLARAK
GÜNCELLENMEZ (bu, çoklu-yazarlı kayıp-güncelleme riskini yapısal olarak
ORTADAN KALDIRIR, bkz. HATA 12N3C-A2 section 1-3). Yalnızca SESSION
CONTROLLER/SERVICE (N3C3/N3C4, henüz yazılmadı) bu anlık-görüntüyü
inşa edip yazar -- tek-tek sembol worker'ları bu koleksiyona ASLA
DOĞRUDAN YAZMAZ (bu bir servis-katmanı sözleşmesidir, henüz bir IAM
garantisi DEĞİLDİR).

`retry_pending_evaluation_ids`, YALNIZCA mevcut geçişte finalizasyon
servisinin GERÇEKTEN `RETRYABLE` türünde bir sonuç döndürdüğü
evaluation_id'leri temsil eder -- "henüz finalizasyon hiç çalışmadı"
durumuyla ASLA KARIŞTIRILMAZ (bu ikisi, bir `FinalEvaluation`'ın
YOKLUĞU açısından ayırt edilemez; ayrım SADECE mevcut geçişin
TÜRETİLMİŞ tipli sonuçlarından gelir, bkz. HATA 12N3C-A3 section 10).

`provenance_blocked_evaluation_ids`, YALNIZCA depolama-katmanı
(repository-seviyesi) `ProvenanceConflictError` sonuçlarını temsil eder
(ör. N2B2 `get_verified()`'ın kendisinin fırlattığı) -- bir GÜVENİLİR
`FinalEvaluation`'ın KENDİ İÇERİĞİNDEKİ `evaluation_integrity_status ==
PROVENANCE_CONFLICT` alanıyla ASLA KARIŞTIRILMAZ (bu, tamamen FARKLI,
domain-seviyesi bir kavramdır -- bkz. HATA 12N3C-A2 section 6).
Manifest-seviyesi (session-seviyesi, evaluation_id'siz) bir provenance
çakışması bu N3C1 şemasında KASITLI OLARAK TEMSİL EDİLMEZ (N3C4'e
ertelenmiştir, bkz. HATA 12N3C-A3 section 8/9) -- sahte bir
evaluation_id İCAT EDİLMEZ.

`status` bu sınıfın bir constructor alanı DEĞİLDİR -- HER ZAMAN diğer
iki listeden TÜRETİLİR (`FinalEvaluation.record_content_sha256`/
`TechnicalV1SessionManifest.record_content_sha256` İLE AYNI "türetilmiş
alan, ASLA bağımsız olarak verilemez" deseni) -- bu, listelerle
ÇELİŞEN bir status'un yapısal olarak İMKANSIZ olmasını sağlar.

Bu modül frozen-100 evrenine karşı ÜYELİK doğrulaması YAPMAZ (frozen
sembol listesi bilgisine SAHİP DEĞİLDİR, bu KASITLIDIR) -- yalnızca
YAPISAL kimlik doğruluğunu (kanonik hex/sıralı/tekil/ayrık) doğrular.
Beklenen 100 kimliğe ÜYELİK doğrulaması, bu bilgiye zaten sahip olan
N3C3/N3C4 controller/servis katmanının SORUMLULUĞUDUR.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.research.evidence_identity import compute_session_id
from app.research.evidence_models import validate_sha256_hex

_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def _validate_canonical_date_str(value: str, field_name: str) -> None:
    """`evidence_identity.py`'nin AYNI iki-katmanlı sıkı doğrulama deseni
    (regex tam-eşleşme + self-round-trip) -- `session_manifest.py`'nin
    ZATEN yaptığı gibi burada da KENDİ private kopyası olarak tutulur
    (paylaşılan tek ilkel olan `evidence_identity.compute_session_id()`'nin
    aksine, bu küçük format kontrolü modüller arası paylaşılan bir public
    API DEĞİLDİR -- `evidence_identity._validate_canonical_date` özel/alt
    çizgili bir isimdir, modüller arası içe aktarılmaz)."""
    if not isinstance(value, str) or not _CANONICAL_DATE_RE.match(value):
        raise ValueError(f"{field_name} kanonik lehçede değil (YYYY-MM-DD bekleniyor): {value!r}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} geçersiz takvim tarihi: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} kanonik round-trip'i sağlamıyor: {value!r}")


def _validate_evaluation_id_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    """Her ID kanonik (64 küçük-harf hex) olmalı; tüm tuple ARTAN sırada
    VE tekil olmalı. HİÇBİR normalizasyon (sort/dedupe/lowercase/strip)
    YAPMAZ -- malformed/kanonik-olmayan girdi SESSİZCE onarılmaz,
    `ValueError` fırlatılır."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} sıralı bir koleksiyon (liste/tuple) olmalı, çıplak str/bytes DEĞİL: {values!r}")
    result = tuple(values)
    for value in result:
        validate_sha256_hex(value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} içinde tekrar eden evaluation_id var -- SESSİZCE dedupe edilmez: {result!r}")
    if list(result) != sorted(result):
        raise ValueError(f"{field_name} artan (sorted) sırada değil -- SESSİZCE yeniden sıralanmaz: {result!r}")
    return result


class SessionRunStatus(str, Enum):
    """HATA 12N3C-A2 section 9/29: KASITLI OLARAK YOK -- `COMPLETE`/
    `MANIFEST_CREATED` (değişmez manifest'in KENDİ varlığı zaten
    otoriterdir, ayrıca mutable bir ayna alan gerekmez) ve `RUNNING`
    (hiçbir aşağı akış mantığı "şu an aktif çalışıyor" ile "henüz
    tamamlanmadı" arasında ayrım YAPMAZ)."""

    INCOMPLETE = "INCOMPLETE"
    FINALIZATION_RETRY_PENDING = "FINALIZATION_RETRY_PENDING"
    PROVENANCE_BLOCKED = "PROVENANCE_BLOCKED"


_LOGICAL_DOCUMENT_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "session_id",
        "protocol_version",
        "T_session_date",
        "status",
        "retry_pending_evaluation_ids",
        "provenance_blocked_evaluation_ids",
    }
)


@dataclass(frozen=True)
class TechnicalV1SessionRunSnapshot:
    """HATA 12N3C-A3 section 2/4/7: mantıksal alanlar SADECE bunlardır --
    `updated_at` HİÇ YOKTUR (o, depolama-zamanı, repository-sahipli
    metadata'dır, bkz. modül docstring'i ve repository dosyası).
    `status` bir constructor parametresi DEĞİLDİR -- aşağıdaki `@property`
    üzerinden HER ZAMAN türetilir."""

    session_id: str
    protocol_version: str
    T_session_date: str
    retry_pending_evaluation_ids: tuple[str, ...]
    provenance_blocked_evaluation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_non_empty_str(self.protocol_version, "protocol_version")
        _validate_canonical_date_str(self.T_session_date, "T_session_date")

        expected_session_id = compute_session_id(self.protocol_version, self.T_session_date)
        if self.session_id != expected_session_id:
            raise ValueError(
                f"session_id ({self.session_id}) protocol_version/T_session_date'ten bağımsız olarak "
                f"yeniden hesaplanan ({expected_session_id}) ile eşleşmiyor -- çağırandan geldiği gibi "
                f"KÖRÜKÖRÜNE güvenilmez."
            )

        # HATA 12N3C-A3 section 7: derin değişmezlik -- girdi ne olursa
        # olsun (liste/tuple), SAVUNMACI OLARAK doğrulanmış bir `tuple`'a
        # dönüştürülüp saklanır; çağıranın ORİJİNAL listesi sonradan
        # mutate edilse bile bu nesneyi ETKİLEMEZ (tuple zaten değişmez,
        # ayrıca `object.__setattr__` yalnızca BU alanı, DOĞRULANMIŞ yeni
        # değerle, bir KEZ ilklendirir).
        retry_pending = _validate_evaluation_id_tuple(
            self.retry_pending_evaluation_ids, "retry_pending_evaluation_ids"
        )
        provenance_blocked = _validate_evaluation_id_tuple(
            self.provenance_blocked_evaluation_ids, "provenance_blocked_evaluation_ids"
        )
        object.__setattr__(self, "retry_pending_evaluation_ids", retry_pending)
        object.__setattr__(self, "provenance_blocked_evaluation_ids", provenance_blocked)

        # HATA 12N3C-A3 section 6: bir evaluation AYNI ANDA hem RETRYABLE
        # hem PROVENANCE_BLOCKED OLAMAZ.
        overlap = set(retry_pending) & set(provenance_blocked)
        if overlap:
            raise ValueError(
                f"retry_pending_evaluation_ids ve provenance_blocked_evaluation_ids AYRIK olmalı -- "
                f"örtüşen ID'ler: {sorted(overlap)!r}"
            )

    @property
    def status(self) -> SessionRunStatus:
        """HATA 12N3C-A3 section 7 -- TAM, koşulsuz bir fonksiyon: bu
        yüzden listelerle ÇELİŞEN bir status yapısal olarak İMKANSIZDIR
        (ayrıca doğrulanan/reddedilen bir durum DEĞİL, çünkü bağımsız
        olarak hiç VERİLEMEZ)."""
        if self.provenance_blocked_evaluation_ids:
            return SessionRunStatus.PROVENANCE_BLOCKED
        if self.retry_pending_evaluation_ids:
            return SessionRunStatus.FINALIZATION_RETRY_PENDING
        return SessionRunStatus.INCOMPLETE

    def to_document_fields(self) -> dict:
        """SADECE mantıksal alanlar -- `updated_at` HİÇ YOK (bu,
        repository'nin `SERVER_TIMESTAMP`'i AYRICA enjekte ettiği bir
        alandır). ID tuple'ları düz, AYRIK (detached) `list` nesneleri
        olarak yayınlanır -- döndürülen sözlüğü mutate etmek bu nesneyi
        ETKİLEMEZ (bir `tuple`'dan `list(...)` HER ZAMAN yeni bir nesne
        üretir)."""
        return {
            "session_id": self.session_id,
            "protocol_version": self.protocol_version,
            "T_session_date": self.T_session_date,
            "status": self.status.value,
            "retry_pending_evaluation_ids": list(self.retry_pending_evaluation_ids),
            "provenance_blocked_evaluation_ids": list(self.provenance_blocked_evaluation_ids),
        }

    @classmethod
    def from_document_fields(cls, data: dict) -> TechnicalV1SessionRunSnapshot:
        """`to_document_fields()`'ın TERSİ -- HATA 12N3C-A3 section 13/14.

        Katı alan-kümesi doğrulaması: TAM OLARAK `_LOGICAL_DOCUMENT_
        FIELD_KEYS` beklenir -- bilinmeyen/eksik bir anahtar SESSİZCE
        onarılmaz, `ValueError` fırlatılır.

        `status` constructor'a HİÇ VERİLMEZ -- önce diğer beş alandan
        snapshot yeniden kurulur, SONRA saklanan ham `status` string'inin
        GEÇERLİ bir `SessionRunStatus` değeri olduğu VE yeniden kurulan
        snapshot'ın KENDİ türetilmiş `status`'uyla TAM eşleştiği
        doğrulanır. Uyuşmazlık -- ör. saklanan `status="INCOMPLETE"` ama
        `retry_pending_evaluation_ids` dolu -- SESSİZCE onarılmaz,
        reddedilir."""
        actual_keys = set(data.keys())
        if actual_keys != _LOGICAL_DOCUMENT_FIELD_KEYS:
            missing = _LOGICAL_DOCUMENT_FIELD_KEYS - actual_keys
            unexpected = actual_keys - _LOGICAL_DOCUMENT_FIELD_KEYS
            raise ValueError(
                f"beklenmeyen/eksik mantıksal alan kümesi -- eksik={sorted(missing)!r} "
                f"beklenmeyen={sorted(unexpected)!r}"
            )

        snapshot = cls(
            session_id=data["session_id"],
            protocol_version=data["protocol_version"],
            T_session_date=data["T_session_date"],
            retry_pending_evaluation_ids=tuple(data["retry_pending_evaluation_ids"]),
            provenance_blocked_evaluation_ids=tuple(data["provenance_blocked_evaluation_ids"]),
        )

        raw_status = data["status"]
        try:
            SessionRunStatus(raw_status)
        except ValueError as exc:
            raise ValueError(f"status geçerli bir SessionRunStatus değeri değil: {raw_status!r}") from exc
        if raw_status != snapshot.status.value:
            raise ValueError(
                f"saklanan status ({raw_status!r}), ID listelerinden bağımsız olarak türetilen "
                f"({snapshot.status.value!r}) ile eşleşmiyor -- operasyonel durum SESSİZCE onarılmaz."
            )

        return snapshot
