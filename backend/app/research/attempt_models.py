"""HATA 12N2A — Technical V1 immutable attempt-claim/attempt-result saf veri
modelleri.

Bu modül HİÇBİR I/O yapmaz (Firestore/GCS/ağ erişimi YOK) -- yalnızca
`app/repositories/technical_v1_attempt_repository.py`'nin okuyup yazacağı
değişmez (frozen) veri yapılarını, kapalı enum'larını ve bunlara özgü
doğrulama/içerik-hash mantığını içerir.

Kilitli kavram ayrımı (HATA 12N2-A audit'i, CLAIM-ONCE modeli):
  - `AttemptClaim`: "bir worker'ın bu mantıksal denemeyi (attempt) YÜRÜTMESİNE
    İZİN VERİLDİ" -- MUTABLE DEĞİL, create-only, SONSUZA KADAR değişmez.
    Sonuç/skor/durum alanı TAŞIMAZ -- yalnızca "kim/hangi mantıksal deneme"
    bilgisini taşır. Lease/heartbeat/generation/claim_token YOKTUR (HATA
    12N2-A: bu proje için gerekli değil, bkz. o audit raporu).
  - `AttemptResult`: worker'ın GERÇEKTEN ürettiği, terminal (nihai) ve
    değişmez kanıt -- yalnızca claim VARSA yayınlanabilir (bkz. repository).
    `claim var + result yok` GEÇERLİ, kalıcı bir depolama durumudur
    (AUDIT_INCOMPLETE aday durumu) -- N2A'da hiçbir temizlik/timeout süreci
    YOKTUR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.research.evidence_identity import ALLOWED_ATTEMPT_NUMBERS
from app.research.evidence_models import (
    EvidenceIntegrityError,
    EvidenceObjectKind,
    EvidenceObjectRef,
    validate_sha256_hex,
)
from app.research.evidence_serialization import input_snapshot_sha256_from_hashes


class AttemptClaimMissingError(ValueError):
    """Bir attempt-result YAYINLAMA girişimi, kendisine karşılık gelen
    immutable claim doküman'ı OLMADAN yapıldı -- yürütme sözleşmesi ihlal
    edildi (HATA 12N2A: önce claim, sonra iş, sonra sonuç yayınlama).
    Result yayınlama KENDİ İÇİNDE sessizce bir claim OLUŞTURMAZ."""


class AttemptResultClassification(str, Enum):
    """Bir DENEMENİN (attempt) ürettiği terminal sonucun kapalı sınıflandırması
    -- HATA 12O/12P'de kilitlenen final-evaluation `capture_status`/
    `observation_status` ayrımının ATTEMPT SEVİYESİNDEKİ dar karşılığıdır.
    Aşırı genişletilmiş bir taksonomi DEĞİLDİR -- ayrıntılı metodoloji/veri
    nedeni `native_reason_code`'da taşınır."""

    VALID_CANDIDATE = "VALID_CANDIDATE"
    EXCLUSION = "EXCLUSION"
    FAILED = "FAILED"
    BLOCKED_CONFIG_DRIFT = "BLOCKED_CONFIG_DRIFT"
    BLOCKED_METHODOLOGY_DRIFT = "BLOCKED_METHODOLOGY_DRIFT"
    BLOCKED_RUNTIME_IDENTITY = "BLOCKED_RUNTIME_IDENTITY"
    BLOCKED_UNIVERSE_OR_ASSET_CONFIG = "BLOCKED_UNIVERSE_OR_ASSET_CONFIG"


class GateCheckResult(str, Enum):
    """Config/metodoloji/runtime/universe ön-uçuş (pre-flight) kapılarının
    HER BİRİ için tekdüze (uniform), iki-değerli sonuç -- dört ayrı, farklı
    isimlendirilmiş enum YERİNE tek bir paylaşılan tip (HATA 12N2A section
    10'daki dört gate alanının hepsi AYNI semantiği taşır: bu kapı geçti mi)."""

    PASS = "PASS"
    FAIL = "FAIL"


