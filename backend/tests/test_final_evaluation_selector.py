"""HATA 12N2B1 — `app/research/final_evaluation_selector.py`'nin saf,
deterministik final-evaluation seçim mantığının kapsamlı testleri.

Bu dosyadaki HİÇBİR test Firestore/GCS/ağ erişimi GEREKTİRMEZ --
`FakeEvidenceObjectStore` (HATA 12N1) ve saf `Persisted*` girdi zarfları
(HATA 12N2B1) kullanılır.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.research.attempt_models import (
    AttemptClaim,
    AttemptResult,
    AttemptResultClassification,
    GateCheckResult,
)
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id
from app.research.evidence_models import EvidenceObjectKind, EvidenceObjectRef, ObjectStoreError
from app.research.evidence_object_store import FakeEvidenceObjectStore
from app.research.evidence_serialization import input_snapshot_sha256_from_hashes
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalizationContext,
    FinalizationRetryableError,
    OrchestrationAnomalyCode,
    PersistedAttemptClaim,
    PersistedAttemptResultDocument,
    ResultState,
    VerificationState,
)
from app.research.final_evaluation_selector import select_final_evaluation

PROTOCOL = "TECHNICAL_V1_PROTOCOL_V1"
T_DATE = "2026-09-09"
SYMBOL = "AKBNK"

# E1 = 2026-09-10. 08:00/09:00/09:45 Europe/Istanbul (+03:00, DST yok) -> UTC.
ATTEMPT1_SCHEDULED_UTC = datetime(2026, 9, 10, 5, 0, 0, tzinfo=timezone.utc)  # 08:00 +03:00
DECISION_UTC = datetime(2026, 9, 10, 6, 0, 0, tzinfo=timezone.utc)  # 09:00 +03:00
CUTOFF_UTC = datetime(2026, 9, 10, 6, 45, 0, tzinfo=timezone.utc)  # 09:45 +03:00


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _eval_id() -> str:
    return compute_evaluation_id(PROTOCOL, T_DATE, SYMBOL)


def _attempt_id(n: int) -> str:
    return compute_attempt_id(_eval_id(), n)


def _make_context(decision: datetime = DECISION_UTC, cutoff: datetime = CUTOFF_UTC) -> FinalizationContext:
    return FinalizationContext(
        evaluation_id=_eval_id(),
        protocol_version=PROTOCOL,
        protocol_sha256="a" * 64,
        methodology_git_commit="c1f0d439d40a709d55007bd8ff34b4a8b2347f95",
        freeze_manifest_sha256="b" * 64,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        T_session_date=T_DATE,
        symbol=SYMBOL,
        E1_date="2026-09-10",
        attempt2_decision_time_utc=decision,
        formal_cutoff_utc=cutoff,
    )


def _upload_evidence(store: FakeEvidenceObjectStore, salt: str = "") -> tuple[str, str, str]:
    asset_bytes = f'{{"asset":"{salt}"}}'.encode()
    benchmark_bytes = f'{{"benchmark":"{salt}"}}'.encode()
    output_bytes = f'{{"output":"{salt}"}}'.encode()
    asset_hash, benchmark_hash, output_hash = _sha(asset_bytes), _sha(benchmark_bytes), _sha(output_bytes)
    store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, asset_hash, asset_bytes)
    store.put_immutable(EvidenceObjectKind.BENCHMARK_SNAPSHOT, benchmark_hash, benchmark_bytes)
    store.put_immutable(EvidenceObjectKind.TECHNICAL_OUTPUT, output_hash, output_bytes)
    return asset_hash, benchmark_hash, output_hash


def _make_valid_result(
    attempt_number: int,
    asset_hash: str,
    benchmark_hash: str,
    output_hash: str,
    gates_all_pass: bool = True,
    omit_technical_output_ref: bool = False,
) -> AttemptResult:
    input_snapshot_hash = input_snapshot_sha256_from_hashes(asset_hash, benchmark_hash)
    gate = GateCheckResult.PASS if gates_all_pass else GateCheckResult.FAIL
    kwargs = dict(
        attempt_id=_attempt_id(attempt_number),
        evaluation_id=_eval_id(),
        attempt_number=attempt_number,
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        symbol=SYMBOL,
        scheduled_for="2026-09-10T09:00:00+03:00",
        runtime_fingerprint="rev-x",
        config_gate_result=gate,
        methodology_gate_result=GateCheckResult.PASS,
        runtime_gate_result=GateCheckResult.PASS,
        universe_gate_result=GateCheckResult.PASS,
        result_classification=AttemptResultClassification.VALID_CANDIDATE,
        native_reason_code=None,
        started_at="2026-09-10T09:00:00+03:00",
        finished_at="2026-09-10T09:00:05+03:00",
        asset_input_sha256=asset_hash,
        benchmark_input_sha256=benchmark_hash,
        input_snapshot_sha256=input_snapshot_hash,
        asset_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.ASSET_SNAPSHOT, sha256=asset_hash, object_name="x", size_bytes=7),
        benchmark_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.BENCHMARK_SNAPSHOT, sha256=benchmark_hash, object_name="y", size_bytes=7),
    )
    if omit_technical_output_ref:
        kwargs["technical_output_sha256"] = None
        kwargs["technical_output_object_ref"] = None
    else:
        kwargs["technical_output_sha256"] = output_hash
        kwargs["technical_output_object_ref"] = EvidenceObjectRef(
            kind=EvidenceObjectKind.TECHNICAL_OUTPUT, sha256=output_hash, object_name="z", size_bytes=7
        )
    return AttemptResult(**kwargs)


def _make_nonvalid_result(attempt_number: int, classification: AttemptResultClassification, native_reason_code: str | None = None) -> AttemptResult:
    return AttemptResult(
        attempt_id=_attempt_id(attempt_number),
        evaluation_id=_eval_id(),
        attempt_number=attempt_number,
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        symbol=SYMBOL,
        scheduled_for="2026-09-10T09:00:00+03:00",
        runtime_fingerprint="rev-x",
        config_gate_result=GateCheckResult.PASS,
        methodology_gate_result=GateCheckResult.PASS,
        runtime_gate_result=GateCheckResult.PASS,
        universe_gate_result=GateCheckResult.PASS,
        result_classification=classification,
        native_reason_code=native_reason_code,
        started_at="2026-09-10T09:00:00+03:00",
        finished_at="2026-09-10T09:00:05+03:00",
    )


def _make_claim(attempt_number: int, symbol: str = SYMBOL) -> AttemptClaim:
    eval_id = compute_evaluation_id(PROTOCOL, T_DATE, symbol) if symbol != SYMBOL else _eval_id()
    return AttemptClaim(
        attempt_id=compute_attempt_id(eval_id, attempt_number),
        evaluation_id=eval_id,
        attempt_number=attempt_number,
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        symbol=symbol,
        claimed_by_runtime="rev-x",
    )


def _wrap_claim(claim: AttemptClaim) -> PersistedAttemptClaim:
    return PersistedAttemptClaim(
        attempt_number=claim.attempt_number, attempt_id=claim.attempt_id, document_fields=claim.to_document_fields()
    )


def _wrap_result(result: AttemptResult, create_time: datetime) -> PersistedAttemptResultDocument:
    return PersistedAttemptResultDocument(
        attempt_number=result.attempt_number,
        attempt_id=result.attempt_id,
        document_fields=result.to_document_fields(),
        create_time=create_time,
    )


def _select(
    context=None,
    attempt1_claim=None,
    attempt1_result=None,
    attempt2_claim=None,
    attempt2_result=None,
    object_store=None,
):
    return select_final_evaluation(
        context=context or _make_context(),
        attempt1_claim=attempt1_claim,
        attempt1_result=attempt1_result,
        attempt2_claim=attempt2_claim,
        attempt2_result=attempt2_result,
        object_store=object_store or FakeEvidenceObjectStore(),
    )


# ---------------------------------------------------------------------------
# Section 28: VALID + sibling no-result
# ---------------------------------------------------------------------------


def test_valid_plus_sibling_no_result():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result2 = _make_valid_result(2, asset_hash, benchmark_hash, output_hash)
    claim2 = _make_claim(2)

    fe = _select(
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),  # 09:10
        object_store=store,
    )

    assert fe.technical_observation_eligible is True
    assert fe.selected_attempt_id == _attempt_id(2)
    assert fe.selected_evidence_integrity_complete is True
    assert fe.attempt_history_complete is False
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.AUDIT_INCOMPLETE
    assert fe.capture_status == CaptureStatus.VALID_CAPTURE_AVAILABLE
    assert fe.attempt_1_summary.claim_presence == ClaimPresence.MISSING
    assert fe.attempt_1_summary.result_state == ResultState.NO_RESULT


# ---------------------------------------------------------------------------
# Section 29: VALID + sibling provenance conflict (tampered content hash)
# ---------------------------------------------------------------------------


def test_valid_plus_sibling_tampered_result_is_provenance_conflict():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store, salt="2")

    claim1 = _make_claim(1)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.FAILED, native_reason_code="PROVIDER_EXHAUSTED")
    tampered_fields = dict(result1.to_document_fields())
    tampered_fields["native_reason_code"] = "SILENTLY_CHANGED"  # icerik degisti, hash DEGISMEDI -- tamper

    result2 = _make_valid_result(2, asset_hash, benchmark_hash, output_hash)
    claim2 = _make_claim(2)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=PersistedAttemptResultDocument(
            attempt_number=1, attempt_id=result1.attempt_id, document_fields=tampered_fields, create_time=ATTEMPT1_SCHEDULED_UTC
        ),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
        object_store=store,
    )

    assert fe.technical_observation_eligible is True
    assert fe.selected_attempt_id == _attempt_id(2)
    assert fe.selected_evidence_integrity_complete is True
    assert fe.attempt_history_complete is False
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.PROVENANCE_CONFLICT
    assert fe.capture_status == CaptureStatus.VALID_CAPTURE_AVAILABLE
    assert fe.attempt_1_summary.result_state == ResultState.INTEGRITY_INVALID
    assert fe.attempt_1_summary.verification_state == VerificationState.RESULT_CONTENT_HASH_INVALID
    assert fe.attempt_1_summary.result_classification is None
    assert fe.attempt_1_summary.native_reason_code is None


# ---------------------------------------------------------------------------
# Section 30/43: VALID + sibling evidence-integrity failure (EVIDENCE_MISSING)
# ---------------------------------------------------------------------------


def test_valid_plus_sibling_evidence_missing_is_evidence_integrity_failure():
    store = FakeEvidenceObjectStore()
    # attempt1: VALID_CANDIDATE ama evidence HICBIR YERE yuklenmedi -- definitif eksik.
    asset_hash1, benchmark_hash1, output_hash1 = _sha(b"a1"), _sha(b"b1"), _sha(b"c1")
    input_snapshot_hash1 = input_snapshot_sha256_from_hashes(asset_hash1, benchmark_hash1)
    result1 = AttemptResult(
        attempt_id=_attempt_id(1), evaluation_id=_eval_id(), attempt_number=1,
        protocol_version=PROTOCOL, T_session_date=T_DATE, symbol=SYMBOL,
        scheduled_for="2026-09-10T08:00:00+03:00", runtime_fingerprint="rev-x",
        config_gate_result=GateCheckResult.PASS, methodology_gate_result=GateCheckResult.PASS,
        runtime_gate_result=GateCheckResult.PASS, universe_gate_result=GateCheckResult.PASS,
        result_classification=AttemptResultClassification.VALID_CANDIDATE, native_reason_code=None,
        started_at="2026-09-10T08:00:00+03:00", finished_at="2026-09-10T08:00:05+03:00",
        asset_input_sha256=asset_hash1, benchmark_input_sha256=benchmark_hash1,
        input_snapshot_sha256=input_snapshot_hash1, technical_output_sha256=output_hash1,
        asset_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.ASSET_SNAPSHOT, sha256=asset_hash1, object_name="x1", size_bytes=2),
        benchmark_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.BENCHMARK_SNAPSHOT, sha256=benchmark_hash1, object_name="y1", size_bytes=2),
        technical_output_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.TECHNICAL_OUTPUT, sha256=output_hash1, object_name="z1", size_bytes=2),
    )
    claim1 = _make_claim(1)

    asset_hash2, benchmark_hash2, output_hash2 = _upload_evidence(store, salt="clean")
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim2 = _make_claim(2)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
        object_store=store,
    )

    assert fe.capture_status == CaptureStatus.VALID_CAPTURE_AVAILABLE
    assert fe.selected_attempt_id == _attempt_id(2)
    assert fe.selected_evidence_integrity_complete is True
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.EVIDENCE_INTEGRITY_FAILURE
    assert fe.attempt_1_summary.result_state == ResultState.TERMINAL_RESULT  # kayit KENDI ICINDE guvenilir
    assert fe.attempt_1_summary.verification_state == VerificationState.EVIDENCE_MISSING


# ---------------------------------------------------------------------------
# Section 42: transient ObjectStoreError aborts ENTIRE finalization
# ---------------------------------------------------------------------------


class _TransientFailingObjectStore:
    """attempt1'in nesnelerinden herhangi biri sorulduğunda BILINMEYEN/
    gecici bir hata firlatir -- section 42'nin kritik regresyon senaryosu.
    GERCEK implementasyonlarin (`GCSEvidenceObjectStore`) zaten HAM
    `ConnectionError` gibi transport hatalarini `ObjectStoreError`'a
    SARDIGINI (HATA 12N1-F) taklit eder -- selector KENDISI ham stdlib
    istisnalarini DEGIL, ZATEN siniflandirilmis `ObjectStoreError`'i
    yakalar."""

    def put_immutable(self, kind, expected_sha256, raw_bytes):
        raise AssertionError("bu test put_immutable cagirmamali")

    def get_verified(self, kind, expected_sha256):
        raise ObjectStoreError("simulated transient network failure") from ConnectionError("network blip")


def test_transient_object_store_error_aborts_entire_finalization_no_fallthrough():
    store = _TransientFailingObjectStore()
    asset_hash1, benchmark_hash1, output_hash1 = _sha(b"a1"), _sha(b"b1"), _sha(b"c1")
    result1 = _make_valid_result(1, asset_hash1, benchmark_hash1, output_hash1)
    claim1 = _make_claim(1)

    # attempt2 GORUNURDE tamamen temiz VALID olsa BILE -- asla degerlendirilmemeli.
    asset_hash2, benchmark_hash2, output_hash2 = _sha(b"a2"), _sha(b"b2"), _sha(b"c2")
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim2 = _make_claim(2)

    with pytest.raises(FinalizationRetryableError):
        select_final_evaluation(
            context=_make_context(),
            attempt1_claim=_wrap_claim(claim1),
            attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
            attempt2_claim=_wrap_claim(claim2),
            attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
            object_store=store,
        )


# ---------------------------------------------------------------------------
# Section 45: non-valid cases A-D
# ---------------------------------------------------------------------------


def test_nonvalid_A_exclusion_plus_failed():
    claim1, claim2 = _make_claim(1), _make_claim(2)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.EXCLUSION, "EXCLUDED_CONTINUITY")
    result2 = _make_nonvalid_result(2, AttemptResultClassification.FAILED, "PROVIDER_EXHAUSTED")

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
    )

    assert fe.capture_status == CaptureStatus.NO_VALID_CAPTURE_AVAILABLE
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.CLEAN
    assert fe.attempt_history_complete is True
    assert fe.technical_observation_eligible is False


def test_nonvalid_B_all_blocked():
    claim1, claim2 = _make_claim(1), _make_claim(2)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.BLOCKED_CONFIG_DRIFT, "SCORING_CONFIG_HASH_MISMATCH")
    result2 = _make_nonvalid_result(2, AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY, "DEPLOYED_ENGINE_VERSION_MISMATCH")

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
    )

    assert fe.capture_status == CaptureStatus.INFRASTRUCTURE_BLOCKED
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.CLEAN
    assert fe.attempt_history_complete is True


def test_nonvalid_C_mixed_blocked_and_nonblocked():
    claim1, claim2 = _make_claim(1), _make_claim(2)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.BLOCKED_CONFIG_DRIFT, "SCORING_CONFIG_HASH_MISMATCH")
    result2 = _make_nonvalid_result(2, AttemptResultClassification.EXCLUSION, "EXCLUDED_CONTINUITY")

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
    )

    assert fe.capture_status == CaptureStatus.NO_VALID_CAPTURE_AVAILABLE  # NOT hepsi BLOCKED degil
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.CLEAN
    assert fe.attempt_history_complete is True


def test_nonvalid_D_both_claim_no_result():
    claim1, claim2 = _make_claim(1), _make_claim(2)

    fe = _select(attempt1_claim=_wrap_claim(claim1), attempt2_claim=_wrap_claim(claim2))

    assert fe.capture_status == CaptureStatus.NO_VALID_CAPTURE_AVAILABLE
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.AUDIT_INCOMPLETE
    assert fe.attempt_history_complete is False


# ---------------------------------------------------------------------------
# Section 46: attempt2 requirement test matrix
# ---------------------------------------------------------------------------


def test_attempt2_not_required_when_attempt1_valid_before_0900():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash)
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC - timedelta(seconds=1)),  # 08:59:59
        object_store=store,
    )
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID
    assert fe.attempt_history_complete is True  # NOT_REQUIRED + MISSING claim = tam/complete


@pytest.mark.parametrize(
    "create_time_offset",
    [timedelta(0), timedelta(minutes=1)],
    ids=["exactly_0900", "after_0900"],
)
def test_attempt2_required_when_attempt1_valid_at_or_after_0900(create_time_offset):
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash)
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC + create_time_offset),
        object_store=store,
    )
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.REQUIRED


def test_attempt2_required_when_attempt1_exclusion_before_0900():
    claim1 = _make_claim(1)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.EXCLUSION, "EXCLUDED_CONTINUITY")
    fe = _select(attempt1_claim=_wrap_claim(claim1), attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC))
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.REQUIRED


def test_attempt2_required_when_attempt1_failed_before_0900():
    claim1 = _make_claim(1)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.FAILED, "PROVIDER_EXHAUSTED")
    fe = _select(attempt1_claim=_wrap_claim(claim1), attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC))
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.REQUIRED


def test_attempt2_required_when_attempt1_claim_no_result():
    claim1 = _make_claim(1)
    fe = _select(attempt1_claim=_wrap_claim(claim1))
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.REQUIRED


def test_attempt2_indeterminate_when_attempt1_content_hash_invalid():
    claim1 = _make_claim(1)
    result1 = _make_nonvalid_result(1, AttemptResultClassification.FAILED, "PROVIDER_EXHAUSTED")
    tampered = dict(result1.to_document_fields())
    tampered["native_reason_code"] = "CHANGED"
    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=PersistedAttemptResultDocument(
            attempt_number=1, attempt_id=result1.attempt_id, document_fields=tampered, create_time=ATTEMPT1_SCHEDULED_UTC
        ),
    )
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.INDETERMINATE_PROVENANCE


def test_attempt2_indeterminate_when_attempt1_semantic_invalid():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash, omit_technical_output_ref=True)
    claim1 = _make_claim(1)
    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        object_store=store,
    )
    assert fe.attempt_1_summary.verification_state == VerificationState.RESULT_SEMANTIC_INVALID
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.INDETERMINATE_PROVENANCE


def test_attempt2_indeterminate_when_attempt1_result_without_claim():
    result1 = _make_nonvalid_result(1, AttemptResultClassification.FAILED, "PROVIDER_EXHAUSTED")
    fe = _select(attempt1_claim=None, attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC))
    assert fe.attempt_1_summary.verification_state == VerificationState.CLAIM_RELATION_INVALID
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.INDETERMINATE_PROVENANCE


def test_later_gcs_loss_on_trusted_pre_0900_valid_attempt1_does_not_change_requirement():
    """HATA 12N2B1 section 46 son madde -- QUALIFYING_AT_ATTEMPT2_DECISION
    hicbir zaman canli GCS kontrolu YAPMAZ, bu yuzden evidence sonradan
    kaybolsa BILE attempt2 NOT_REQUIRED_FIRST_VALID olarak KALIR."""
    store = FakeEvidenceObjectStore()  # evidence HIC yuklenmedi -- attempt1 GCS'te KAYIP
    asset_hash, benchmark_hash, output_hash = _sha(b"x"), _sha(b"y"), _sha(b"z")
    input_snapshot_hash = input_snapshot_sha256_from_hashes(asset_hash, benchmark_hash)
    result1 = AttemptResult(
        attempt_id=_attempt_id(1), evaluation_id=_eval_id(), attempt_number=1,
        protocol_version=PROTOCOL, T_session_date=T_DATE, symbol=SYMBOL,
        scheduled_for="2026-09-10T08:00:00+03:00", runtime_fingerprint="rev-x",
        config_gate_result=GateCheckResult.PASS, methodology_gate_result=GateCheckResult.PASS,
        runtime_gate_result=GateCheckResult.PASS, universe_gate_result=GateCheckResult.PASS,
        result_classification=AttemptResultClassification.VALID_CANDIDATE, native_reason_code=None,
        started_at="2026-09-10T08:00:00+03:00", finished_at="2026-09-10T08:00:05+03:00",
        asset_input_sha256=asset_hash, benchmark_input_sha256=benchmark_hash,
        input_snapshot_sha256=input_snapshot_hash, technical_output_sha256=output_hash,
        asset_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.ASSET_SNAPSHOT, sha256=asset_hash, object_name="x", size_bytes=1),
        benchmark_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.BENCHMARK_SNAPSHOT, sha256=benchmark_hash, object_name="y", size_bytes=1),
        technical_output_object_ref=EvidenceObjectRef(kind=EvidenceObjectKind.TECHNICAL_OUTPUT, sha256=output_hash, object_name="z", size_bytes=1),
    )
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC - timedelta(seconds=1)),
        object_store=store,
    )
    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID
    # ayrica: attempt1 kendisi artik gecerli bir aday DEGIL (GCS'te kayip).
    assert fe.selected_attempt_id is None
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.EVIDENCE_INTEGRITY_FAILURE


# ---------------------------------------------------------------------------
# Section 47: cutoff test matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "create_time,expected_eligible",
    [
        (CUTOFF_UTC - timedelta(microseconds=1), True),
        (CUTOFF_UTC, False),
        (CUTOFF_UTC + timedelta(minutes=1), False),
    ],
    ids=["just_before_cutoff", "exactly_cutoff", "after_cutoff"],
)
def test_cutoff_boundary(create_time, expected_eligible):
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash)
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, create_time),
        object_store=store,
    )
    assert fe.technical_observation_eligible is expected_eligible


# ---------------------------------------------------------------------------
# Section 48: two valid ordering
# ---------------------------------------------------------------------------


def test_two_valid_ordering_attempt1_earlier_wins():
    store = FakeEvidenceObjectStore()
    asset_hash1, benchmark_hash1, output_hash1 = _upload_evidence(store, salt="1")
    asset_hash2, benchmark_hash2, output_hash2 = _upload_evidence(store, salt="2")
    result1 = _make_valid_result(1, asset_hash1, benchmark_hash1, output_hash1)
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim1, claim2 = _make_claim(1), _make_claim(2)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC - timedelta(seconds=1)),  # before decision -> not_required path irrelevant here since claimed
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=12)),  # 09:12
        object_store=store,
    )
    # attempt1 create_time (08:59:59) < attempt2 create_time (09:12) -> attempt1 wins
    assert fe.selected_attempt_id == _attempt_id(1)


def test_two_valid_ordering_attempt2_earlier_wins():
    store = FakeEvidenceObjectStore()
    asset_hash1, benchmark_hash1, output_hash1 = _upload_evidence(store, salt="1")
    asset_hash2, benchmark_hash2, output_hash2 = _upload_evidence(store, salt="2")
    result1 = _make_valid_result(1, asset_hash1, benchmark_hash1, output_hash1)
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim1, claim2 = _make_claim(1), _make_claim(2)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC + timedelta(minutes=12)),  # 09:12 (late attempt1)
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),  # 09:10
        object_store=store,
    )
    assert fe.selected_attempt_id == _attempt_id(2)


def test_two_valid_same_create_time_lower_attempt_number_wins():
    store = FakeEvidenceObjectStore()
    asset_hash1, benchmark_hash1, output_hash1 = _upload_evidence(store, salt="1")
    asset_hash2, benchmark_hash2, output_hash2 = _upload_evidence(store, salt="2")
    result1 = _make_valid_result(1, asset_hash1, benchmark_hash1, output_hash1)
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim1, claim2 = _make_claim(1), _make_claim(2)
    same_time = DECISION_UTC + timedelta(minutes=10)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, same_time),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, same_time),
        object_store=store,
    )
    assert fe.selected_attempt_id == _attempt_id(1)


# ---------------------------------------------------------------------------
# Section 21: unexpected attempt #2 (executed despite NOT_REQUIRED)
# ---------------------------------------------------------------------------


def test_unexpected_attempt2_executed_despite_not_required_does_not_invalidate_attempt1():
    store = FakeEvidenceObjectStore()
    asset_hash1, benchmark_hash1, output_hash1 = _upload_evidence(store, salt="1")
    result1 = _make_valid_result(1, asset_hash1, benchmark_hash1, output_hash1)
    claim1 = _make_claim(1)

    # attempt1 zaten 08:59:59'da qualifying -- attempt2 NOT_REQUIRED_FIRST_VALID olmali.
    # Ama orkestrasyon YINE DE attempt2'yi calistirdi (bug/race) -- claim/result VAR.
    asset_hash2, benchmark_hash2, output_hash2 = _upload_evidence(store, salt="2")
    result2 = _make_valid_result(2, asset_hash2, benchmark_hash2, output_hash2)
    claim2 = _make_claim(2)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, DECISION_UTC - timedelta(seconds=1)),
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=5)),
        object_store=store,
    )

    assert fe.attempt_2_summary.requirement_state == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID
    assert fe.attempt_2_summary.claim_presence == ClaimPresence.CLAIMED  # yine de islendi
    assert OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED in fe.orchestration_anomaly_codes
    # FIRST_VALID hala otoriter -- attempt1 (daha erken) kazanir.
    assert fe.selected_attempt_id == _attempt_id(1)


# ---------------------------------------------------------------------------
# Semantic/claim-relation edge cases
# ---------------------------------------------------------------------------


def test_valid_candidate_missing_required_object_ref_is_semantic_invalid():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash, omit_technical_output_ref=True)
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        object_store=store,
    )
    assert fe.attempt_1_summary.result_state == ResultState.INTEGRITY_INVALID
    assert fe.attempt_1_summary.verification_state == VerificationState.RESULT_SEMANTIC_INVALID
    assert fe.attempt_1_summary.result_classification is None


def test_claim_identity_mismatch_is_claim_relation_invalid():
    """Claim FIZIKSEL olarak var ama YANLIS bir sembol icin -- dogrudan
    beklenen kimlikle KARSILASTIRILDIGINDA tutarsiz."""
    wrong_claim = _make_claim(1, symbol="GARAN")  # farkli evaluation_id/sembol
    # ama result attempt_id/document ID acisindan attempt1'in kendi (dogru) attempt_id'sine YAZILIYORMUS gibi simule ediyoruz:
    persisted_wrong_claim = PersistedAttemptClaim(
        attempt_number=1, attempt_id=_attempt_id(1), document_fields=wrong_claim.to_document_fields()
    )
    result1 = _make_nonvalid_result(1, AttemptResultClassification.FAILED, "PROVIDER_EXHAUSTED")

    fe = _select(attempt1_claim=persisted_wrong_claim, attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC))
    assert fe.attempt_1_summary.result_state == ResultState.INTEGRITY_INVALID
    assert fe.attempt_1_summary.verification_state == VerificationState.CLAIM_RELATION_INVALID


def test_gate_not_all_pass_on_valid_candidate_stays_trusted_but_does_not_qualify():
    """HATA 12N2B1 duzeltmesi: bu ARTIK RESULT_SEMANTIC_INVALID DEGIL --
    kayit VERIFIED/TERMINAL_RESULT olarak GUVENILIR kalir, yalnizca
    adaylik saglamaz (section 16/23'un ayirdigi semantik-doğrulama vs
    siniflandirma/gate adimlari)."""
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result1 = _make_valid_result(1, asset_hash, benchmark_hash, output_hash, gates_all_pass=False)
    claim1 = _make_claim(1)

    fe = _select(
        attempt1_claim=_wrap_claim(claim1),
        attempt1_result=_wrap_result(result1, ATTEMPT1_SCHEDULED_UTC),
        object_store=store,
    )
    assert fe.attempt_1_summary.result_state == ResultState.TERMINAL_RESULT
    assert fe.attempt_1_summary.verification_state == VerificationState.VERIFIED
    assert fe.attempt_1_summary.result_classification == "VALID_CANDIDATE"
    assert fe.technical_observation_eligible is False
    assert fe.selected_attempt_id is None
    assert fe.evaluation_integrity_status == EvaluationIntegrityStatus.AUDIT_INCOMPLETE  # attempt2 hic yok


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_repeat_produces_identical_content_hash():
    store = FakeEvidenceObjectStore()
    asset_hash, benchmark_hash, output_hash = _upload_evidence(store)
    result2 = _make_valid_result(2, asset_hash, benchmark_hash, output_hash)
    claim2 = _make_claim(2)

    fe_a = _select(
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
        object_store=store,
    )
    fe_b = _select(
        attempt2_claim=_wrap_claim(claim2),
        attempt2_result=_wrap_result(result2, DECISION_UTC + timedelta(minutes=10)),
        object_store=store,
    )
    assert fe_a.record_content_sha256 == fe_b.record_content_sha256
    assert fe_a.to_document_fields() == fe_b.to_document_fields()


# ---------------------------------------------------------------------------
# Boundary: no dependency on provider/engine/Firestore
# ---------------------------------------------------------------------------


def test_selector_module_imports_no_provider_engine_or_firestore():
    import ast
    import inspect

    import app.research.final_evaluation_selector as selector_module
    import app.research.final_evaluation_models as models_module

    forbidden_substrings = (
        "BistProvider",
        "yfinance",
        "TechnicalAnalysisEngine",
        "BenchmarkService",
        "benchmark_service",
        "TechnicalAnalysisRepository",
        "firebase_admin",
        "firestore",
        "DocumentReference",
    )
    for module in (selector_module, models_module):
        source = inspect.getsource(module)
        for forbidden in forbidden_substrings:
            assert forbidden not in source, f"{module.__name__} imports/references forbidden symbol: {forbidden}"
        ast.parse(source)  # sanity: hala gecerli Python
