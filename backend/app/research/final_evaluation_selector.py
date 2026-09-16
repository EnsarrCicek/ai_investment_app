"""HATA 12N2B1 — Technical V1 saf/deterministik final-evaluation seçim
motoru.

Bu modül HİÇBİR Firestore erişimi YAPMAZ -- yalnızca zaten materyalize
edilmiş `PersistedAttemptClaim`/`PersistedAttemptResultDocument` girdi
zarflarını (ki bunların `document_fields`'i KASITLI OLARAK HAM/
doğrulanmamış dict'lerdir) ve enjekte edilmiş bir `EvidenceObjectStore`'u
alıp SAF, deterministik bir `FinalEvaluation` üretir.

Doğrulama önceliği (HATA 12N2B1 section 16, KİLİTLİ sıra):
  1. bağımsız beklenen kimlik (attempt_id/evaluation_id, context'ten)
  2. claim varlığı/kimliği
  3. result varlığı
  4. ham result içerik-hash bütünlüğü
  5. semantik/model doğrulaması
  6. claim/result kimlik ilişkisi
  7. sınıflandırma/gate'ler (yalnızca ADAYLIK için, güvenilirlik İÇİN DEĞİL)
  8. GCS doğrulaması (yalnızca aksi halde geçerli bir aday için)
  9. create_time cutoff karşılaştırması

KİLİTLİ tasarım düzeltmesi (bu ticket'ta, önceki HATA 12N2B-A2 taslağının
YERİNE): "VALID_CANDIDATE + bir gate PASS değil" durumu ARTIK
`RESULT_SEMANTIC_INVALID` OLARAK YANLIŞ SINIFLANDIRILMAZ -- kayıt KENDİ
İÇİNDE tamamen tutarlı/güvenilir (`TERMINAL_RESULT`/`VERIFIED`) kalır,
yalnızca ADAYLIK sorgusu (`QUALIFYING_AT_ATTEMPT2_DECISION`/
`QUALIFYING_FOR_FINAL_SELECTION`) bunu reddeder -- section 16'nın "semantik
doğrulama" (5) ile "sınıflandırma/gate'ler" (7) adımlarını AYRI listelemesi
bunu netleştirir. Yalnızca "VALID_CANDIDATE ama zorunlu bir object-ref
eksik" (section 23) GERÇEK bir semantik-sözleşme ihlalidir (`RESULT_
SEMANTIC_INVALID`) -- ikisi FARKLI kategorilerdir.
"""

from __future__ import annotations

from datetime import datetime

from app.research.attempt_models import (
    AttemptResult,
    AttemptResultClassification,
    GateCheckResult,
)
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_attempt_id
from app.research.evidence_models import (
    EvidenceObjectKind,
    EvidenceObjectNotFoundError,
    ObjectStoreError,
    ProvenanceConflictError,
)
from app.research.evidence_object_store import EvidenceObjectStore
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    AttemptSummary,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalEvaluation,
    FinalizationContext,
    FinalizationRetryableError,
    OrchestrationAnomalyCode,
    PersistedAttemptClaim,
    PersistedAttemptResultDocument,
    ResultState,
    VerificationState,
)

_PROBLEM_VERIFICATION_STATES = frozenset(
    {
        VerificationState.CLAIM_RELATION_INVALID,
        VerificationState.RESULT_CONTENT_HASH_INVALID,
        VerificationState.RESULT_SEMANTIC_INVALID,
    }
)
_EVIDENCE_LOSS_VERIFICATION_STATES = frozenset(
    {VerificationState.EVIDENCE_MISSING, VerificationState.EVIDENCE_HASH_MISMATCH}
)

_REQUIRED_OBJECT_KINDS_IN_ORDER: tuple[tuple[str, EvidenceObjectKind], ...] = (
    ("asset", EvidenceObjectKind.ASSET_SNAPSHOT),
    ("benchmark", EvidenceObjectKind.BENCHMARK_SNAPSHOT),
    ("technical_output", EvidenceObjectKind.TECHNICAL_OUTPUT),
)


