"""HATA 12N3C2-B2-D — `app/research/identity_gates.py` saf karşılaştırma
katmanı testleri (Firestore/dosya sistemi/ortam erişimi olmadan)."""

import pytest

from app.research.attempt_models import GateCheckResult
from app.research.attempt_reason_codes import (
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
)
from app.research.identity_gates import (
    IdentityGateEvaluation,
    evaluate_config_gate,
    evaluate_methodology_gate,
    evaluate_runtime_gate,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


# ---------------------------------------------------------------------------
# IdentityGateEvaluation invariant
# ---------------------------------------------------------------------------


def test_pass_cannot_carry_a_reason_code():
    with pytest.raises(ValueError):
        IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code="SOMETHING")


@pytest.mark.parametrize("bad_reason", [None, ""])
def test_fail_must_carry_a_non_empty_reason_code(bad_reason):
    with pytest.raises(ValueError):
        IdentityGateEvaluation(result=GateCheckResult.FAIL, reason_code=bad_reason)


def test_pass_with_none_reason_is_valid():
    evaluation = IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code=None)
    assert evaluation.reason_code is None


# ---------------------------------------------------------------------------
# CONFIG gate (section 25)
# ---------------------------------------------------------------------------


def test_config_gate_equal_hashes_pass():
    evaluation = evaluate_config_gate(HASH_A, HASH_A)
    assert evaluation.result == GateCheckResult.PASS
    assert evaluation.reason_code is None


def test_config_gate_different_hashes_fail():
    evaluation = evaluate_config_gate(HASH_A, HASH_B)
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == SCORING_CONFIG_HASH_MISMATCH


@pytest.mark.parametrize(
    "expected,observed",
    [
        ("A" * 64, HASH_A),
        (HASH_A, "A" * 64),
        ("a" * 63, HASH_A),
        (HASH_A, "a" * 65),
        ("g" * 64, HASH_A),
        ("", HASH_A),
        (None, HASH_A),
    ],
)
def test_config_gate_rejects_malformed_input(expected, observed):
    with pytest.raises(Exception):
        evaluate_config_gate(expected, observed)


# ---------------------------------------------------------------------------
# METHODOLOGY gate (section 26)
# ---------------------------------------------------------------------------


def test_methodology_gate_equal_fingerprints_pass():
    evaluation = evaluate_methodology_gate(HASH_A, HASH_A)
    assert evaluation.result == GateCheckResult.PASS
    assert evaluation.reason_code is None


def test_methodology_gate_different_fingerprints_fail():
    evaluation = evaluate_methodology_gate(HASH_A, HASH_B)
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH


@pytest.mark.parametrize(
    "expected,observed",
    [
        ("A" * 64, HASH_A),
        (HASH_A, "g" * 64),
        ("a" * 63, HASH_A),
        ("", HASH_A),
        (None, HASH_A),
    ],
)
def test_methodology_gate_rejects_malformed_input(expected, observed):
    with pytest.raises(Exception):
        evaluate_methodology_gate(expected, observed)


# ---------------------------------------------------------------------------
# RUNTIME gate (section 27)
# ---------------------------------------------------------------------------


def test_runtime_gate_same_fingerprint_passes():
    evaluation = evaluate_runtime_gate("proj/svc/rev", "proj/svc/rev")
    assert evaluation.result == GateCheckResult.PASS
    assert evaluation.reason_code is None


def test_runtime_gate_different_project_fails():
    evaluation = evaluate_runtime_gate("proj-a/svc/rev", "proj-b/svc/rev")
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == RUNTIME_IDENTITY_UNAUTHORIZED


def test_runtime_gate_different_service_fails():
    evaluation = evaluate_runtime_gate("proj/svc-a/rev", "proj/svc-b/rev")
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == RUNTIME_IDENTITY_UNAUTHORIZED


def test_runtime_gate_different_revision_fails():
    evaluation = evaluate_runtime_gate("proj/svc/rev-a", "proj/svc/rev-b")
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == RUNTIME_IDENTITY_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Reason codes contain no raw exception text / no PII (section 33)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evaluation",
    [
        evaluate_config_gate(HASH_A, HASH_B),
        evaluate_methodology_gate(HASH_A, HASH_B),
        evaluate_runtime_gate("proj/svc/rev-a", "proj/svc/rev-b"),
    ],
)
def test_fail_reason_codes_are_stable_categorical_constants_only(evaluation):
    assert evaluation.reason_code in {
        SCORING_CONFIG_HASH_MISMATCH,
        METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
        RUNTIME_IDENTITY_UNAUTHORIZED,
    }
    forbidden_substrings = ("http://", "https://", "Traceback", "@")
    for forbidden in forbidden_substrings:
        assert forbidden not in evaluation.reason_code
