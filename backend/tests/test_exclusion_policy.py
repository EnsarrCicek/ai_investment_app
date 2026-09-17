"""HATA 12N3C2-E2-A/E2-A1 — `app/research/exclusion_policy.py` saf
karşılaştırma katmanı testleri (Firestore/dosya sistemi/ortam erişimi
olmadan)."""

import inspect
import math

import pytest

from app.research.attempt_reason_codes import TECHNICAL_SCORE_NONE
from app.research.evidence_models import EvidenceIntegrityError
from app.research.exclusion_policy import ExclusionEvaluation, evaluate_technical_score_exclusion


# ---------------------------------------------------------------------------
# ExclusionEvaluation invariant
# ---------------------------------------------------------------------------


def test_excluded_true_requires_non_empty_reason_code():
    with pytest.raises(ValueError):
        ExclusionEvaluation(excluded=True, reason_code=None)
    with pytest.raises(ValueError):
        ExclusionEvaluation(excluded=True, reason_code="")


def test_excluded_false_cannot_carry_a_reason_code():
    with pytest.raises(ValueError):
        ExclusionEvaluation(excluded=False, reason_code="SOMETHING")


def test_excluded_false_with_none_reason_is_valid():
    evaluation = ExclusionEvaluation(excluded=False, reason_code=None)
    assert evaluation.reason_code is None


# ---------------------------------------------------------------------------
# technical_score is None (section 5)
# ---------------------------------------------------------------------------


def test_none_score_is_excluded_with_technical_score_none_reason():
    evaluation = evaluate_technical_score_exclusion(None)
    assert evaluation.excluded is True
    assert evaluation.reason_code == TECHNICAL_SCORE_NONE


# ---------------------------------------------------------------------------
# Zero is valid (section 6) -- LOAD-BEARING
# ---------------------------------------------------------------------------


def test_zero_score_is_not_excluded():
    evaluation = evaluate_technical_score_exclusion(0.0)
    assert evaluation.excluded is False
    assert evaluation.reason_code is None


def test_negative_zero_score_is_not_excluded():
    """`-0.0` da finite'dır -- ayrı bir edge-case olarak da doğrulanır."""
    evaluation = evaluate_technical_score_exclusion(-0.0)
    assert evaluation.excluded is False
    assert evaluation.reason_code is None


def test_evaluator_does_not_use_truthiness_on_score():
    """Section 6: `if not technical_score` KULLANILMAMALI -- kaynak
    incelemesiyle doğrudan doğrulanır (0.0 Python'da falsy'dir, bu yüzden
    yalnızca davranışsal test YETERLİ DEĞİLDİR, kaynak da kontrol edilir)."""
    import app.research.exclusion_policy as module

    source = inspect.getsource(module.evaluate_technical_score_exclusion)
    assert "if not technical_score" not in source
    assert "if technical_score:" not in source


# ---------------------------------------------------------------------------
# Valid finite scores (section 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("score", [0.0, 42.5, -42.5, 100.0, -100.0, 0.01, -0.01])
def test_representative_finite_scores_are_not_excluded(score):
    evaluation = evaluate_technical_score_exclusion(score)
    assert evaluation.excluded is False
    assert evaluation.reason_code is None


def test_integer_finite_score_is_accepted():
    """Model sözleşmesi `float | None` -- ama saf fonksiyon, Pydantic'in
    KENDİ int->float coercion'ı ile tutarlı olarak int bir değeri de
    finite bir sayı olarak kabul eder (bool HARİÇ, ayrı test edilir)."""
    evaluation = evaluate_technical_score_exclusion(42)
    assert evaluation.excluded is False
    assert evaluation.reason_code is None


# ---------------------------------------------------------------------------
# Malformed / non-finite input (section 8) -- LOAD-BEARING
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed",
    [float("nan"), float("inf"), float("-inf"), True, False, "42.5", object(), [42.5]],
    ids=["nan", "inf", "neg_inf", "true", "false", "numeric_string", "object", "list"],
)
def test_malformed_input_fails_loudly_not_as_technical_score_none(malformed):
    with pytest.raises(EvidenceIntegrityError):
        evaluate_technical_score_exclusion(malformed)


# ---------------------------------------------------------------------------
# Data-quality/precedence isolation (section 9/10)
# ---------------------------------------------------------------------------


def test_evaluator_signature_accepts_only_technical_score():
    sig = inspect.signature(evaluate_technical_score_exclusion)
    assert list(sig.parameters.keys()) == ["technical_score"]


def test_module_does_not_import_data_quality_module():
    import app.research.exclusion_policy as module

    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("data_quality" in line.lower() for line in import_lines)
    assert not hasattr(module, "DataQualityError")
    assert not hasattr(module, "check_data_quality")


def test_module_never_constructs_attempt_result_or_classification():
    import app.research.exclusion_policy as module

    source = inspect.getsource(module)
    assert "AttemptResult(" not in source
    assert "AttemptResultClassification" not in source


def test_module_performs_no_io():
    import app.research.exclusion_policy as module

    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden_substrings = ("firestore", "requests", "httpx", "yfinance", "market_data", "os.environ")
    for line in import_lines:
        lowered = line.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"yasaklı bağımlılık bulundu: {line!r}"