class _AttemptEvaluation:
    """İç, saf yardımcı taşıyıcı -- bir denemenin (attempt) tüm ara
    sonuçlarını (özet + güvenilen `AttemptResult` nesnesi varsa) taşır.
    Dışarıya (production API) SIZDIRILMAZ -- yalnızca bu modülün kendi
    orkestrasyonu için dahili bir taşıyıcıdır."""

    __slots__ = ("summary", "trusted_result")

    def __init__(self, summary: AttemptSummary, trusted_result: AttemptResult | None):
        self.summary = summary
        self.trusted_result = trusted_result


def _expected_identity(context: FinalizationContext, attempt_number: int) -> dict:
    return {
        "attempt_id": compute_attempt_id(context.evaluation_id, attempt_number),
        "evaluation_id": context.evaluation_id,
        "attempt_number": attempt_number,
        "protocol_version": context.protocol_version,
        "T_session_date": context.T_session_date,
        "symbol": context.symbol,
    }


def _classify_claim(
    claim: PersistedAttemptClaim | None, expected_identity: dict
) -> tuple[ClaimPresence, bool]:
    """`(claim_presence, claim_identity_consistent)` döner. Doküman ID'sinin
    doğru olması TEK BAŞINA YETERLİ DEĞİLDİR -- İÇERİK alanları bağımsız
    olarak karşılaştırılır (HATA 12N2B1 section 4)."""
    if claim is None:
        return ClaimPresence.MISSING, True  # yokluk durumunda "tutarlılık" anlamsız/geçerli kabul edilir
    actual_identity = {key: claim.document_fields.get(key) for key in expected_identity}
    return ClaimPresence.CLAIMED, actual_identity == expected_identity


_BLOCKED_CLASSIFICATION_REQUIRED_FAILING_GATE: dict[AttemptResultClassification, str] = {
    AttemptResultClassification.BLOCKED_CONFIG_DRIFT: "config_gate_result",
    AttemptResultClassification.BLOCKED_METHODOLOGY_DRIFT: "methodology_gate_result",
    AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY: "runtime_gate_result",
    AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG: "universe_gate_result",
}


def _classification_gate_consistency_holds(result: AttemptResult) -> bool:
    """HATA 12N2B1-F: `result_classification` ile frozen gate alanları
    arasında taksonominin KENDİSİNDEN gelen, KAÇINILMAZ ilişkileri
    doğrular -- kanıtsız bir tam-matris İCAT EDİLMEZ (section 4/5):

      - `VALID_CANDIDATE` <=> dört gate'in TÜMÜ `PASS` (aksi halde kayıt
        kendi içinde ÇELİŞKİLİDİR -- "geçerli aday" iddiası ile
        "bir ön-uçuş kapısı geçmedi" gerçeği AYNI ANDA doğru olamaz).
      - Her `BLOCKED_*` sınıflandırması <=> KENDİ karşılık gelen
        gate'inin `FAIL` olması (ör. `BLOCKED_CONFIG_DRIFT` yalnızca
        `config_gate_result == FAIL` iken anlamlıdır). DİĞER üç gate'in
        değeri BU KURAL TARAFINDAN KISITLANMAZ -- worker'ın gate
        değerlendirme SIRASI hakkında (henüz hiçbir worker
        implementasyonu YOKKEN) kanıtsız bir varsayım YAPILMAZ.
      - `EXCLUSION`/`FAILED` için HİÇBİR gate ilişkisi taksonomiden
        GARANTİ EDİLMEZ (section 5) -- bu ikisi için HER ZAMAN `True`
        döner, yapay bir kısıt EKLENMEZ.
    """
    classification = result.result_classification
    if classification == AttemptResultClassification.VALID_CANDIDATE:
        return _all_gates_pass(result)
    required_failing_gate_field = _BLOCKED_CLASSIFICATION_REQUIRED_FAILING_GATE.get(classification)
    if required_failing_gate_field is not None:
        return getattr(result, required_failing_gate_field) == GateCheckResult.FAIL
    return True  # EXCLUSION / FAILED


