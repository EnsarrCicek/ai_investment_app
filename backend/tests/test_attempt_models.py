"""HATA 12N2A — `app/research/attempt_models.py` saf model doğrulama
testleri (Firestore/GCS erişimi olmadan): object-ref tutarlılığı,
input_snapshot_sha256 birleştirici tutarlılığı, içerik-hash türetimi,
ve claim/result şemalarının kilitlenen alan setleriyle sınırlı kalması.
"""

import pytest

from app.research.attempt_models import (
    AttemptClaim,
    AttemptResult,
    AttemptResultClassification,
    GateCheckResult,
    ProviderFetchMetadata,
)
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id
from app.research.evidence_models import EvidenceIntegrityError, EvidenceObjectKind, EvidenceObjectRef
from app.research.evidence_serialization import input_snapshot_sha256_from_hashes

_EVAL_ID = compute_evaluation_id("TECHNICAL_V1_PROTOCOL_V1", "2026-09-09", "AKBNK")
_ATTEMPT_ID = compute_attempt_id(_EVAL_ID, 1)

LOCK_A = "a" * 64
LOCK_B = "b" * 64

_BASE_RESULT_KWARGS = dict(
    attempt_id=_ATTEMPT_ID,
    evaluation_id=_EVAL_ID,
    attempt_number=1,
    protocol_version="TECHNICAL_V1_PROTOCOL_V1",
    T_session_date="2026-09-09",
    symbol="AKBNK",
    scheduled_for="2026-09-09T08:00:00+03:00",
    runtime_fingerprint="rev-x",
    activation_lock_id=LOCK_A,
    config_gate_result=GateCheckResult.PASS,
    methodology_gate_result=GateCheckResult.PASS,
    runtime_gate_result=GateCheckResult.PASS,
    universe_gate_result=GateCheckResult.PASS,
    started_at="2026-09-09T08:00:00+03:00",
    finished_at="2026-09-09T08:00:05+03:00",
)


def _asset_ref(sha256: str) -> EvidenceObjectRef:
    return EvidenceObjectRef(kind=EvidenceObjectKind.ASSET_SNAPSHOT, sha256=sha256, object_name="x", size_bytes=10)


def _benchmark_ref(sha256: str) -> EvidenceObjectRef:
    return EvidenceObjectRef(kind=EvidenceObjectKind.BENCHMARK_SNAPSHOT, sha256=sha256, object_name="y", size_bytes=5)


# ---------------------------------------------------------------------------
# AttemptClaim -- kimlik/alan-seti doğrulama
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_attempt_number", [0, 3, -1, "1", 1.0, True, False])
def test_attempt_claim_rejects_invalid_attempt_number(bad_attempt_number):
    with pytest.raises(EvidenceIntegrityError):
        AttemptClaim(
            attempt_id=_ATTEMPT_ID,
            evaluation_id=_EVAL_ID,
            attempt_number=bad_attempt_number,
            protocol_version="TECHNICAL_V1_PROTOCOL_V1",
            T_session_date="2026-09-09",
            symbol="AKBNK",
            claimed_by_runtime="rev-x",
            activation_lock_id=LOCK_A,
        )


def test_attempt_claim_rejects_empty_symbol():
    with pytest.raises(EvidenceIntegrityError):
        AttemptClaim(
            attempt_id=_ATTEMPT_ID,
            evaluation_id=_EVAL_ID,
            attempt_number=1,
            protocol_version="TECHNICAL_V1_PROTOCOL_V1",
            T_session_date="2026-09-09",
            symbol="",
            claimed_by_runtime="rev-x",
            activation_lock_id=LOCK_A,
        )


def test_attempt_claim_document_fields_exclude_claimed_by_runtime_from_identity():
    claim = AttemptClaim(
        attempt_id=_ATTEMPT_ID,
        evaluation_id=_EVAL_ID,
        attempt_number=1,
        protocol_version="TECHNICAL_V1_PROTOCOL_V1",
        T_session_date="2026-09-09",
        symbol="AKBNK",
        claimed_by_runtime="rev-x",
        activation_lock_id=LOCK_A,
    )
    assert "claimed_by_runtime" not in claim.identity_fields()
    assert "claimed_by_runtime" in claim.to_document_fields()
    assert "activation_lock_id" not in claim.identity_fields()
    assert "activation_lock_id" in claim.to_document_fields()


def test_attempt_claim_round_trips_through_document_fields():
    claim = AttemptClaim(
        attempt_id=_ATTEMPT_ID,
        evaluation_id=_EVAL_ID,
        attempt_number=1,
        protocol_version="TECHNICAL_V1_PROTOCOL_V1",
        T_session_date="2026-09-09",
        symbol="AKBNK",
        claimed_by_runtime="rev-x",
        activation_lock_id=LOCK_A,
    )
    reconstructed = AttemptClaim.from_document_fields(claim.to_document_fields())
    assert reconstructed == claim


