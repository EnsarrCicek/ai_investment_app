import copy
import hashlib
from pathlib import Path

import pytest

from app.research.data_issues.registry import check_input_files, load_registry
from app.research.position_exit import normalized

BACKEND = Path(__file__).resolve().parents[1]
UNIVERSE = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925"
HAS_LOCAL_RUN = (UNIVERSE / "inputs" / "BSOKE_provider_ohlcv.csv").exists()
local_only = pytest.mark.skipif(not HAS_LOCAL_RUN, reason="yerel araştırma girdileri yok (git'e alınmamış)")

OLD_OUTPUTS = {  # 29.09.2026 itibarıyla kayıtlı eski çıktılar DEĞİŞMEMELİ
    "app/research/position_exit/runs/exit_exp1_20260929/result.json": "6ebbd86490705ff8c32d408068939814c336feaf3dd03ecc7a08d9f9e44e4512",
    "app/research/position_exit/runs/exit_exp1_20260929/episodes.jsonl": "1c55c29e53bc7c6953f4c8bf803f8eaf98b6e89e17580e65f46242a311c5edad",
    "app/research/market_risk_shadow/runs/early_risk_model_20260928/result.json": "de8111f39815a45ac7b366e22ac9a025576c92d5198645842b5cf2361796d98a",
    "app/research/market_risk_shadow/runs/volume_experiment_20260928/result.json": "9f71695e04bde90e44ed41d4193ef31540426a5d8049c728a9b74971ce8ae338",
    "app/research/market_risk_shadow/runs/universe_20260925/sharp_drop_coverage.json": "14e22c44f3f53e37ad2dfdb21a49f1c5d18813b20012b92974dee4d9f860ab8b",
    "app/research/market_risk_shadow/runs/universe_20260925/asset_gate_analysis.json": "33f2e36ada1ae2d39523d1a34beaccc99e690f48682c606c130d69dec9852efd",
    "app/research/market_risk_shadow/runs/universe_20260925/inputs/BSOKE_provider_ohlcv.csv": "059964873b1fc3b3824f026baabd5f3fe5c56d19f75b12b265f59f9e3ca5dc05",
    "app/research/market_risk_shadow/runs/universe_20260925/inputs/FENER_provider_ohlcv.csv": "f91b73aa34f33071d95ddf812386e553a98cd72159473b5807a2845ca705dc36",
}


def _registry_for(tmp_path, content=b"a,b\n1,2\n", symbol="ORNEK"):
    f = tmp_path / f"{symbol}.csv"
    f.write_bytes(content)
    reg = {"issues": [{"issue_id": "T-1", "symbol": symbol, "status": "CONFIRMED_PRICE_DISCONTINUITY",
                       "file": {"sha256": hashlib.sha256(content).hexdigest()}}], "reviews": []}
    return f, reg


def test_registry_records_both_confirmed_issues_by_file_identity():
    reg = load_registry()
    by_symbol = {i["symbol"]: i for i in reg["issues"]}
    assert set(by_symbol) == {"BSOKE", "FENER"}
    for issue in by_symbol.values():
        assert issue["status"] == "CONFIRMED_PRICE_DISCONTINUITY" and len(issue["file"]["sha256"]) == 64
        assert len(issue["officially_compared_sessions"]) == 4
        assert "KARŞILAŞTIRILMADI" in issue["locally_inferred_scaled_window"]["basis"]
        assert issue["origin"].startswith("KESİNLEŞMEDİ")


def test_matching_file_hash_blocks(tmp_path):
    f, reg = _registry_for(tmp_path)
    out = check_input_files({"ORNEK": f, "DIGER": tmp_path / "ORNEK.csv"}, reg)
    assert out["status"] == "BLOCKED"
    assert out["blocked"][0]["issue_id"] == "T-1" and out["blocked"][0]["reason"] == "CONFIRMED_PRICE_DISCONTINUITY"


def test_changed_file_identity_is_not_silently_approved(tmp_path):
    f, reg = _registry_for(tmp_path)
    f.write_bytes(b"a,b\n1,3\n")  # hash değişti
    out = check_input_files({"ORNEK": f}, reg)
    assert out["status"] == "BLOCKED" and out["blocked"][0]["reason"].startswith("REVIEW_REQUIRED")
    reviewed = copy.deepcopy(reg)
    reviewed["reviews"].append({"symbol": "ORNEK", "sha256": hashlib.sha256(b"a,b\n1,3\n").hexdigest(),
                                "status": "REVIEWED_NO_KNOWN_ISSUE"})
    assert check_input_files({"ORNEK": f}, reviewed)["status"] == "NO_KNOWN_ISSUE_MATCH"


def test_no_match_is_not_proof_of_correct_data(tmp_path):
    f, reg = _registry_for(tmp_path)
    other = tmp_path / "X.csv"
    other.write_bytes(b"z")
    out = check_input_files({"X": other}, reg)
    assert out["status"] == "NO_KNOWN_ISSUE_MATCH" and "KANITLAMAZ" in out["limit"]


@local_only
def test_exit_exp1_runner_blocked_before_start_on_known_issue_files(tmp_path, capsys):
    out_dir = tmp_path / "should_not_exist"
    assert normalized.main([str(UNIVERSE), str(out_dir)]) == 3
    assert not out_dir.exists()  # karşılaştırma başlamadı, kısmi sonuç yok
    err = capsys.readouterr().err
    assert "BLOCKED_KNOWN_DATA_ISSUE" in err and "BSOKE" in err and "FENER" in err


@local_only
def test_old_outputs_and_inputs_unchanged():
    for rel, digest in OLD_OUTPUTS.items():
        assert hashlib.sha256((BACKEND / rel).read_bytes()).hexdigest() == digest, rel