def _classify_result(
    result_doc: PersistedAttemptResultDocument | None,
    expected_identity: dict,
    claim_presence: ClaimPresence,
    claim_identity_consistent: bool,
    claim_activation_lock_id: str | None,
) -> tuple[ResultState, VerificationState, str | None, str | None, AttemptResult | None]:
    """`(result_state, verification_state, result_classification_value,
    native_reason_code, trusted_result_or_None)` döner.

    KİLİTLİ sıra (section 16, adım 4-6): önce ham içerik-hash bütünlüğü,
    SONRA semantik/model doğrulaması, EN SON claim/result kimlik ilişkisi.
    Üç "problem" dalının (RESULT_CONTENT_HASH_INVALID / RESULT_SEMANTIC_
    INVALID / CLAIM_RELATION_INVALID) HİÇBİRİNDE `result_classification`/
    `native_reason_code` GÜVENİLMEZ/KOPYALANMAZ (section 13/14/15) --
    kayıt kendi içinde ya da ilişkisel olarak güvenilmez bulunduysa,
    İÇERİĞİNİN HİÇBİR PARÇASI dışarı sızdırılmaz.

    HATA 12N3C2-B2-C section 16: adım 6'nın claim/result kimlik ilişkisi
    kontrolüne, DEFENSE-IN-DEPTH olarak, `claim.activation_lock_id ==
    result.activation_lock_id` eşitliği de eklenir -- depolama bozulması/
    tamperlenmiş doküman/gelecekteki bir repository bypass'ına karşı,
    `publish_result()`'ın KENDİ (repository-katmanı) kontrolüne TEK BAŞINA
    güvenilmez. Uyuşmazlık AYNI `CLAIM_RELATION_INVALID` durumuna girer --
    YENİ bir `VerificationState` İCAT EDİLMEZ."""
    if result_doc is None:
        return ResultState.NO_RESULT, VerificationState.NOT_APPLICABLE, None, None, None

    raw_fields = result_doc.document_fields
    stored_hash = raw_fields.get("attempt_result_content_sha256")
    content_fields = {key: value for key, value in raw_fields.items() if key != "attempt_result_content_sha256"}

    # Adım 4: ham içerik-hash bütünlüğü.
    if not isinstance(stored_hash, str) or not stored_hash:
        return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_CONTENT_HASH_INVALID, None, None, None
    try:
        recomputed_hash = content_sha256(content_fields)
    except (TypeError, ValueError):
        return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_CONTENT_HASH_INVALID, None, None, None
    if recomputed_hash != stored_hash:
        return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_CONTENT_HASH_INVALID, None, None, None

    # Adım 5: semantik/model doğrulaması -- `AttemptResult`'ın KENDİ
    # `__post_init__` sözleşmesi (attempt_number geçerliliği, object-ref
    # tutarlılığı, input-snapshot birleştirme tutarlılığı, vb.) burada
    # TEKRAR YAZILMAZ, doğrudan yeniden kullanılır.
    try:
        trusted_result = AttemptResult.from_document_fields(content_fields)
    except (ValueError, KeyError, TypeError):
        return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_SEMANTIC_INVALID, None, None, None

    # HATA 12N2B1 section 23: VALID_CANDIDATE, üç zorunlu object-ref'in
    # HİÇBİRİNİ nullable BIRAKAMAZ -- bu, `AttemptResult.__post_init__`'in
    # KENDİ genel object-ref-tutarlılık kontrolünün (hash var/yok <-> ref
    # var/yok) KAPSAMADIĞI, VALID_CANDIDATE'e ÖZGÜ ek bir semantik kural.
    if trusted_result.result_classification == AttemptResultClassification.VALID_CANDIDATE:
        if (
            trusted_result.asset_object_ref is None
            or trusted_result.benchmark_object_ref is None
            or trusted_result.technical_output_object_ref is None
        ):
            return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_SEMANTIC_INVALID, None, None, None

    # HATA 12N2B1-F: `result_classification` ile frozen gate alanları
    # arasındaki taksonomiden-kaynaklanan kaçınılmaz ilişki de AYNI adımda
    # (5) doğrulanır -- `VALID_CANDIDATE` iddiası + herhangi bir gate'in
    # `FAIL` olması (veya tersine, bir `BLOCKED_*` iddiası + karşılık
    # gelen gate'in `PASS` olması) kendi içinde ÇELİŞKİLİDİR; bu bir
    # ordinary/trusted terminal sonuç OLARAK KABUL EDİLMEZ, sınıflandırma/
    # native reason YİNE DE dışarı sızdırılmaz.
    if not _classification_gate_consistency_holds(trusted_result):
        return ResultState.INTEGRITY_INVALID, VerificationState.RESULT_SEMANTIC_INVALID, None, None, None

    # Adım 6: claim/result kimlik ilişkisi -- kayıt kendi içinde tutarlı
    # (adım 4/5 geçti) OLSA BİLE, karşılık gelen claim yoksa/tutarsızsa
    # VEYA kaydın KENDİ kimlik alanları beklenenle uyuşmuyorsa bu bir
    # provenance/repository-bütünlüğü sorunudur -- sınıflandırma/native
    # reason YİNE DE dışarı sızdırılmaz.
    if (
        claim_presence != ClaimPresence.CLAIMED
        or not claim_identity_consistent
        or trusted_result.identity_fields() != expected_identity
        or trusted_result.activation_lock_id != claim_activation_lock_id
    ):
        return ResultState.INTEGRITY_INVALID, VerificationState.CLAIM_RELATION_INVALID, None, None, None

    return (
        ResultState.TERMINAL_RESULT,
        VerificationState.VERIFIED,
        trusted_result.result_classification.value,
        trusted_result.native_reason_code,
        trusted_result,
    )


