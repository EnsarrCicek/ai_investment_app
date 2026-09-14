"""HATA 12N2B1 — `app/research/final_evaluation_models.py` saf model
doğrulama testleri (Firestore/GCS erişimi olmadan)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.research.evidence_identity import compute_evaluation_id
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    AttemptSummary,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalEvaluation,
    FinalizationContext,
    OrchestrationAnomalyCode,
    PersistedAttemptClaim,
    PersistedAttemptResultDocument,
    ResultState,
    VerificationState,
)

PROTOCOL = "TECHNICAL_V1_PROTOCOL_V1"
T_DATE = "2026-09-09"
SYMBOL = "AKBNK"
DECISION = datetime(2026, 9, 10, 6, 0, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 10, 6, 45, 0, tzinfo=timezone.utc)


def _base_context_kwargs():
    return dict(
        evaluation_id=compute_evaluation_id(PROTOCOL, T_DATE, SYMBOL),
        protocol_version=PROTOCOL,
        protocol_sha256="a" * 64,
        methodology_git_commit="c1f0d439d40a709d55007bd8ff34b4a8b2347f95",
        freeze_manifest_sha256="b" * 64,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        T_session_date=T_DATE,
        symbol=SYMBOL,
        E1_date="2026-09-10",
        attempt2_decision_time_utc=DECISION,
        formal_cutoff_utc=CUTOFF,
    )


# ---------------------------------------------------------------------------
# FinalizationContext
# ---------------------------------------------------------------------------


def test_context_accepts_valid_inputs():
    ctx = FinalizationContext(**_base_context_kwargs())
    assert ctx.formal_cutoff_timestamp_str() == "2026-09-10T06:45:00+00:00"


def test_context_rejects_evaluation_id_not_matching_recomputation():
    kwargs = {**_base_context_kwargs(), "evaluation_id": "d" * 64}
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs)


def test_context_rejects_naive_decision_time():
    kwargs = {**_base_context_kwargs(), "attempt2_decision_time_utc": datetime(2026, 9, 10, 6, 0, 0)}
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs)


def test_context_rejects_non_utc_offset():
    kwargs = {
        **_base_context_kwargs(),
        "attempt2_decision_time_utc": datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone(timedelta(hours=3))),
    }
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs)


def test_context_rejects_decision_not_strictly_before_cutoff():
    kwargs = {**_base_context_kwargs(), "attempt2_decision_time_utc": CUTOFF}
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs)

    kwargs2 = {**_base_context_kwargs(), "attempt2_decision_time_utc": CUTOFF + timedelta(minutes=1)}
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs2)


@pytest.mark.parametrize("bad_date", ["20260909", "2026-9-9", "2026-W37-4", " 2026-09-09"])
def test_context_rejects_noncanonical_t_session_date(bad_date):
    kwargs = {**_base_context_kwargs(), "T_session_date": bad_date}
    with pytest.raises(ValueError):
        FinalizationContext(**kwargs)


def test_context_formal_cutoff_timestamp_str_is_utc_and_isoformat():
    ctx = FinalizationContext(**_base_context_kwargs())
    assert ctx.formal_cutoff_timestamp_str().endswith("+00:00")


# ---------------------------------------------------------------------------
# PersistedAttemptClaim / PersistedAttemptResultDocument
# ---------------------------------------------------------------------------


def test_persisted_claim_rejects_invalid_attempt_number():
    with pytest.raises(ValueError):
        PersistedAttemptClaim(attempt_number=3, attempt_id="a" * 64, document_fields={})


def test_persisted_claim_rejects_non_dict_document_fields():
    with pytest.raises(ValueError):
        PersistedAttemptClaim(attempt_number=1, attempt_id="a" * 64, document_fields="not-a-dict")


def test_persisted_result_document_rejects_naive_create_time():
    with pytest.raises(ValueError):
        PersistedAttemptResultDocument(
            attempt_number=1, attempt_id="a" * 64, document_fields={}, create_time=datetime(2026, 9, 10, 6, 0, 0)
        )


def test_persisted_result_document_rejects_non_utc_create_time():
    with pytest.raises(ValueError):
        PersistedAttemptResultDocument(
            attempt_number=1,
            attempt_id="a" * 64,
            document_fields={},
            create_time=datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone(timedelta(hours=3))),
        )


def test_persisted_result_document_accepts_utc_create_time():
    doc = PersistedAttemptResultDocument(
        attempt_number=1, attempt_id="a" * 64, document_fields={"x": 1}, create_time=DECISION
    )
    assert doc.create_time == DECISION


# ---------------------------------------------------------------------------
# AttemptSummary
# ---------------------------------------------------------------------------


def test_attempt_summary_to_content_fields_shape():
    summary = AttemptSummary(
        attempt_number=1,
        attempt_id="a" * 64,
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NO_RESULT,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )
    fields = summary.to_content_fields()
    assert fields["requirement_state"] == "REQUIRED"
    assert fields["claim_presence"] == "MISSING"
    assert fields["result_state"] == "NO_RESULT"
    assert fields["verification_state"] == "NOT_APPLICABLE"
    assert "attempt_id" in fields and "attempt_number" in fields


# ---------------------------------------------------------------------------
# FinalEvaluation -- content hash derivation
# ---------------------------------------------------------------------------


def _make_summary(attempt_number: int) -> AttemptSummary:
    return AttemptSummary(
        attempt_number=attempt_number,
        attempt_id=f"{'a' if attempt_number == 1 else 'b'}" * 64,
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NO_RESULT,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )


def _make_final_evaluation(anomaly_codes=frozenset()) -> FinalEvaluation:
    return FinalEvaluation(
        evaluation_id=compute_evaluation_id(PROTOCOL, T_DATE, SYMBOL),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        symbol=SYMBOL,
        protocol_sha256="a" * 64,
        methodology_git_commit="c1f0d439d40a709d55007bd8ff34b4a8b2347f95",
        freeze_manifest_sha256="b" * 64,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        E1_date="2026-09-10",
        formal_cutoff_timestamp="2026-09-10T06:45:00+00:00",
        capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
        evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
        technical_observation_eligible=False,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=_make_summary(1),
        attempt_2_summary=_make_summary(2),
        orchestration_anomaly_codes=anomaly_codes,
    )


def test_final_evaluation_record_content_sha256_not_in_content_fields():
    fe = _make_final_evaluation()
    assert "record_content_sha256" not in fe.to_content_fields()
    assert "record_content_sha256" in fe.to_document_fields()


def test_final_evaluation_record_content_sha256_deterministic():
    fe_a = _make_final_evaluation()
    fe_b = _make_final_evaluation()
    assert fe_a.record_content_sha256 == fe_b.record_content_sha256


def test_final_evaluation_record_content_sha256_sensitive_to_field_change():
    fe_a = _make_final_evaluation()
    fe_b = _make_final_evaluation(anomaly_codes=frozenset({OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED}))
    assert fe_a.record_content_sha256 != fe_b.record_content_sha256


def test_final_evaluation_anomaly_codes_serialize_as_sorted_list_regardless_of_set_order():
    """HATA 12N2B1 section 37/41: bir `frozenset`'in kendi iterasyon sırası
    deterministik DEĞİLDİR -- `to_content_fields()` HER ZAMAN sıralı bir
    liste üretmeli."""
    codes = frozenset({OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED})
    fe = _make_final_evaluation(anomaly_codes=codes)
    fields = fe.to_content_fields()
    assert fields["orchestration_anomaly_codes"] == ["ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED"]
    assert isinstance(fields["orchestration_anomaly_codes"], list)


def test_final_evaluation_no_future_outcome_fields_present():
    fe = _make_final_evaluation()
    forbidden = {
        "hit_rate",
        "return",
        "e5",
        "e10",
        "e20",
        "performance",
        "finalized_at",
        "winning_create_time",
        "create_time",
    }
    content_keys = {k.lower() for k in fe.to_content_fields()}
    assert forbidden.isdisjoint(content_keys)
