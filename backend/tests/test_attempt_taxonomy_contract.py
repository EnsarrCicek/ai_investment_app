"""HATA 12 final closure — Technical V1 attempt taksonomi kontrat kilidi.

Bu dosya YENİ bir davranış TEST ETMEZ -- her bir üretim reason-code'unun
(data-quality/identity-gate/exclusion) davranışsal tetiklenmesi zaten kendi
özel test dosyasında (`test_data_quality.py`, `test_identity_gates.py`,
`test_exclusion_policy.py`, `test_technical_engine.py`) kilitlidir. Bu
dosyanın TEK amacı: HATA 12 final closure raporundaki "capture-time vs
outcome-time" taksonomi tablosunun dayandığı KARARLI SABİTLERİN/ENUM
ÜYELERİNİN var olduğunu ve gelecekteki bir attempt-execution servisinin
uygulayacağı EŞLEMENİN (henüz hiçbir kod bunu YAPMIYOR -- kasıtlı olarak,
bkz. HATA 12 section 15) hangi sabitler arasında olacağını dokümante eden
bir REGRESYON KİLİDİDİR. Bir sabit yeniden adlandırılır/kaldırılırsa bu
dosya kırılır -- taksonomi tablosunun sessizce eskimesini ÖNLER.

Hiçbir I/O yapılmaz, hiçbir AttemptResult/controller/servis inşa edilmez.
"""

import inspect

import pytest

from app.engines.technical.data_quality import (
    DataQualityError,
    InvalidOHLCVError,
    TradingDayContinuityError,
)
from app.research.attempt_models import AttemptResultClassification
from app.research.attempt_reason_codes import (
    LEADING_EDGE_UNVERIFIED,
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
    SYMBOL_NOT_IN_FROZEN_UNIVERSE,
    TECHNICAL_SCORE_NONE,
)
from app.research.final_evaluation_models import ResultState


# ---------------------------------------------------------------------------
# 1) İki bağımsız post-analysis exclusion sabiti (exclusion_policy.py'nin
#    dayandığı sabitler) -- EXCLUSION'a eşlenecek.
# ---------------------------------------------------------------------------


def test_post_analysis_exclusion_reason_codes_exist_and_are_distinct():
    assert TECHNICAL_SCORE_NONE == "TECHNICAL_SCORE_NONE"
    assert LEADING_EDGE_UNVERIFIED == "LEADING_EDGE_UNVERIFIED"
    assert TECHNICAL_SCORE_NONE != LEADING_EDGE_UNVERIFIED


# ---------------------------------------------------------------------------
# 2) Dört kimlik-kapısı FAIL nedeni -- her biri, gelecekte TAM OLARAK bir
#    BLOCKED_* sınıflandırmasına eşlenmesi beklenen sabitlerdir (henüz hiçbir
#    kod bu eşlemeyi YAPMIYOR -- bu, o niyeti dokümante eden bir kilittir).
# ---------------------------------------------------------------------------

_EXPECTED_IDENTITY_GATE_TO_BLOCKED_MAPPING = {
    SCORING_CONFIG_HASH_MISMATCH: AttemptResultClassification.BLOCKED_CONFIG_DRIFT,
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH: AttemptResultClassification.BLOCKED_METHODOLOGY_DRIFT,
    RUNTIME_IDENTITY_UNAUTHORIZED: AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY,
    SYMBOL_NOT_IN_FROZEN_UNIVERSE: AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG,
}


def test_exactly_four_identity_gate_reason_codes_map_to_four_blocked_classifications():
    assert len(_EXPECTED_IDENTITY_GATE_TO_BLOCKED_MAPPING) == 4
    assert set(_EXPECTED_IDENTITY_GATE_TO_BLOCKED_MAPPING.values()) == {
        AttemptResultClassification.BLOCKED_CONFIG_DRIFT,
        AttemptResultClassification.BLOCKED_METHODOLOGY_DRIFT,
        AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY,
        AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG,
    }