def _evaluate_attempt(
    attempt_number: int,
    context: FinalizationContext,
    claim: PersistedAttemptClaim | None,
    result_doc: PersistedAttemptResultDocument | None,
) -> _AttemptEvaluation:
    expected_identity = _expected_identity(context, attempt_number)
    claim_presence, claim_identity_consistent = _classify_claim(claim, expected_identity)
    claim_activation_lock_id = claim.document_fields.get("activation_lock_id") if claim is not None else None
    result_state, verification_state, classification_value, native_reason_code, trusted_result = _classify_result(
        result_doc, expected_identity, claim_presence, claim_identity_consistent, claim_activation_lock_id
    )
    summary = AttemptSummary(
        attempt_number=attempt_number,
        attempt_id=expected_identity["attempt_id"],  # HER ZAMAN bağımsız hesaplanan -- ASLA dokümandan kopyalanmaz
        requirement_state=AttemptRequirementState.REQUIRED,  # section 19'da attempt_2 için AYRICA yeniden atanır
        claim_presence=claim_presence,
        result_state=result_state,
        result_classification=classification_value,
        native_reason_code=native_reason_code,
        verification_state=verification_state,
        verification_reason_code=None,
    )
    return _AttemptEvaluation(summary=summary, trusted_result=trusted_result)


def _all_gates_pass(result: AttemptResult) -> bool:
    return (
        result.config_gate_result == GateCheckResult.PASS
        and result.methodology_gate_result == GateCheckResult.PASS
        and result.runtime_gate_result == GateCheckResult.PASS
        and result.universe_gate_result == GateCheckResult.PASS
    )


def _qualifying_at_attempt2_decision(
    attempt1: _AttemptEvaluation, context: FinalizationContext, attempt1_create_time: datetime | None
) -> bool:
    """HATA 12N2B1 section 18: attempt #2'nin TARİHSEL olarak gerekli
    olup olmadığını yeniden inşa etmek İÇİN bir saf predikat -- CANLI GCS
    doğrulaması YAPMAZ (o, section 26'nın AYRI predikatına aittir)."""
    if attempt1.summary.result_state != ResultState.TERMINAL_RESULT:
        return False
    result = attempt1.trusted_result
    if result is None or result.result_classification != AttemptResultClassification.VALID_CANDIDATE:
        return False
    if not _all_gates_pass(result):
        return False
    if attempt1_create_time is None:
        return False
    return attempt1_create_time < context.attempt2_decision_time_utc