# ---------------------------------------------------------------------------
# AttemptClaim -- activation_lock_id ZORUNLU (HATA 12N3C2-B2-C section 3/22)
# ---------------------------------------------------------------------------


def _base_claim_kwargs() -> dict:
    return dict(
        attempt_id=_ATTEMPT_ID,
        evaluation_id=_EVAL_ID,
        attempt_number=1,
        protocol_version="TECHNICAL_V1_PROTOCOL_V1",
        T_session_date="2026-09-09",
        symbol="AKBNK",
        claimed_by_runtime="rev-x",
    )


def test_attempt_claim_requires_activation_lock_id_missing_raises_type_error():
    with pytest.raises(TypeError):
        AttemptClaim(**_base_claim_kwargs())  # activation_lock_id hic verilmedi -- default/None YOK


@pytest.mark.parametrize(
    "bad_lock",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12345],
    ids=["uppercase", "63_chars", "65_chars", "non_hex", "empty", "none", "not_a_string"],
)
def test_attempt_claim_rejects_malformed_activation_lock_id(bad_lock):
    with pytest.raises(Exception):
        AttemptClaim(**_base_claim_kwargs(), activation_lock_id=bad_lock)


def test_attempt_claim_from_document_fields_requires_activation_lock_id():
    claim = AttemptClaim(**_base_claim_kwargs(), activation_lock_id=LOCK_A)
    doc = claim.to_document_fields()
    del doc["activation_lock_id"]
    with pytest.raises(KeyError):
        AttemptClaim.from_document_fields(doc)


def test_two_claims_differing_only_in_activation_lock_id_have_different_document_content_but_same_attempt_id():
    claim_a = AttemptClaim(**_base_claim_kwargs(), activation_lock_id=LOCK_A)
    claim_b = AttemptClaim(**_base_claim_kwargs(), activation_lock_id=LOCK_B)

    assert claim_a.attempt_id == claim_b.attempt_id
    assert claim_a.to_document_fields() != claim_b.to_document_fields()
    assert claim_a.identity_fields() == claim_b.identity_fields()


# ---------------------------------------------------------------------------
# AttemptResult -- activation_lock_id ZORUNLU (HATA 12N3C2-B2-C section 4/23)
# ---------------------------------------------------------------------------


def test_attempt_result_requires_activation_lock_id_missing_raises_type_error():
    kwargs = dict(_BASE_RESULT_KWARGS)
    del kwargs["activation_lock_id"]
    with pytest.raises(TypeError):
        AttemptResult(
            result_classification=AttemptResultClassification.FAILED,
            native_reason_code="PROVIDER_EXHAUSTED",
            **kwargs,
        )


@pytest.mark.parametrize(
    "bad_lock",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12345],
    ids=["uppercase", "63_chars", "65_chars", "non_hex", "empty", "none", "not_a_string"],
)
def test_attempt_result_rejects_malformed_activation_lock_id(bad_lock):
    kwargs = dict(_BASE_RESULT_KWARGS)
    kwargs["activation_lock_id"] = bad_lock
    with pytest.raises(Exception):
        AttemptResult(
            result_classification=AttemptResultClassification.FAILED,
            native_reason_code="PROVIDER_EXHAUSTED",
            **kwargs,
        )


def test_attempt_result_from_document_fields_requires_activation_lock_id():
    result = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    doc = result.to_document_fields()
    del doc["activation_lock_id"]
    with pytest.raises(KeyError):
        AttemptResult.from_document_fields(doc)


def test_two_results_differing_only_in_activation_lock_id_have_same_attempt_id_but_different_content_hash():
    kwargs_a = dict(_BASE_RESULT_KWARGS)
    kwargs_b = dict(_BASE_RESULT_KWARGS)
    kwargs_b["activation_lock_id"] = LOCK_B

    result_a = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **kwargs_a,
    )
    result_b = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **kwargs_b,
    )
    assert result_a.attempt_id == result_b.attempt_id
    assert result_a.content_sha256 != result_b.content_sha256


# ---------------------------------------------------------------------------
# AttemptResult -- object-ref tutarlılığı (HATA 12N2A section 13)
# ---------------------------------------------------------------------------


def test_attempt_result_rejects_hash_without_object_ref():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=None,
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_rejects_object_ref_without_hash():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256=None,
            asset_object_ref=_asset_ref("a" * 64),
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_rejects_object_ref_kind_mismatch():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=_benchmark_ref("a" * 64),  # yanlis kind
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_rejects_object_ref_hash_mismatch():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=_asset_ref("b" * 64),  # farkli hash
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_accepts_consistent_object_ref():
    result = AttemptResult(
        result_classification=AttemptResultClassification.VALID_CANDIDATE,
        native_reason_code=None,
        asset_input_sha256="a" * 64,
        asset_object_ref=_asset_ref("a" * 64),
        **_BASE_RESULT_KWARGS,
    )
    assert result.asset_input_sha256 == "a" * 64


