"""FLOW 1C veri hijyeni: ham Yahoo snapshot'ları git'te ve Docker imajında
TUTULMAZ; yerel ham veri yoksa analiz açık hatayla durur (sessiz yeniden
çekim yok)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.research.flow_v1.dataset import FrozenDatasetMissingError, load_verified_dataset

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
RAW_PATHS = [
    "backend/app/research/flow_v1/data/frozen_ohlcv.json.gz",
    "backend/app/research/flow_v1c/data/frozen_ohlcv.json.gz",
]


def test_missing_local_frozen_data_fails_explicitly(tmp_path):
    manifest = tmp_path / "dataset_manifest.json"
    manifest.write_text(json.dumps({"symbols": {}, "dataset_sha256": "x"}), encoding="utf-8")
    with pytest.raises(FrozenDatasetMissingError, match="git'te tutulmaz"):
        load_verified_dataset(data_file=tmp_path / "frozen_ohlcv.json.gz", manifest_file=manifest)


def test_missing_manifest_fails_explicitly(tmp_path):
    with pytest.raises(FrozenDatasetMissingError):
        load_verified_dataset(data_file=tmp_path / "x.json.gz", manifest_file=tmp_path / "m.json")


@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
@pytest.mark.parametrize("raw_path", RAW_PATHS)
def test_raw_research_data_path_is_git_ignored(raw_path):
    result = subprocess.run(["git", "check-ignore", "-q", raw_path], cwd=REPO_ROOT)
    assert result.returncode == 0, f"{raw_path} git-ignore kapsamında değil"


@pytest.mark.skipif(shutil.which("git") is None, reason="git yok")
def test_no_raw_research_snapshot_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files", "backend/app/research"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert not [p for p in tracked if p.endswith(".json.gz")]


def test_raw_research_data_excluded_from_docker_context():
    patterns = [line.strip() for line in (BACKEND_DIR / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "app/research/**/data/*.json.gz" in patterns
