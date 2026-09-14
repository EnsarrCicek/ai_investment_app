"""HATA 12N2B1 — Technical V1 immutable final-evaluation seçim katmanının
saf veri modelleri (enum'lar, girdi zarfları, `AttemptSummary`,
`FinalEvaluation`).

Bu modül HİÇBİR I/O yapmaz (Firestore/GCS/ağ erişimi YOK) -- yalnızca
zaten materyalize edilmiş, çağıran tarafından verilen ham girdi
nesnelerini temsil eder. `final_evaluation_selector.py`'nin saf seçim
mantığı bu modeller üzerinden çalışır.

Kilitli BOUNDED APPEND-ONLY tehdit modeli (HATA 12N2B-A4'te kilitlendi,
BURADA da açıkça belgelenir): bu katman, Technical V1 uygulamasının
kendi kodunun bir attempt claim/result dokümanını ASLA silmediği/
güncellemediği varsayımı ÜZERİNE kuruludur (confirmed by source
inspection, HATA 12N2B-A4). Ayrıcalıklı bir yöneticinin (privileged
admin) Firestore'dan TAMAMEN silinmiş, geçmişte var olmuş bir dokümanı
BU KATMAN yeniden inşa edemez/tespit edemez -- bu, V1 için AÇIKÇA kabul
edilmiş bir kapsam sınırıdır (forensic guarantee DEĞİL). Temiz bir
"claim var + result yok" durumu, bu model altında GÜVENİLİR bir "hiç
üretilmedi" anlamına gelir -- "üretildi ama sonra silindi" İHTİMALİ BU
KATMANIN KAPSAMI DIŞINDADIR. Ayrı bir yayın-işareti (publication
marker)/harici denetim çıpası mimarisi KASITLI OLARAK EKLENMEMİŞTİR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from app.research.attempt_models import ALLOWED_ATTEMPT_NUMBERS as _ALLOWED_ATTEMPT_NUMBERS
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_evaluation_id
from app.research.evidence_models import EvidenceObjectKind, EvidenceObjectRef, validate_sha256_hex


class FinalizationRetryableError(RuntimeError):
    """Kalıcı olmayan/bilinmeyen bir depolama-katmanı hatası (ör. GCS'in
    plain `ObjectStoreError`'ı -- geçici bir ağ kesintisi/servis arızası)
    NEDENIYLE bu finalizasyon çalıştırması TAMAMLANAMADI. Bu, kalıcı bir
    `FinalEvaluation` SONUCU DEĞİLDİR -- çağıran taraf hiçbir final kaydı
    OLUŞTURMAMALI/PERSIST ETMEMELİDİR, yalnızca daha sonra TEKRAR
    denemelidir. Geçici bir depolama arızasının kalıcı bir prospective
    veri kümesi kararını YANLIŞLIKLA/KALICI OLARAK değiştirmesini önler
    (HATA 12N2B-A2 section 5)."""


def _validate_attempt_number_strict(attempt_number: int, field_name: str = "attempt_number") -> None:
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number not in _ALLOWED_ATTEMPT_NUMBERS
    ):
        raise ValueError(f"{field_name} yalnızca {_ALLOWED_ATTEMPT_NUMBERS} (int) olabilir: {attempt_number!r}")


def _validate_non_empty_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} boş olmayan bir string olmalı: {value!r}")


def _validate_utc_aware(value: datetime, field_name: str) -> None:
    """Naive (tz'siz) bir `datetime` KESİNLİKLE REDDEDİLİR -- SESSİZCE UTC
    varsayılmaz. Yalnızca UTC ofseti TAM OLARAK sıfır olan tz-aware
    değerler kabul edilir (`+03:00` gibi başka bir ofsetle gelen bir
    değer de reddedilir -- çağıran taraf ÖNCEDEN UTC'ye normalize etmekle
    yükümlüdür, bu katman SESSİZCE dönüştürme YAPMAZ)."""
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} bir datetime olmalı: {value!r}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} tz-aware değil (naive datetime kabul edilmez): {value!r}")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} UTC ofsetinde değil (ofset={value.utcoffset()}): {value!r}")


_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_canonical_date_str(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _CANONICAL_DATE_RE.match(value):
        raise ValueError(f"{field_name} kanonik lehçede değil (YYYY-MM-DD bekleniyor): {value!r}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} geçersiz takvim tarihi: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} kanonik round-trip'i sağlamıyor: {value!r}")


# ---------------------------------------------------------------------------
# Ham girdi zarfları (PersistedAttemptClaim / PersistedAttemptResultDocument)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersistedAttemptClaim:
    """HATA 12N2B1 section 4: minimal, ham girdi zarfı -- `document_fields`
    Firestore'dan (veya eşdeğer bir sahteden) okunmuş HAM sözlüktür,
    ÖNCEDEN doğrulanmış bir `AttemptClaim` NESNESİ DEĞİLDİR. Seçici,
    doküman ID'sinin doğru olmasına GÜVENMEDEN, İÇERİĞİN kimlik
    alanlarını BAĞIMSIZ OLARAK doğrular."""

    attempt_number: int
    attempt_id: str
    document_fields: dict

    def __post_init__(self) -> None:
        _validate_attempt_number_strict(self.attempt_number)
        _validate_non_empty_str(self.attempt_id, "attempt_id")
        if not isinstance(self.document_fields, dict):
            raise ValueError(f"document_fields bir dict olmalı: {self.document_fields!r}")


@dataclass(frozen=True)
class PersistedAttemptResultDocument:
    """HATA 12N2B1 section 5: `document_fields` KASITLI OLARAK ham bir
    dict'tir -- önceden doğrulanmış bir `AttemptResult` NESNESİ KABUL
    EDİLMEZ, aksi halde tampered/semantic-invalid dokümanlar seçiciye HİÇ
    ULAŞAMAZDI (`AttemptResult.__post_init__` zaten kendi kendine
    fırlatırdı). `create_time`, section 6: Firestore depolama metadata'sı
    -- tz-aware UTC olmalı, `AttemptResult`'ın bir ALANI DEĞİLDİR, final
    kayıt içeriğine ASLA kopyalanmaz, `AttemptSummary`'ye ASLA girmez."""

    attempt_number: int
    attempt_id: str
    document_fields: dict
    create_time: datetime

    def __post_init__(self) -> None:
        _validate_attempt_number_strict(self.attempt_number)
        _validate_non_empty_str(self.attempt_id, "attempt_id")
        if not isinstance(self.document_fields, dict):
            raise ValueError(f"document_fields bir dict olmalı: {self.document_fields!r}")
        _validate_utc_aware(self.create_time, "create_time")


# ---------------------------------------------------------------------------
# Kapalı domain enum'ları (HATA 12N2B-A/A2/A3/A4'te kilitlenen kontrat)
# ---------------------------------------------------------------------------


class AttemptRequirementState(str, Enum):
    REQUIRED = "REQUIRED"
    NOT_REQUIRED_FIRST_VALID = "NOT_REQUIRED_FIRST_VALID"
    INDETERMINATE_PROVENANCE = "INDETERMINATE_PROVENANCE"


class ClaimPresence(str, Enum):
    CLAIMED = "CLAIMED"
    MISSING = "MISSING"


class ResultState(str, Enum):
    NO_RESULT = "NO_RESULT"
    TERMINAL_RESULT = "TERMINAL_RESULT"
    INTEGRITY_INVALID = "INTEGRITY_INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VerificationState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    VERIFIED = "VERIFIED"
    CLAIM_RELATION_INVALID = "CLAIM_RELATION_INVALID"
    RESULT_CONTENT_HASH_INVALID = "RESULT_CONTENT_HASH_INVALID"
    RESULT_SEMANTIC_INVALID = "RESULT_SEMANTIC_INVALID"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"


class CaptureStatus(str, Enum):
    VALID_CAPTURE_AVAILABLE = "VALID_CAPTURE_AVAILABLE"
    NO_VALID_CAPTURE_AVAILABLE = "NO_VALID_CAPTURE_AVAILABLE"
    INFRASTRUCTURE_BLOCKED = "INFRASTRUCTURE_BLOCKED"


class EvaluationIntegrityStatus(str, Enum):
    CLEAN = "CLEAN"
    AUDIT_INCOMPLETE = "AUDIT_INCOMPLETE"
    EVIDENCE_INTEGRITY_FAILURE = "EVIDENCE_INTEGRITY_FAILURE"
    PROVENANCE_CONFLICT = "PROVENANCE_CONFLICT"


class OrchestrationAnomalyCode(str, Enum):
    """HATA 12N2B1 section 37: deterministik/kapalı bir temsil -- serbest
    metin birincil kimlik OLARAK KULLANILMAZ."""

    ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED = "ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED"


# ---------------------------------------------------------------------------
# Finalization bağlamı (bağımsız olarak güvenilen kimlik/zamanlama gerçekleri)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinalizationContext:
    """HATA 12N2B1 section 7/8: seçicinin ihtiyaç duyduğu, BAĞIMSIZ OLARAK
    güvenilen (dondurulmuş protokol/metodoloji dosyalarından/sabit
    kod'dan gelen, herhangi bir Firestore doküman gövdesinden OKUNMAYAN)
    kimlik ve zamanlama gerçekleri. `evaluation_id` çağıran tarafından
    verilir AMA doğrudan güvenilmez -- `compute_evaluation_id(...)` ile
    BAĞIMSIZ OLARAK yeniden hesaplanıp karşılaştırılır."""

    evaluation_id: str
    protocol_version: str
    protocol_sha256: str
    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str
    T_session_date: str
    symbol: str
    E1_date: str
    attempt2_decision_time_utc: datetime
    formal_cutoff_utc: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "protocol_version",
            "protocol_sha256",
            "methodology_git_commit",
            "freeze_manifest_sha256",
            "engine_version",
            "scoring_config_hash",
            "symbol",
        ):
            _validate_non_empty_str(getattr(self, field_name), field_name)
        _validate_canonical_date_str(self.T_session_date, "T_session_date")
        _validate_canonical_date_str(self.E1_date, "E1_date")
        _validate_utc_aware(self.attempt2_decision_time_utc, "attempt2_decision_time_utc")
        _validate_utc_aware(self.formal_cutoff_utc, "formal_cutoff_utc")
        if not (self.attempt2_decision_time_utc < self.formal_cutoff_utc):
            raise ValueError(
                "attempt2_decision_time_utc, formal_cutoff_utc'den KESİN OLARAK önce olmalı "
                f"({self.attempt2_decision_time_utc!r} >= {self.formal_cutoff_utc!r})"
            )

        # HATA 12N2B1 section 7: evaluation_id ASLA çağırandan geldiği gibi
        # güvenilmez -- bağımsız olarak yeniden hesaplanır.
        expected_evaluation_id = compute_evaluation_id(self.protocol_version, self.T_session_date, self.symbol)
        validate_sha256_hex(self.evaluation_id)
        if self.evaluation_id != expected_evaluation_id:
            raise ValueError(
                f"Sağlanan evaluation_id ({self.evaluation_id}) bağımsız olarak yeniden hesaplanan "
                f"({expected_evaluation_id}) ile eşleşmiyor -- güvenilmedi."
            )

    def formal_cutoff_timestamp_str(self) -> str:
        """Kanonik, UTF-8/yerel-ayardan bağımsız ISO-8601 temsili --
        `formal_cutoff_utc`'nin ofseti `__post_init__`'te zaten TAM
        SIFIR olarak doğrulandığından, `.isoformat()` hangi UTC-temsilci
        `tzinfo` nesnesi kullanılırsa kullanılsın (`timezone.utc` /
        `ZoneInfo('UTC')`) DETERMİNİSTİK, aynı string'i üretir."""
        return self.formal_cutoff_utc.isoformat()


# ---------------------------------------------------------------------------
# AttemptSummary (HATA 12N2B1 section 10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptSummary:
    """KASITLI OLARAK YOK: tam `AttemptResult`, object ref'ler, girdi
    hash'leri, `create_time`, client zaman damgaları, provider metadata --
    bunlar burada DEĞİL, gerekiyorsa (seçilen aday için) `FinalEvaluation`
    seviyesinde AYRI alanlarda taşınır."""

    attempt_number: int
    attempt_id: str

    requirement_state: AttemptRequirementState
    claim_presence: ClaimPresence
    result_state: ResultState

    result_classification: str | None
    native_reason_code: str | None

    verification_state: VerificationState
    verification_reason_code: str | None

    def to_content_fields(self) -> dict:
        return {
            "attempt_number": self.attempt_number,
            "attempt_id": self.attempt_id,
            "requirement_state": self.requirement_state.value,
            "claim_presence": self.claim_presence.value,
            "result_state": self.result_state.value,
            "result_classification": self.result_classification,
            "native_reason_code": self.native_reason_code,
            "verification_state": self.verification_state.value,
            "verification_reason_code": self.verification_reason_code,
        }

    @classmethod
    def from_content_fields(cls, data: dict) -> AttemptSummary:
        """`to_content_fields()`'ın TERSİ -- HATA 12N2B2 section 13.
        Bilinmeyen/geçersiz bir enum string'i burada doğrudan `ValueError`
        fırlatır (ör. `AttemptRequirementState("BOZUK")`) -- çağıran
        repository katmanı bunu KENDİ `ProvenanceConflictError`'ına
        çevirir, burada SESSİZCE onarılmaz/normalize edilmez."""
        return cls(
            attempt_number=data["attempt_number"],
            attempt_id=data["attempt_id"],
            requirement_state=AttemptRequirementState(data["requirement_state"]),
            claim_presence=ClaimPresence(data["claim_presence"]),
            result_state=ResultState(data["result_state"]),
            result_classification=data.get("result_classification"),
            native_reason_code=data.get("native_reason_code"),
            verification_state=VerificationState(data["verification_state"]),
            verification_reason_code=data.get("verification_reason_code"),
        )


# ---------------------------------------------------------------------------
# FinalEvaluation (HATA 12N2B1 section 38)
# ---------------------------------------------------------------------------


def _object_ref_to_content_fields(ref: EvidenceObjectRef | None) -> dict | None:
    if ref is None:
        return None
    return {
        "kind": ref.kind.value,
        "sha256": ref.sha256,
        "object_name": ref.object_name,
        "size_bytes": ref.size_bytes,
        "bucket_name": ref.bucket_name,
    }


def _object_ref_from_content_fields(data: dict | None) -> EvidenceObjectRef | None:
    if data is None:
        return None
    return EvidenceObjectRef(
        kind=EvidenceObjectKind(data["kind"]),
        sha256=data["sha256"],
        object_name=data["object_name"],
        size_bytes=data["size_bytes"],
        bucket_name=data.get("bucket_name"),
    )


@dataclass(frozen=True)
class FinalEvaluation:
    """HATA 12N2B1 section 38: KASITLI OLARAK YOK -- gelecekteki sonuç
    (E5/E10/E20), performans/hit-rate/getiri alanı, client `finalized_at`,
    kazanan attempt'in `create_time`'ı (bkz. section 27 -- Seçenek A
    kilitlendi: bu her zaman `selected_attempt_id` üzerinden ayrı bir
    okuma ile erişilir, ASLA bu dokümana KOPYALANMAZ), bu final kaydın
    KENDİ Firestore `create_time`'ı (o, N2B2'nin depolama metadata'sıdır,
    bu dokümanın İÇERİĞİ değildir)."""

    evaluation_id: str
    protocol_version: str
    T_session_date: str
    symbol: str

    protocol_sha256: str
    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str

    E1_date: str
    formal_cutoff_timestamp: str

    capture_status: CaptureStatus
    evaluation_integrity_status: EvaluationIntegrityStatus

    technical_observation_eligible: bool
    selected_evidence_integrity_complete: bool | None
    attempt_history_complete: bool

    selected_attempt_id: str | None

    attempt_1_summary: AttemptSummary
    attempt_2_summary: AttemptSummary

    orchestration_anomaly_codes: frozenset[OrchestrationAnomalyCode] = field(default_factory=frozenset)

    selected_asset_input_sha256: str | None = None
    selected_benchmark_input_sha256: str | None = None
    selected_input_snapshot_sha256: str | None = None
    selected_technical_output_sha256: str | None = None

    selected_asset_object_ref: EvidenceObjectRef | None = None
    selected_benchmark_object_ref: EvidenceObjectRef | None = None
    selected_technical_output_object_ref: EvidenceObjectRef | None = None

    def to_content_fields(self) -> dict:
        """`record_content_sha256` HARİÇ tüm alanlar -- bu dict doğrudan
        `canonical_hash.content_sha256()`'a verilir. Anomaly kod listesi
        HER ZAMAN sıralı (`sorted`) bir liste olarak yayınlanır -- bir
        `frozenset`'in kendi iterasyon sırası deterministik DEĞİLDİR
        (section 41: "No unordered set serialization")."""
        return {
            "evaluation_id": self.evaluation_id,
            "protocol_version": self.protocol_version,
            "T_session_date": self.T_session_date,
            "symbol": self.symbol,
            "protocol_sha256": self.protocol_sha256,
            "methodology_git_commit": self.methodology_git_commit,
            "freeze_manifest_sha256": self.freeze_manifest_sha256,
            "engine_version": self.engine_version,
            "scoring_config_hash": self.scoring_config_hash,
            "E1_date": self.E1_date,
            "formal_cutoff_timestamp": self.formal_cutoff_timestamp,
            "capture_status": self.capture_status.value,
            "evaluation_integrity_status": self.evaluation_integrity_status.value,
            "technical_observation_eligible": self.technical_observation_eligible,
            "selected_evidence_integrity_complete": self.selected_evidence_integrity_complete,
            "attempt_history_complete": self.attempt_history_complete,
            "selected_attempt_id": self.selected_attempt_id,
            "attempt_1_summary": self.attempt_1_summary.to_content_fields(),
            "attempt_2_summary": self.attempt_2_summary.to_content_fields(),
            "orchestration_anomaly_codes": sorted(code.value for code in self.orchestration_anomaly_codes),
            "selected_asset_input_sha256": self.selected_asset_input_sha256,
            "selected_benchmark_input_sha256": self.selected_benchmark_input_sha256,
            "selected_input_snapshot_sha256": self.selected_input_snapshot_sha256,
            "selected_technical_output_sha256": self.selected_technical_output_sha256,
            "selected_asset_object_ref": _object_ref_to_content_fields(self.selected_asset_object_ref),
            "selected_benchmark_object_ref": _object_ref_to_content_fields(self.selected_benchmark_object_ref),
            "selected_technical_output_object_ref": _object_ref_to_content_fields(
                self.selected_technical_output_object_ref
            ),
        }

    @property
    def record_content_sha256(self) -> str:
        # HATA 12N2B1 section 40: `record_content_sha256` bu sınıfın bir
        # ALANI DEĞİLDİR -- HER ZAMAN diğer tüm alanlardan TÜRETİLİR, bu
        # yüzden kendi kendini içerme sorusu yapısal olarak İMKANSIZDIR.
        return content_sha256(self.to_content_fields())

    def to_document_fields(self) -> dict:
        return {**self.to_content_fields(), "record_content_sha256": self.record_content_sha256}

    @classmethod
    def from_document_fields(cls, data: dict) -> FinalEvaluation:
        """`to_document_fields()`'ın TERSİ -- HATA 12N2B2 section 13.
        `record_content_sha256` alanı KASITLI OLARAK okunmaz/kullanılmaz
        (constructor'ın bir parametresi DEĞİLDİR, her zaman `content_
        sha256` property'si üzerinden yeniden TÜRETİLİR); çağıran taraf
        (repository) tamper/tutarlılık kontrolü için `evaluation.record_
        content_sha256`'yı dokümanın saklanan `record_content_sha256`
        alanıyla AYRICA, bu fonksiyon ÇAĞRILMADAN ÖNCE karşılaştırmalıdır
        -- bu metod SEMANTİK yeniden kuruluşu yapar, ham içerik-hash
        doğrulamasını YAPMAZ (o, repository'nin sorumluluğudur).

        Bilinmeyen/geçersiz bir enum string'i veya eksik bir anahtar
        burada doğrudan `ValueError`/`KeyError` fırlatır -- SESSİZCE
        onarılmaz/normalize edilmez; çağıran repository bunu KENDİ
        `ProvenanceConflictError`'ına çevirir."""
        return cls(
            evaluation_id=data["evaluation_id"],
            protocol_version=data["protocol_version"],
            T_session_date=data["T_session_date"],
            symbol=data["symbol"],
            protocol_sha256=data["protocol_sha256"],
            methodology_git_commit=data["methodology_git_commit"],
            freeze_manifest_sha256=data["freeze_manifest_sha256"],
            engine_version=data["engine_version"],
            scoring_config_hash=data["scoring_config_hash"],
            E1_date=data["E1_date"],
            formal_cutoff_timestamp=data["formal_cutoff_timestamp"],
            capture_status=CaptureStatus(data["capture_status"]),
            evaluation_integrity_status=EvaluationIntegrityStatus(data["evaluation_integrity_status"]),
            technical_observation_eligible=data["technical_observation_eligible"],
            selected_evidence_integrity_complete=data.get("selected_evidence_integrity_complete"),
            attempt_history_complete=data["attempt_history_complete"],
            selected_attempt_id=data.get("selected_attempt_id"),
            attempt_1_summary=AttemptSummary.from_content_fields(data["attempt_1_summary"]),
            attempt_2_summary=AttemptSummary.from_content_fields(data["attempt_2_summary"]),
            orchestration_anomaly_codes=frozenset(
                OrchestrationAnomalyCode(code) for code in data.get("orchestration_anomaly_codes", [])
            ),
            selected_asset_input_sha256=data.get("selected_asset_input_sha256"),
            selected_benchmark_input_sha256=data.get("selected_benchmark_input_sha256"),
            selected_input_snapshot_sha256=data.get("selected_input_snapshot_sha256"),
            selected_technical_output_sha256=data.get("selected_technical_output_sha256"),
            selected_asset_object_ref=_object_ref_from_content_fields(data.get("selected_asset_object_ref")),
            selected_benchmark_object_ref=_object_ref_from_content_fields(data.get("selected_benchmark_object_ref")),
            selected_technical_output_object_ref=_object_ref_from_content_fields(
                data.get("selected_technical_output_object_ref")
            ),
        )