# ---------------------------------------------------------------------------
# 3) Continuity / raw-OHLCV / insufficient-history: YENİ sabit EKLENMEDİ --
#    `app.engines.technical.data_quality`'nin KENDİ, ZATEN var olan
#    `DataQualityError.reason_code` sabitleri REUSE edilir (HATA 12 section
#    5: alias/yeniden-isimlendirme YASAK). Her biri EXCLUSION'a eşlenecek.
# ---------------------------------------------------------------------------


def test_continuity_hard_veto_reason_codes_are_reused_not_aliased():
    missing = TradingDayContinuityError(
        symbol="TEST", missing_dates=[__import__("datetime").date(2026, 1, 5)], checked_period=(None, None)
    )
    assert missing.reason_code == "MISSING_TRADING_SESSION"

    unexpected = TradingDayContinuityError(
        symbol="TEST",
        missing_dates=[],
        checked_period=(None, None),
        unexpected_dates=[__import__("datetime").date(2026, 1, 5)],
    )
    assert unexpected.reason_code == "UNEXPECTED_TRADING_SESSION"


def test_raw_ohlcv_hard_veto_reason_code_is_reused_not_aliased():
    err = InvalidOHLCVError(symbol="TEST", violations=[(__import__("datetime").date(2026, 1, 5), "NEGATIVE_VOLUME")])
    assert err.reason_code == "INVALID_OHLCV"


def test_insufficient_history_reason_code_is_reused_not_aliased():
    err = DataQualityError("INSUFFICIENT_HISTORY", "test")
    assert err.reason_code == "INSUFFICIENT_HISTORY"


def test_data_quality_error_reason_codes_are_never_confused_with_exclusion_policy_constants():
    """Section 5: `CONTINUITY_FAILED`/`BAD_OHLCV`/`NOT_ENOUGH_HISTORY` gibi
    alias'lar YOKTUR -- kaynak incelemesiyle de doğrudan doğrulanır."""
    import app.engines.technical.data_quality as module

    source = inspect.getsource(module)
    for forbidden_alias in ("CONTINUITY_FAILED", "BAD_OHLCV", "NOT_ENOUGH_HISTORY"):
        assert forbidden_alias not in source


# ---------------------------------------------------------------------------
# 4) `AttemptResultClassification` -- kapalı taksonomi, section 16'nın
#    dayandığı TAM üye kümesi. Yeni bir üye eklenirse/kaldırılırsa bu
#    kilitleri KIRAR (kasıtlı -- taksonomi tablosunun sessizce eskimesini
#    önler).
# ---------------------------------------------------------------------------


def test_attempt_result_classification_has_exactly_the_expected_members():
    assert {member.value for member in AttemptResultClassification} == {
        "VALID_CANDIDATE",
        "EXCLUSION",
        "FAILED",
        "BLOCKED_CONFIG_DRIFT",
        "BLOCKED_METHODOLOGY_DRIFT",
        "BLOCKED_RUNTIME_IDENTITY",
        "BLOCKED_UNIVERSE_OR_ASSET_CONFIG",
    }


def test_attempt_result_classification_has_no_fabricated_no_result_member():
    """"Unexpected internal defect" ASLA bir `AttemptResultClassification`
    üyesi olarak UYDURULMAZ -- bu, selector seviyesindeki (bir AttemptResult
    hiç YAYINLANMADIĞINDA kullanılan) mevcut `ResultState.NO_RESULT`'tır,
    farklı bir katman/kavramdır (bkz. final_evaluation_models.py)."""
    assert not hasattr(AttemptResultClassification, "NO_RESULT")
    assert ResultState.NO_RESULT.value == "NO_RESULT"


# ---------------------------------------------------------------------------
# 5) Provider operational failure -> FAILED zaten mevcut taksonomide;
#    section 16'nın "provider failure -> FAILED" iddiasının FAILED'ın
#    GERÇEKTEN var olan bir sınıflandırma olduğunu kilitler.
# ---------------------------------------------------------------------------


def test_failed_classification_exists_for_provider_operational_failures():
    assert AttemptResultClassification.FAILED.value == "FAILED"
