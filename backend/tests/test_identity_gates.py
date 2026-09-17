"""HATA 12N3C2-B2-D / E1-R3 — `app/research/identity_gates.py` saf
karşılaştırma katmanı testleri (Firestore/dosya sistemi/ortam erişimi
olmadan; UNIVERSE kapısı testleri gerçek, doğrulanmış `TrustedTechnicalV1
Protocol.frozen_symbols`'ı kullanır -- elle ikinci bir 100-sembol fixture
İCAT EDİLMEZ)."""

import inspect

import pytest

from app.research.attempt_models import GateCheckResult
from app.research.attempt_reason_codes import (
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
    SYMBOL_NOT_IN_FROZEN_UNIVERSE,
)
from app.research.evidence_models import EvidenceIntegrityError
from app.research.identity_gates import (
    IdentityGateEvaluation,
    evaluate_config_gate,
    evaluate_methodology_gate,
    evaluate_runtime_gate,
    evaluate_universe_gate,
)
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol

LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"

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


# ---------------------------------------------------------------------------
# UNIVERSE gate (HATA 12N3C2-E1-R3)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trusted_protocol():
    return load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)


def test_universe_gate_real_frozen_member_passes(trusted_protocol):
    evaluation = evaluate_universe_gate(trusted_protocol.frozen_symbols, "THYAO")
    assert evaluation.result == GateCheckResult.PASS
    assert evaluation.reason_code is None


def test_universe_gate_another_real_frozen_member_passes(trusted_protocol):
    # Fixture'dan (bellekten TAHMİN EDİLMEDEN) gerçek bir başka üye alınır.
    another_member = next(iter(trusted_protocol.frozen_symbols - {"THYAO"}))
    evaluation = evaluate_universe_gate(trusted_protocol.frozen_symbols, another_member)
    assert evaluation.result == GateCheckResult.PASS
    assert evaluation.reason_code is None


def test_universe_gate_canonical_nonmember_fails(trusted_protocol):
    nonmember = "FAKE"
    assert nonmember not in trusted_protocol.frozen_symbols
    evaluation = evaluate_universe_gate(trusted_protocol.frozen_symbols, nonmember)
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == SYMBOL_NOT_IN_FROZEN_UNIVERSE


@pytest.mark.parametrize(
    "malformed_form",
    ["thyao", "THYAO.IS", " THYAO", "THYAO "],
    ids=["lowercase", "provider_suffixed", "leading_ws", "trailing_ws"],
)
def test_universe_gate_performs_no_normalization(trusted_protocol, malformed_form):
    """Section 20: bilinen gerçek bir üyenin küçük-harf/`.IS`-son-ekli/
    boşluk-dolgulu biçimleri, gate TARAFINDAN normalize EDİLMEDEN,
    kanonik dışı olarak REDDEDİLMELİ -- `.upper()`/`.strip()`/
    `.removesuffix('.IS')` gate İÇİNDE HİÇ ÇAĞRILMAZ."""
    assert "THYAO" in trusted_protocol.frozen_symbols
    evaluation = evaluate_universe_gate(trusted_protocol.frozen_symbols, malformed_form)
    assert evaluation.result == GateCheckResult.FAIL
    assert evaluation.reason_code == SYMBOL_NOT_IN_FROZEN_UNIVERSE


@pytest.mark.parametrize("bad_observed", [None, 123, ""], ids=["none", "int", "empty_string"])
def test_universe_gate_rejects_malformed_observed_symbol_not_as_scientific_fail(trusted_protocol, bad_observed):
    """Section 9/21: `None`/`123`/`""` bir GEÇERLİ "evren dışı" bilimsel
    gözlem DEĞİLDİR -- kaba bir programlama/domain girdi hatasıdır,
    `EvidenceIntegrityError` olarak fırlatılır, ASLA `IdentityGateEvaluation
    (FAIL, SYMBOL_NOT_IN_FROZEN_UNIVERSE)` DÖNDÜRMEZ."""
    with pytest.raises(EvidenceIntegrityError):
        evaluate_universe_gate(trusted_protocol.frozen_symbols, bad_observed)


def test_universe_gate_rejects_list_instead_of_frozenset():
    with pytest.raises(TypeError):
        evaluate_universe_gate(["THYAO", "GARAN"], "THYAO")


def test_universe_gate_rejects_none_expected_set():
    with pytest.raises(TypeError):
        evaluate_universe_gate(None, "THYAO")


def test_universe_gate_rejects_expected_set_with_non_string_member():
    with pytest.raises(EvidenceIntegrityError):
        evaluate_universe_gate(frozenset({"THYAO", 123}), "THYAO")


def test_universe_gate_rejects_expected_set_with_empty_string_member():
    with pytest.raises(EvidenceIntegrityError):
        evaluate_universe_gate(frozenset({"THYAO", ""}), "THYAO")


def test_universe_gate_result_is_order_independent():
    """Section 23: aynı sembol kümesinin FARKLI kaynak sıralarından
    inşa edilmiş iki eşdeğer frozenset'i, AYNI gözlemlenen sembol için
    AYNI sonucu üretmeli -- liste-sırası bağımlılığı YOKTUR."""
    symbols_order_a = frozenset(["THYAO", "GARAN", "AKBNK"])
    symbols_order_b = frozenset(["AKBNK", "THYAO", "GARAN"])
    assert symbols_order_a == symbols_order_b

    result_a = evaluate_universe_gate(symbols_order_a, "GARAN")
    result_b = evaluate_universe_gate(symbols_order_b, "GARAN")
    assert result_a == result_b


def test_universe_gate_reason_invariant_matches_shared_dataclass_contract():
    passing = evaluate_universe_gate(frozenset({"THYAO"}), "THYAO")
    assert passing.reason_code is None

    failing = evaluate_universe_gate(frozenset({"THYAO"}), "GARAN")
    assert failing.reason_code == SYMBOL_NOT_IN_FROZEN_UNIVERSE


def test_universe_gate_module_has_no_asset_config_or_provider_dependencies():
    """Section 25: kaynak-inceleme -- `identity_gates.py` hiçbir zaman
    `AssetRepository`/`Asset`/provider/Firestore/ağ importu YAPMAZ."""
    import app.research.identity_gates as module

    import_lines = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden_substrings = (
        "assetrepository",
        "bist_provider",
        "yfinance",
        "firestore",
        "requests",
        "httpx",
        "market_data",
    )
    for line in import_lines:
        lowered = line.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"yasaklı bağımlılık bulundu: {line!r}"


def test_universe_gate_never_constructs_attempt_result_or_classification():
    """Section 26: yeni kod `AttemptResult` İNŞA ETMEZ ve
    `AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG`'e
    ÜRETİM referansı VERMEZ."""
    import app.research.identity_gates as module

    source = inspect.getsource(module)
    assert "AttemptResult(" not in source
    assert "BLOCKED_UNIVERSE_OR_ASSET_CONFIG" not in source