def _attempt2_requirement_state(attempt1: _AttemptEvaluation, qualifying_at_decision: bool) -> AttemptRequirementState:
    """HATA 12N2B1 section 19 (A/B/C):
      A) attempt1 provenance/integrity-invalid -> INDETERMINATE_PROVENANCE
      B) QUALIFYING_AT_ATTEMPT2_DECISION == true -> NOT_REQUIRED_FIRST_VALID
      C) aksi halde (TEMİZ yokluk DAHİL -- section 19: "clean absence is
         NOT provenance-indeterminate") -> REQUIRED
    """
    if attempt1.summary.result_state == ResultState.INTEGRITY_INVALID:
        return AttemptRequirementState.INDETERMINATE_PROVENANCE
    if qualifying_at_decision:
        return AttemptRequirementState.NOT_REQUIRED_FIRST_VALID
    return AttemptRequirementState.REQUIRED


def _verify_evidence_objects(
    result: AttemptResult, object_store: EvidenceObjectStore
) -> tuple[VerificationState, str | None]:
    """HATA 12N2B1 section 23-25: yalnızca `result_classification ==
    VALID_CANDIDATE` VE tüm gate'ler PASS olan, ZATEN güvenilir bir
    `TERMINAL_RESULT` için çağrılır. Sabit sıra: asset -> benchmark ->
    technical_output (section 25 -- yalnızca deterministik tanılama
    içindir). Kesin/bilinen bir depolama hatası VerificationState'e
    eşlenir; BİLİNMEYEN/geçici bir `ObjectStoreError` ise
    `FinalizationRetryableError` olarak YUKARI FIRLATILIR (yakalanmaz) --
    bu, section 24/42'nin kilitlediği "geçici hata asla kalıcı bir
    sınıflandırmaya dönüşmez" kuralıdır."""
    hash_by_kind = {
        EvidenceObjectKind.ASSET_SNAPSHOT: result.asset_input_sha256,
        EvidenceObjectKind.BENCHMARK_SNAPSHOT: result.benchmark_input_sha256,
        EvidenceObjectKind.TECHNICAL_OUTPUT: result.technical_output_sha256,
    }
    for label, kind in _REQUIRED_OBJECT_KINDS_IN_ORDER:
        expected_hash = hash_by_kind[kind]
        try:
            object_store.get_verified(kind, expected_hash)
        except EvidenceObjectNotFoundError as exc:
            return VerificationState.EVIDENCE_MISSING, f"{label}: {exc}"
        except ProvenanceConflictError as exc:
            return VerificationState.EVIDENCE_HASH_MISMATCH, f"{label}: {exc}"
        except ObjectStoreError as exc:
            # HATA 12N2B1 section 24/42: KRİTİK -- bu istisna YAKALANMAZ/
            # bir VerificationState'e DÖNÜŞTÜRÜLMEZ, doğrudan yukarı
            # (finalizasyonun TAMAMINI durdurarak) fırlatılır.
            raise FinalizationRetryableError(
                f"{label} nesnesi doğrulanırken geçici/bilinmeyen bir depolama hatası oluştu: {exc}"
            ) from exc
    return VerificationState.VERIFIED, None