# ---------------------------------------------------------------------------
# AttemptResult -- input_snapshot_sha256 birleştirici tutarlılığı
# (HATA 12N2A section 14)
# ---------------------------------------------------------------------------


def test_attempt_result_requires_input_snapshot_hash_when_both_sides_present():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=_asset_ref("a" * 64),
            benchmark_input_sha256="c" * 64,
            benchmark_object_ref=_benchmark_ref("c" * 64),
            input_snapshot_sha256=None,
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_rejects_wrong_input_snapshot_hash():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=_asset_ref("a" * 64),
            benchmark_input_sha256="c" * 64,
            benchmark_object_ref=_benchmark_ref("c" * 64),
            input_snapshot_sha256="d" * 64,  # yanlis -- gercek birlestiriciden gelmiyor
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_rejects_input_snapshot_hash_with_only_one_side_present():
    with pytest.raises(EvidenceIntegrityError):
        AttemptResult(
            result_classification=AttemptResultClassification.VALID_CANDIDATE,
            native_reason_code=None,
            asset_input_sha256="a" * 64,
            asset_object_ref=_asset_ref("a" * 64),
            benchmark_input_sha256=None,
            input_snapshot_sha256="d" * 64,  # benchmark tarafi yokken bu ASLA olmamali
            **_BASE_RESULT_KWARGS,
        )


def test_attempt_result_accepts_correct_combined_input_snapshot_hash():
    asset_hash = "a" * 64
    benchmark_hash = "c" * 64
    combined = input_snapshot_sha256_from_hashes(asset_hash, benchmark_hash)

    result = AttemptResult(
        result_classification=AttemptResultClassification.VALID_CANDIDATE,
        native_reason_code=None,
        asset_input_sha256=asset_hash,
        asset_object_ref=_asset_ref(asset_hash),
        benchmark_input_sha256=benchmark_hash,
        benchmark_object_ref=_benchmark_ref(benchmark_hash),
        input_snapshot_sha256=combined,
        **_BASE_RESULT_KWARGS,
    )
    assert result.input_snapshot_sha256 == combined


def test_attempt_result_allows_all_hashes_none_for_capture_failed():
    """CAPTURE_FAILED/BLOCKED_* icin girdi anlik-goruntusu HIC yok --
    ucu de None birakilabilmeli, sahte bir snapshot UYDURULMAZ."""
    result = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    assert result.asset_input_sha256 is None
    assert result.benchmark_input_sha256 is None
    assert result.input_snapshot_sha256 is None
    assert result.technical_output_sha256 is None


# ---------------------------------------------------------------------------
# İçerik-hash türetimi
# ---------------------------------------------------------------------------


def test_attempt_result_content_sha256_is_not_a_stored_field():
    result = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    assert "attempt_result_content_sha256" not in result.to_content_fields()
    assert "attempt_result_content_sha256" in result.to_document_fields()


def test_attempt_result_content_sha256_deterministic():
    result_a = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    result_b = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    assert result_a.content_sha256 == result_b.content_sha256


def test_attempt_result_content_sha256_sensitive_to_field_change():
    result_a = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="PROVIDER_EXHAUSTED",
        **_BASE_RESULT_KWARGS,
    )
    result_b = AttemptResult(
        result_classification=AttemptResultClassification.FAILED,
        native_reason_code="DIFFERENT_REASON",
        **_BASE_RESULT_KWARGS,
    )
    assert result_a.content_sha256 != result_b.content_sha256


def test_attempt_result_round_trips_through_document_fields():
    result = AttemptResult(
        result_classification=AttemptResultClassification.VALID_CANDIDATE,
        native_reason_code=None,
        asset_input_sha256="a" * 64,
        asset_object_ref=_asset_ref("a" * 64),
        provider_fetch=ProviderFetchMetadata(
            provider_name="yahoo_finance",
            requested_symbol="AKBNK",
            requested_period_or_range="6mo",
            fetch_started_at="2026-09-09T08:00:00+03:00",
            fetch_completed_at="2026-09-09T08:00:03+03:00",
            provider_result_status="OK",
        ),
        **_BASE_RESULT_KWARGS,
    )
    reconstructed = AttemptResult.from_document_fields(result.to_document_fields())
    assert reconstructed == result
    assert reconstructed.content_sha256 == result.content_sha256


def test_no_cutoff_or_eligibility_fields_present_anywhere():
    """HATA 12N2A section 10/25: `before_cutoff`/`technical_observation_
    eligible`/`primary_outcome_eligible` bu modelde HICBIR YERDE olmamali."""
    result = AttemptResult(
        result_classification=AttemptResultClassification.VALID_CANDIDATE,
        native_reason_code=None,
        **_BASE_RESULT_KWARGS,
    )
    forbidden = {"before_cutoff", "after_cutoff", "technical_observation_eligible", "primary_outcome_eligible"}
    assert forbidden.isdisjoint(result.to_document_fields().keys())
    assert not hasattr(result, "before_cutoff")
    assert not hasattr(result, "technical_observation_eligible")