class ClaimOutcome(str, Enum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"


class PublishOutcome(str, Enum):
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class ProviderFetchMetadata:
    """HATA 12N2A section 12 -- kimlik-bilgisi/gizli veri TAŞIMAZ (auth
    header/cookie/API key/token/ham HTTP dump YOK). Zaman damgaları ISO-8601
    string olarak taşınır (çıplak `datetime` nesnesi DEĞİL) -- bu, bu
    metadata'nın doğrudan JSON-güvenli olmasını, dolayısıyla içerik-hash'e
    ek bir dönüştürme adımı olmadan girebilmesini sağlar."""

    provider_name: str
    requested_symbol: str
    requested_period_or_range: str
    fetch_started_at: str | None
    fetch_completed_at: str | None
    provider_result_status: str
    provider_error_category: str | None = None

    def to_content_fields(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "requested_symbol": self.requested_symbol,
            "requested_period_or_range": self.requested_period_or_range,
            "fetch_started_at": self.fetch_started_at,
            "fetch_completed_at": self.fetch_completed_at,
            "provider_result_status": self.provider_result_status,
            "provider_error_category": self.provider_error_category,
        }


def _validate_attempt_number(attempt_number: int) -> None:
    """`bool`, Python'da `int`'in bir alt sınıfıdır ve `1.0 == 1` sayısal
    eşitliği `in` kontrolünü SESSİZCE atlatabilir -- kimlik/model alanı
    kesin TİP eşleşmesi ister (bkz. `evidence_identity.compute_attempt_
    id()`'deki AYNI düzeltme)."""
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number not in ALLOWED_ATTEMPT_NUMBERS
    ):
        raise EvidenceIntegrityError(f"attempt_number geçersiz: {attempt_number!r}")


def _object_ref_to_content_fields(ref: EvidenceObjectRef) -> dict:
    return {
        "kind": ref.kind.value,
        "sha256": ref.sha256,
        "object_name": ref.object_name,
        "size_bytes": ref.size_bytes,
        "bucket_name": ref.bucket_name,
    }


def _validate_object_ref_consistency(
    kind: EvidenceObjectKind, expected_hash: str | None, ref: EvidenceObjectRef | None
) -> None:
    """HATA 12N2A section 13: bir hash `None` ise karşılık gelen ref de
    `None` OLMALI; hash mevcutsa ref MEVCUT olmalı VE `kind`/`sha256`
    alanları bu hash ile TAM eşleşmeli."""
    if expected_hash is None:
        if ref is not None:
            raise EvidenceIntegrityError(
                f"{kind.value}: hash None ama object ref sağlanmış (tutarsız model kurulumu)"
            )
        return
    validate_sha256_hex(expected_hash)
    if ref is None:
        raise EvidenceIntegrityError(f"{kind.value}: hash mevcut ({expected_hash}) ama object ref eksik")
    if ref.kind != kind:
        raise EvidenceIntegrityError(f"{kind.value}: object ref kind uyuşmuyor ({ref.kind.value})")
    if ref.sha256 != expected_hash:
        raise EvidenceIntegrityError(
            f"{kind.value}: object ref sha256 ({ref.sha256}) beklenen hash ({expected_hash}) ile eşleşmiyor"
        )