def _qualifying_for_final_selection(
    attempt: _AttemptEvaluation,
    result_doc: PersistedAttemptResultDocument | None,
    context: FinalizationContext,
    object_store: EvidenceObjectStore,
) -> bool:
    """HATA 12N2B1 section 26: `QUALIFYING_AT_ATTEMPT2_DECISION`'dan AYRI
    bir predikat -- CANLI GCS doğrulaması + `formal_cutoff_utc` karşısında
    KESİN `<` gerektirir. `attempt.summary`'yi (verification_state alanı
    dahil) YERİNDE GÜNCELLER -- bu fonksiyon çağrıldıktan SONRA
    `attempt.summary` GCS doğrulama sonucunu yansıtır (section 30: bir
    kardeş adayın kanıt kaybı ASLA gizlenmez, adayın kendisi kazanmasa
    BİLE)."""
    if attempt.summary.result_state != ResultState.TERMINAL_RESULT:
        return False
    result = attempt.trusted_result
    if result is None or result.result_classification != AttemptResultClassification.VALID_CANDIDATE:
        return False
    if not _all_gates_pass(result):
        # HATA 12N2B1 section 16/23 düzeltmesi: bu RESULT_SEMANTIC_INVALID
        # DEĞİLDİR -- kayıt GÜVENİLİR kalır (VERIFIED), yalnızca ADAYLIK
        # sağlamaz (GCS doğrulaması bile denenmez).
        return False

    # HATA 12N2B1 section 30: GCS doğrulaması, cutoff zamanlamasından
    # BAĞIMSIZ olarak HER ZAMAN denenir -- bir kardeş adayın kanıt kaybı,
    # kendisi zamanlama nedeniyle zaten kazanamayacak olsa BİLE asla
    # sessizce atlanmaz/gizlenmez.
    verification_state, reason_code = _verify_evidence_objects(result, object_store)
    attempt.summary = AttemptSummary(
        attempt_number=attempt.summary.attempt_number,
        attempt_id=attempt.summary.attempt_id,
        requirement_state=attempt.summary.requirement_state,
        claim_presence=attempt.summary.claim_presence,
        result_state=attempt.summary.result_state,
        result_classification=attempt.summary.result_classification,
        native_reason_code=attempt.summary.native_reason_code,
        verification_state=verification_state,
        verification_reason_code=reason_code,
    )
    if verification_state != VerificationState.VERIFIED:
        return False

    create_time = result_doc.create_time if result_doc is not None else None
    if create_time is None:
        return False
    return create_time < context.formal_cutoff_utc


def _attempt_complete(summary, requirement_matters: bool) -> bool:
    if requirement_matters and summary.requirement_state == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID:
        return True
    return summary.claim_presence == ClaimPresence.CLAIMED and summary.result_state == ResultState.TERMINAL_RESULT


def _derive_evaluation_integrity_status(
    summaries: tuple[AttemptSummary, AttemptSummary], attempt_history_complete: bool
) -> EvaluationIntegrityStatus:
    """HATA 12N2B1 section 32 -- KİLİTLİ öncelik sırası."""
    for summary in summaries:
        if summary.verification_state in _PROBLEM_VERIFICATION_STATES:
            return EvaluationIntegrityStatus.PROVENANCE_CONFLICT
    if any(s.requirement_state == AttemptRequirementState.INDETERMINATE_PROVENANCE for s in summaries):
        return EvaluationIntegrityStatus.PROVENANCE_CONFLICT
    for summary in summaries:
        if summary.verification_state in _EVIDENCE_LOSS_VERIFICATION_STATES:
            return EvaluationIntegrityStatus.EVIDENCE_INTEGRITY_FAILURE
    if not attempt_history_complete:
        return EvaluationIntegrityStatus.AUDIT_INCOMPLETE
    return EvaluationIntegrityStatus.CLEAN


def _derive_capture_status(
    selected: _AttemptEvaluation | None, summaries: tuple[AttemptSummary, AttemptSummary]
) -> CaptureStatus:
    """HATA 12N2B1 section 33 -- tamamlanma/bütünlük/provenance BURAYA
    ASLA KARIŞMAZ."""
    if selected is not None:
        return CaptureStatus.VALID_CAPTURE_AVAILABLE
    trustworthy_terminal = [s for s in summaries if s.result_state == ResultState.TERMINAL_RESULT]
    if trustworthy_terminal and all(
        s.result_classification is not None and s.result_classification.startswith("BLOCKED_")
        for s in trustworthy_terminal
    ):
        return CaptureStatus.INFRASTRUCTURE_BLOCKED
    return CaptureStatus.NO_VALID_CAPTURE_AVAILABLE


