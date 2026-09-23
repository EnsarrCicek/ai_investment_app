"""TECH-VOL 1B — Technical V2 freeze manifest tutarlılığı.

V2 manifest, düzeltilmiş metodolojiyi (engine 1.15.0) düzeltme commit'ine
sabitler, scoring config'in DEĞİŞMEDİĞİNİ ve V1'i açıkça supersede ettiğini
kaydeder. Holdout/aktivasyon YOK.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.engines.technical.engine import ENGINE_VERSION
from app.engines.technical.scoring import compute_scoring_config_hash
from app.research.canonical_hash import content_sha256

_RES = Path(__file__).resolve().parents[1] / "app" / "research" / "resources"
_V1 = json.loads((_RES / "technical_v1_freeze_manifest.json").read_text(encoding="utf-8"))
_V2 = json.loads((_RES / "technical_v2_freeze_manifest.json").read_text(encoding="utf-8"))
_REPO = Path(__file__).resolve().parents[2]


def test_v2_identity_matches_running_engine_and_unchanged_scoring_config():
    ident = _V2["methodology_identity"]
    assert _V2["technical_version_name"] == "TECHNICAL_V2"
    assert ident["engine_version"] == ENGINE_VERSION == "1.15.0"
    assert ident["scoring_config_hash"] == compute_scoring_config_hash(
        _V2["technical_indicator_weights"], _V2["technical_family_weights"])
    assert ident["scoring_config_hash"] == _V1["methodology_identity"]["scoring_config_hash"]
    assert _V2["technical_indicator_weights"] == _V1["technical_indicator_weights"]
    assert _V2["technical_family_weights"] == _V1["technical_family_weights"]


def test_v2_supersedes_exact_v1_manifest():
    sup = _V2["supersedes"]
    assert sup["manifest_sha256"] == content_sha256(_V1)
    assert sup["engine_version"] == _V1["methodology_identity"]["engine_version"] == "1.14.0"
    assert sup["methodology_git_commit"] == _V1["methodology_identity"]["methodology_git_commit"]


def test_v2_does_not_activate_holdout():
    status = _V2["prospective_validation_status"]
    assert status["prospective_holdout_started"] is False
    assert status["prospective_evaluation_protocol_frozen"] is False


@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
def test_v2_methodology_commit_contains_the_gate_removal():
    commit = _V2["methodology_identity"]["methodology_git_commit"]
    src = subprocess.run(["git", "show", f"{commit}:backend/app/engines/technical/signal_classifier.py"],
                         cwd=_REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    strong_branch = src[src.index("if (\n        score >= 40"):src.index('return "STRONG_BULLISH_INITIATION"')]
    assert "high_volume" not in strong_branch
    engine_src = subprocess.run(["git", "show", f"{commit}:backend/app/engines/technical/engine.py"],
                                cwd=_REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert 'ENGINE_VERSION = "1.15.0"' in engine_src


@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
def test_v2_fingerprint_equals_normalized_source_at_pinned_commit():
    import hashlib

    from app.research.methodology_fingerprint import METHODOLOGY_FINGERPRINT_FILES

    commit = _V2["methodology_identity"]["methodology_git_commit"]
    hashes = {}
    for rel in METHODOLOGY_FINGERPRINT_FILES:
        blob = subprocess.run(["git", "show", f"{commit}:backend/{rel}"], cwd=_REPO, capture_output=True, check=True).stdout
        hashes[rel] = hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()
    expected = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert _V2["methodology_identity"]["methodology_source_fingerprint"] == expected


def test_v2_manifest_records_its_fingerprint_correction():
    corr = _V2["corrections"][0]
    assert corr["previous_field"] == "methodology_source_fingerprint_at_commit"
    assert corr["previous_value"] != _V2["methodology_identity"]["methodology_source_fingerprint"]


def test_normalized_fingerprint_is_line_ending_independent(tmp_path):
    from app.research.methodology_fingerprint import compute_methodology_source_fingerprint

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "f.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    (tmp_path / "b" / "f.py").write_bytes(b"x = 1\ny = 2\n")
    fa = compute_methodology_source_fingerprint(("f.py",), root=tmp_path / "a", normalize_newlines=True)
    fb = compute_methodology_source_fingerprint(("f.py",), root=tmp_path / "b", normalize_newlines=True)
    assert fa == fb
    # V1 algoritması (normalize yok) değişmedi: ham baytlar farklı -> farklı parmak izi
    assert compute_methodology_source_fingerprint(("f.py",), root=tmp_path / "a") != \
        compute_methodology_source_fingerprint(("f.py",), root=tmp_path / "b")