@dataclass(frozen=True)
class AttemptClaim:
    """HATA 12N2A section 6: minimal, SONSUZA KADAR create-only immutable
    operasyonel claim. Sonuç/durum/lease/heartbeat/generation/claim_token
    alanı KASITLI OLARAK YOKTUR -- tamamlanma durumu SADECE ayrı bir
    `AttemptResult` dokümanının VAR OLUP OLMADIĞIYLA temsil edilir.

    `claimed_at` KASITLI OLARAK BURADA YOKTUR (section 6: "preferably
    OMITTED unless there is a concrete operational need") -- Firestore'un
    kendi `DocumentSnapshot.create_time`'ı bu claim'in ne zaman durably
    oluşturulduğunu cevaplamak için yeterlidir, ayrı bir client-taraflı
    alan gerektirmez.
    """

    attempt_id: str
    evaluation_id: str
    attempt_number: int
    protocol_version: str
    T_session_date: str
    symbol: str
    claimed_by_runtime: str

    def __post_init__(self) -> None:
        validate_sha256_hex(self.attempt_id)
        validate_sha256_hex(self.evaluation_id)
        _validate_attempt_number(self.attempt_number)
        for field_name in ("protocol_version", "T_session_date", "symbol", "claimed_by_runtime"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise EvidenceIntegrityError(f"{field_name} boş olmayan bir string olmalı: {value!r}")

    def identity_fields(self) -> dict:
        """HATA 12N2A section 9: `claimed_by_runtime` KASITLI OLARAK bu
        kimlik setinin DIŞINDADIR -- iki farklı runtime'ın AYNI attempt_id
        için claim denemesi, `claimed_by_runtime` farklı olsa BİLE normal
        (ilk-claimant-kazanır) bir redelivery'dir, PROVENANCE_CONFLICT
        DEĞİLDİR."""
        return {
            "attempt_id": self.attempt_id,
            "evaluation_id": self.evaluation_id,
            "attempt_number": self.attempt_number,
            "protocol_version": self.protocol_version,
            "T_session_date": self.T_session_date,
            "symbol": self.symbol,
        }

    def to_document_fields(self) -> dict:
        return {**self.identity_fields(), "claimed_by_runtime": self.claimed_by_runtime}

    @classmethod
    def from_document_fields(cls, data: dict) -> AttemptClaim:
        return cls(
            attempt_id=data["attempt_id"],
            evaluation_id=data["evaluation_id"],
            attempt_number=data["attempt_number"],
            protocol_version=data["protocol_version"],
            T_session_date=data["T_session_date"],
            symbol=data["symbol"],
            claimed_by_runtime=data["claimed_by_runtime"],
        )


@dataclass(frozen=True)
class AttemptResult:
    """HATA 12N2A section 10: immutable, terminal deneme (attempt) sonucu.

    KASITLI OLARAK YOK: `before_cutoff`/`technical_observation_eligible`/
    `primary_outcome_eligible` (bunlar N2B finalizer'ının SONRADAN,
    `DocumentSnapshot.create_time` okuyarak türeteceği alanlardır -- bu
    dokümanın içeriği DEĞİLDİR, bkz. HATA 12P/12Q); lease/generation alanı
    (CLAIM-ONCE modelinde gerek YOK).

    `attempt_result_content_sha256` bu sınıfın bir ALANI DEĞİLDİR -- HER
    ZAMAN `content_sha256` property'si üzerinden, diğer tüm alanlardan
    TÜRETİLİR (bkz. aşağı). Bu, "hash kendi kendini nasıl hariç tutar"
    sorusunu yapısal olarak ortadan kaldırır: türetilmiş bir alan kendi
    girdisinin bir parçası OLAMAZ.
    """

    attempt_id: str
    evaluation_id: str
    attempt_number: int
    protocol_version: str
    T_session_date: str
    symbol: str

    scheduled_for: str
    runtime_fingerprint: str

    config_gate_result: GateCheckResult
    methodology_gate_result: GateCheckResult
    runtime_gate_result: GateCheckResult
    universe_gate_result: GateCheckResult

    result_classification: AttemptResultClassification
    native_reason_code: str | None

    started_at: str
    finished_at: str

    provider_fetch: ProviderFetchMetadata | None = None

    asset_input_sha256: str | None = None
    benchmark_input_sha256: str | None = None
    input_snapshot_sha256: str | None = None
    technical_output_sha256: str | None = None

    asset_object_ref: EvidenceObjectRef | None = None
    benchmark_object_ref: EvidenceObjectRef | None = None
    technical_output_object_ref: EvidenceObjectRef | None = None

    def __post_init__(self) -> None:
        validate_sha256_hex(self.attempt_id)
        validate_sha256_hex(self.evaluation_id)
        _validate_attempt_number(self.attempt_number)
        for field_name in ("protocol_version", "T_session_date", "symbol", "scheduled_for", "runtime_fingerprint", "started_at", "finished_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise EvidenceIntegrityError(f"{field_name} boş olmayan bir string olmalı: {value!r}")

        _validate_object_ref_consistency(EvidenceObjectKind.ASSET_SNAPSHOT, self.asset_input_sha256, self.asset_object_ref)
        _validate_object_ref_consistency(
            EvidenceObjectKind.BENCHMARK_SNAPSHOT, self.benchmark_input_sha256, self.benchmark_object_ref
        )
        _validate_object_ref_consistency(
            EvidenceObjectKind.TECHNICAL_OUTPUT, self.technical_output_sha256, self.technical_output_object_ref
        )

        # HATA 12N2A section 14: input_snapshot_sha256 -- HATA 12M'in
        # birleştirme algoritmasının İKİNCİ, UYUMSUZ bir kopyası ASLA
        # YAZILMAZ; `evidence_serialization.input_snapshot_sha256_from_
        # hashes()` (aynı fonksiyon `input_snapshot_sha256()`'ın da
        # DELEGE ettiği yer) burada da DOĞRUDAN çağrılır.
        if self.asset_input_sha256 is not None and self.benchmark_input_sha256 is not None:
            expected_combined = input_snapshot_sha256_from_hashes(self.asset_input_sha256, self.benchmark_input_sha256)
            if self.input_snapshot_sha256 is None:
                raise EvidenceIntegrityError(
                    "asset_input_sha256 ve benchmark_input_sha256 ikisi de mevcut ama input_snapshot_sha256 eksik"
                )
            if self.input_snapshot_sha256 != expected_combined:
                raise EvidenceIntegrityError(
                    f"input_snapshot_sha256 ({self.input_snapshot_sha256}) beklenen birleştirilmiş hash "
                    f"({expected_combined}) ile eşleşmiyor"
                )
        else:
            if self.input_snapshot_sha256 is not None:
                raise EvidenceIntegrityError(
                    "input_snapshot_sha256 mevcut ama asset_input_sha256/benchmark_input_sha256'dan biri eksik"
                )

    def identity_fields(self) -> dict:
        return {
            "attempt_id": self.attempt_id,
            "evaluation_id": self.evaluation_id,
            "attempt_number": self.attempt_number,
            "protocol_version": self.protocol_version,
            "T_session_date": self.T_session_date,
            "symbol": self.symbol,
        }

    def to_content_fields(self) -> dict:
        """`attempt_result_content_sha256` hariç TÜM alanlar -- bu dict
        `canonical_hash.content_sha256()`'a doğrudan verilir."""
        return {
            **self.identity_fields(),
            "scheduled_for": self.scheduled_for,
            "runtime_fingerprint": self.runtime_fingerprint,
            "config_gate_result": self.config_gate_result.value,
            "methodology_gate_result": self.methodology_gate_result.value,
            "runtime_gate_result": self.runtime_gate_result.value,
            "universe_gate_result": self.universe_gate_result.value,
            "result_classification": self.result_classification.value,
            "native_reason_code": self.native_reason_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "provider_fetch": self.provider_fetch.to_content_fields() if self.provider_fetch is not None else None,
            "asset_input_sha256": self.asset_input_sha256,
            "benchmark_input_sha256": self.benchmark_input_sha256,
            "input_snapshot_sha256": self.input_snapshot_sha256,
            "technical_output_sha256": self.technical_output_sha256,
            "asset_object_ref": _object_ref_to_content_fields(self.asset_object_ref) if self.asset_object_ref else None,
            "benchmark_object_ref": (
                _object_ref_to_content_fields(self.benchmark_object_ref) if self.benchmark_object_ref else None
            ),
            "technical_output_object_ref": (
                _object_ref_to_content_fields(self.technical_output_object_ref)
                if self.technical_output_object_ref
                else None
            ),
        }

    @property
    def content_sha256(self) -> str:
        from app.research.canonical_hash import content_sha256 as _content_sha256

        return _content_sha256(self.to_content_fields())

    def to_document_fields(self) -> dict:
        """Firestore'a YAZILACAK TAM alan seti -- içerik alanları + türetilmiş
        `attempt_result_content_sha256`. Bu dict AYNI ZAMANDA content-hash
        DOĞRULAMASI için de kullanılır (bkz. repository) -- iki AYRI temsil
        YOKTUR."""
        return {**self.to_content_fields(), "attempt_result_content_sha256": self.content_sha256}

    @classmethod
    def from_document_fields(cls, data: dict) -> AttemptResult:
        """`to_document_fields()`'ın TERSİ -- `attempt_result_content_
        sha256` alanı KASITLI OLARAK okunmaz/kullanılmaz (constructor'ın
        bir parametresi DEĞİLDİR, her zaman yeniden TÜRETİLİR); çağıran
        taraf tamper/tutarlılık kontrolü için `result.content_sha256`'ı
        dokümanın saklanan `attempt_result_content_sha256` alanıyla AYRICA
        karşılaştırmalıdır (bkz. repository `publish_result()`)."""

        def _ref(ref_data: dict | None) -> EvidenceObjectRef | None:
            if ref_data is None:
                return None
            return EvidenceObjectRef(
                kind=EvidenceObjectKind(ref_data["kind"]),
                sha256=ref_data["sha256"],
                object_name=ref_data["object_name"],
                size_bytes=ref_data["size_bytes"],
                bucket_name=ref_data.get("bucket_name"),
            )

        provider_fetch_data = data.get("provider_fetch")
        provider_fetch = ProviderFetchMetadata(**provider_fetch_data) if provider_fetch_data is not None else None

        return cls(
            attempt_id=data["attempt_id"],
            evaluation_id=data["evaluation_id"],
            attempt_number=data["attempt_number"],
            protocol_version=data["protocol_version"],
            T_session_date=data["T_session_date"],
            symbol=data["symbol"],
            scheduled_for=data["scheduled_for"],
            runtime_fingerprint=data["runtime_fingerprint"],
            config_gate_result=GateCheckResult(data["config_gate_result"]),
            methodology_gate_result=GateCheckResult(data["methodology_gate_result"]),
            runtime_gate_result=GateCheckResult(data["runtime_gate_result"]),
            universe_gate_result=GateCheckResult(data["universe_gate_result"]),
            result_classification=AttemptResultClassification(data["result_classification"]),
            native_reason_code=data.get("native_reason_code"),
            started_at=data["started_at"],
            finished_at=data["finished_at"],
            provider_fetch=provider_fetch,
            asset_input_sha256=data.get("asset_input_sha256"),
            benchmark_input_sha256=data.get("benchmark_input_sha256"),
            input_snapshot_sha256=data.get("input_snapshot_sha256"),
            technical_output_sha256=data.get("technical_output_sha256"),
            asset_object_ref=_ref(data.get("asset_object_ref")),
            benchmark_object_ref=_ref(data.get("benchmark_object_ref")),
            technical_output_object_ref=_ref(data.get("technical_output_object_ref")),
        )