def select_final_evaluation(
    context: FinalizationContext,
    attempt1_claim: PersistedAttemptClaim | None,
    attempt1_result: PersistedAttemptResultDocument | None,
    attempt2_claim: PersistedAttemptClaim | None,
    attempt2_result: PersistedAttemptResultDocument | None,
    object_store: EvidenceObjectStore,
) -> FinalEvaluation:
    """HATA 12N2B1 — saf, deterministik final-evaluation seçici.

    Aynı `context`/ham girdiler/`create_time` değerleri VE aynı
    `object_store` yanıtları verildiğinde, HER ZAMAN bit-bit AYNI
    `FinalEvaluation` içerik alanlarını (dolayısıyla aynı
    `record_content_sha256`'yı) üretir -- UUID/`now()`/rastgelelik/
    sırasız küme serileştirmesi YOKTUR (section 41).

    Yalnızca BİLİNMEYEN/geçici bir `EvidenceObjectStore` hatasıyla
    karşılaşılırsa `FinalizationRetryableError` fırlatır -- bu durumda
    hiçbir `FinalEvaluation` DÖNDÜRÜLMEZ (section 42)."""
    attempt1 = _evaluate_attempt(1, context, attempt1_claim, attempt1_result)
    # attempt1.summary.requirement_state zaten REQUIRED (sabit, section 7/9).

    attempt1_create_time = attempt1_result.create_time if attempt1_result is not None else None
    qualifying_at_decision = _qualifying_at_attempt2_decision(attempt1, context, attempt1_create_time)
    attempt2_requirement = _attempt2_requirement_state(attempt1, qualifying_at_decision)

    attempt2 = _evaluate_attempt(2, context, attempt2_claim, attempt2_result)
    anomaly_codes: set[OrchestrationAnomalyCode] = set()

    if attempt2_requirement == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID and attempt2.summary.claim_presence == ClaimPresence.MISSING:
        # HATA 12N2B1 section 20: TEMİZ, beklenen "hiç çalıştırılmadı" durumu.
        attempt2.summary = AttemptSummary(
            attempt_number=2,
            attempt_id=attempt2.summary.attempt_id,
            requirement_state=AttemptRequirementState.NOT_REQUIRED_FIRST_VALID,
            claim_presence=ClaimPresence.MISSING,
            result_state=ResultState.NOT_APPLICABLE,
            result_classification=None,
            native_reason_code=None,
            verification_state=VerificationState.NOT_APPLICABLE,
            verification_reason_code=None,
        )
    else:
        if attempt2_requirement == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID:
            # HATA 12N2B1 section 21: BEKLENMEYEN attempt #2 -- attempt1'i
            # GEÇERSİZ KILMAZ, ama bir anomali olarak KAYDEDİLİR. Genel
            # sınıflandırma mantığı (yukarıda zaten çalıştırıldı) DEĞİŞMEDEN
            # kalır -- yalnızca requirement_state güncellenir.
            anomaly_codes.add(OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED)
        attempt2.summary = AttemptSummary(
            attempt_number=2,
            attempt_id=attempt2.summary.attempt_id,
            requirement_state=attempt2_requirement,
            claim_presence=attempt2.summary.claim_presence,
            result_state=attempt2.summary.result_state,
            result_classification=attempt2.summary.result_classification,
            native_reason_code=attempt2.summary.native_reason_code,
            verification_state=attempt2.summary.verification_state,
            verification_reason_code=attempt2.summary.verification_reason_code,
        )

    # HATA 12N2B1 section 26/27: QUALIFYING_FOR_FINAL_SELECTION -- CANLI GCS
    # doğrulaması BURADA, sabit sırada (1 sonra 2) yapılır. Geçici bir
    # depolama hatası (`FinalizationRetryableError`) BURADA fırlatılırsa,
    # bu fonksiyon TAMAMEN durur -- kardeş adaya ASLA geçilmez (section 42).
    attempt1_qualifies = _qualifying_for_final_selection(attempt1, attempt1_result, context, object_store)
    attempt2_qualifies = _qualifying_for_final_selection(attempt2, attempt2_result, context, object_store)

    candidates: list[tuple[datetime, int, _AttemptEvaluation, PersistedAttemptResultDocument]] = []
    if attempt1_qualifies:
        candidates.append((attempt1_result.create_time, 1, attempt1, attempt1_result))
    if attempt2_qualifies:
        candidates.append((attempt2_result.create_time, 2, attempt2, attempt2_result))

    # HATA 12N2B1 section 27/48: en erken create_time kazanır; eşitlikte
    # daha düşük attempt_number kazanır -- İSTEMCİ zaman damgası/döküman
    # sırası/finalizer okuma sırası ASLA kullanılmaz.
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected: _AttemptEvaluation | None = candidates[0][2] if candidates else None
    selected_result_doc: PersistedAttemptResultDocument | None = candidates[0][3] if candidates else None

    summaries = (attempt1.summary, attempt2.summary)

    attempt1_complete = _attempt_complete(attempt1.summary, requirement_matters=False)
    attempt2_complete = _attempt_complete(attempt2.summary, requirement_matters=True)
    attempt_history_complete = attempt1_complete and attempt2_complete

    evaluation_integrity_status = _derive_evaluation_integrity_status(summaries, attempt_history_complete)
    capture_status = _derive_capture_status(selected, summaries)

    if selected is not None:
        selected_attempt_id = selected.summary.attempt_id
        selected_evidence_integrity_complete: bool | None = True
        technical_observation_eligible = True
        selected_result = selected.trusted_result
        selected_asset_input_sha256 = selected_result.asset_input_sha256
        selected_benchmark_input_sha256 = selected_result.benchmark_input_sha256
        selected_input_snapshot_sha256 = selected_result.input_snapshot_sha256
        selected_technical_output_sha256 = selected_result.technical_output_sha256
        selected_asset_object_ref = selected_result.asset_object_ref
        selected_benchmark_object_ref = selected_result.benchmark_object_ref
        selected_technical_output_object_ref = selected_result.technical_output_object_ref
    else:
        selected_attempt_id = None
        selected_evidence_integrity_complete = None
        technical_observation_eligible = False
        selected_asset_input_sha256 = None
        selected_benchmark_input_sha256 = None
        selected_input_snapshot_sha256 = None
        selected_technical_output_sha256 = None
        selected_asset_object_ref = None
        selected_benchmark_object_ref = None
        selected_technical_output_object_ref = None

    return FinalEvaluation(
        evaluation_id=context.evaluation_id,
        protocol_version=context.protocol_version,
        T_session_date=context.T_session_date,
        symbol=context.symbol,
        protocol_sha256=context.protocol_sha256,
        methodology_git_commit=context.methodology_git_commit,
        freeze_manifest_sha256=context.freeze_manifest_sha256,
        engine_version=context.engine_version,
        scoring_config_hash=context.scoring_config_hash,
        E1_date=context.E1_date,
        formal_cutoff_timestamp=context.formal_cutoff_timestamp_str(),
        capture_status=capture_status,
        evaluation_integrity_status=evaluation_integrity_status,
        technical_observation_eligible=technical_observation_eligible,
        selected_evidence_integrity_complete=selected_evidence_integrity_complete,
        attempt_history_complete=attempt_history_complete,
        selected_attempt_id=selected_attempt_id,
        attempt_1_summary=attempt1.summary,
        attempt_2_summary=attempt2.summary,
        orchestration_anomaly_codes=frozenset(anomaly_codes),
        selected_asset_input_sha256=selected_asset_input_sha256,
        selected_benchmark_input_sha256=selected_benchmark_input_sha256,
        selected_input_snapshot_sha256=selected_input_snapshot_sha256,
        selected_technical_output_sha256=selected_technical_output_sha256,
        selected_asset_object_ref=selected_asset_object_ref,
        selected_benchmark_object_ref=selected_benchmark_object_ref,
        selected_technical_output_object_ref=selected_technical_output_object_ref,
    )
