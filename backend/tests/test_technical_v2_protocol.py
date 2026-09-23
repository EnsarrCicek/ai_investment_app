"""TECHNICAL V2 — dondurulmuş prospektif protokol kimliği (TECHNICAL_V2_PROTOCOL_V1).

Protokol, V1 protokolünün istatistiksel/değerlendirme sözleşmesini AYNEN taşır;
yalnızca metodoloji kimliği (V2 freeze manifest, engine 1.15.0) ve sürüm
alanları değişir. Holdout/aktivasyon YOK.
"""

import json
from pathlib import Path

from app.research.canonical_hash import content_sha256
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol

LOCKED_V2_PROTOCOL_SHA256 = "50b5b4e336f48c4043fe6802067b14b86ad8e0beb2cc78a6d56fec8209b395b8"
LOCKED_V1_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"
_RES = Path(__file__).resolve().parents[1] / "app" / "research" / "resources"
_V2_PATH = _RES / "technical_v2_protocol_v1.json"
_P1 = json.loads((_RES / "technical_v1_protocol_v1.json").read_text(encoding="utf-8"))
_P2 = json.loads(_V2_PATH.read_text(encoding="utf-8"))
_M2 = json.loads((_RES / "technical_v2_freeze_manifest.json").read_text(encoding="utf-8"))

_UNCHANGED_SCIENTIFIC_SECTIONS = (
    "class_groups", "primary_observation_unit", "horizons", "execution_and_return_definition", "primary_metric",
    "primary_null_hypothesis", "formal_uncertainty_method", "formal_primary_conclusion_labels", "secondary_analyses",
    "bullish_episode_definition", "sample_and_calendar_floors", "performance_visibility_before_first_checkpoint",
    "transaction_costs_and_simulated_strategy", "benchmark", "excluded_from_evaluation_definition",
    "missing_data_policy", "holdout_status", "required_future_evidence_record_fields",
)


def test_v2_protocol_identity_is_locked_and_verifiable():
    assert content_sha256(_P2) == LOCKED_V2_PROTOCOL_SHA256
    trusted = load_verified_technical_v1_protocol(LOCKED_V2_PROTOCOL_SHA256, _V2_PATH)
    assert trusted.protocol_version == "TECHNICAL_V2_PROTOCOL_V1"
    assert len(trusted.frozen_symbol_list) == 100


def test_v2_protocol_binds_exact_v2_freeze_manifest_identity():
    refs = _P2["methodology_references"]
    ident = _M2["methodology_identity"]
    assert _P2["technical_version"] == refs["technical_version"] == "TECHNICAL_V2"
    assert refs["freeze_manifest_sha256"] == content_sha256(_M2)
    assert refs["engine_version"] == ident["engine_version"] == "1.15.0"
    assert refs["scoring_config_hash"] == ident["scoring_config_hash"] == _P1["methodology_references"]["scoring_config_hash"]
    assert refs["methodology_git_commit"] == ident["methodology_git_commit"]
    assert refs["methodology_source_fingerprint"] == ident["methodology_source_fingerprint"]


def test_v2_protocol_carries_v1_scientific_contract_unchanged():
    for section in _UNCHANGED_SCIENTIFIC_SECTIONS:
        assert _P2[section] == _P1[section], section
    assert _P2["universe"]["frozen_symbol_list"] == _P1["universe"]["frozen_symbol_list"]


def test_v2_protocol_holdout_inactive_and_blinding_preserved():
    assert _P2["holdout_status"]["prospective_holdout_started"] is False
    assert _P2["holdout_status"]["effective_holdout_start"] is None
    assert _P2["performance_visibility_before_first_checkpoint"] is False


def test_v2_protocol_supersedes_exact_v1_protocol():
    assert _P2["supersedes"]["protocol_sha256"] == content_sha256(_P1) == LOCKED_V1_PROTOCOL_SHA256
    assert _P2["supersedes"]["protocol_version"] == "TECHNICAL_V1_PROTOCOL_V1"
