"""Final holdout ön kontrolü (preflight) — YALNIZ sentetik durumlar; gerçek holdout sonucu KULLANILMAZ."""

import json
from datetime import datetime, timezone

import pytest

from app.research.momentum_final_holdout import evaluator as ev
from app.research.momentum_final_holdout import preflight as pf
from app.research.momentum_final_holdout import protocol as pr

RULES = [{"rule_id": "R", "status": pr.EVALUABLE, "config_sha256": "x" * 64}]
PAYLOAD = {"version": "TEST", "rules": RULES}
LIVE = [{"rule_id": "R", "status": pr.EVALUABLE, "config_sha256": "x" * 64}]


def good_state(n_full=20, **kw):
    s = {"holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 2 + n_full)],
         "dataset_coverage": {"asset_sessions": 1978, "minimum_asset_sessions": 1566,
                              "minimum_sessions_per_primary_asset": 18, "assets_below_minimum": 0,
                              "min_sessions_any_asset": 23},
         "holdout_coverage": {"holdout_full_sessions": n_full},
         "archive_integrity": True, "raw_requests": 10, "raw_missing": 0, "raw_invalid": 0,
         "amendment_chain_valid": True, "amendments": list(pf.EXPECTED_AMENDMENTS), "unapproved_changes": [],
         "snapshot_sha256": pf.ORIGINAL_SNAPSHOT_SHA256, "snapshot_file_sha256": pf.ORIGINAL_SNAPSHOT_FILE_SHA256,
         "label_v2_sha256": pr.LABEL_V2_SHA256}
    return {**s, **kw}


@pytest.fixture
def frozen(tmp_path):
    p = tmp_path / "protocol.json"
    pr.freeze_manifest(p, PAYLOAD, datetime(2026, 11, 26, tzinfo=timezone.utc))
    return p


def chk(state, frozen, tmp_path, **kw):
    return pf.check(state, manifest_path=frozen, state_dir=tmp_path / "st", payload=PAYLOAD, live_rules=LIVE, **kw)


def test_all_conditions_met_is_ready(frozen, tmp_path):
    r = chk(good_state(), frozen, tmp_path)
    assert r["status"] == pf.READY and r["open"] and r["failed"] == []


def test_19_full_sessions_blocked(frozen, tmp_path):
    r = chk(good_state(19), frozen, tmp_path)
    assert not r["open"] and r["failed"] == ["holdout_full_sessions_ge_20"]


def test_20_full_but_missing_asset_coverage_blocked(frozen, tmp_path):
    cov = {**good_state()["dataset_coverage"], "assets_below_minimum": 1, "min_sessions_any_asset": 0}
    r = chk(good_state(20, dataset_coverage=cov), frozen, tmp_path)
    assert not r["open"] and r["failed"] == ["every_primary_asset_ge_18_sessions"]
    low = {**good_state()["dataset_coverage"], "asset_sessions": 1565}
    assert "dataset_asset_sessions_ge_1566" in chk(good_state(dataset_coverage=low), frozen, tmp_path)["failed"]


@pytest.mark.parametrize("bad", [{"amendment_chain_valid": False},
                                 {"amendments": ["AMD-001-EOD-PROBE-VALIDATION-RACE"]},
                                 {"unapproved_changes": ["backend/app/research/momentum_collector/collector.py"]}])
def test_invalid_amendment_chain_blocked(frozen, tmp_path, bad):
    assert chk(good_state(**bad), frozen, tmp_path)["failed"] == ["amendment_chain_valid"]


def test_snapshot_tampered_blocked(frozen, tmp_path):
    assert chk(good_state(snapshot_file_sha256="0" * 64), frozen, tmp_path)["failed"] == ["original_snapshot_intact"]


@pytest.mark.parametrize("bad", [{"raw_missing": 1}, {"raw_invalid": 3}, {"raw_requests": 0}])
def test_missing_raw_data_blocked(frozen, tmp_path, bad):
    assert chk(good_state(**bad), frozen, tmp_path)["failed"] == ["raw_hash_integrity"]


def test_corrupt_protocol_sha_blocked(frozen, tmp_path):
    raw = json.loads(frozen.read_text(encoding="utf-8"))
    raw["protocol"]["primary_targets"] = {"FPR": ["<=", 0.9]}
    frozen.write_text(json.dumps(raw), encoding="utf-8")
    r = chk(good_state(), frozen, tmp_path)
    assert not r["open"] and {"protocol_sha", "protocol_matches_code", "frozen_rule_config_sha"} <= set(r["failed"])


def test_rule_config_drift_and_label_mismatch_blocked(frozen, tmp_path):
    drift = [{"rule_id": "R", "status": pr.EVALUABLE, "config_sha256": "y" * 64}]
    r = pf.check(good_state(), manifest_path=frozen, state_dir=tmp_path / "st", payload=PAYLOAD, live_rules=drift)
    assert r["failed"] == ["frozen_rule_config_sha"]
    assert chk(good_state(label_v2_sha256="0" * 64), frozen, tmp_path)["failed"] == ["label_v2_sha"]


def test_consumed_or_started_blocked(frozen, tmp_path):
    st = tmp_path / "st"
    st.mkdir()
    (st / "FINAL_HOLDOUT_STARTED.json").write_text("{}", encoding="utf-8")
    assert chk(good_state(), frozen, tmp_path)["failed"] == ["holdout_not_consumed"]


def test_missing_fields_fail_closed(frozen, tmp_path):
    r = chk({}, frozen, tmp_path)
    assert not r["open"] and len(r["failed"]) >= 8


def test_real_expected_protocol_sha_is_checked(tmp_path):
    m = pr.load_manifest()  # gerçek dondurulmuş manifest (yalnız okunur)
    assert m["protocol_sha256"] == pf.EXPECTED_PROTOCOL_SHA256
    r = pf.check(good_state(), state_dir=tmp_path / "st")
    assert r["checks"]["protocol_sha"] and r["checks"]["protocol_matches_code"]
    assert r["checks"]["frozen_rule_config_sha"]


def gate_state(n=20):
    return {"pilot_manifest_sha256": pr.PILOT_MANIFEST_SHA256, "pilot_cutoff": pr.PILOT_CUTOFF,
            "holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 2 + n)], "short_sessions": [],
            "archive_integrity": True, "raw_requests": 10, "raw_missing": 0, "raw_invalid": 0,
            "raw_fingerprint": "f" * 64, "label_v2_sha256": pr.LABEL_V2_SHA256, "amendment_chain_valid": True}


def test_execute_never_loads_when_preflight_blocked(frozen, tmp_path):
    calls = []
    blocked = lambda: chk(good_state(20, dataset_coverage={**good_state()["dataset_coverage"],  # noqa: E731
                                                         "assets_below_minimum": 1}), frozen, tmp_path)
    out = ev.execute(lambda t: calls.append("bars"), lambda t: calls.append("news"), gate_state(20),
                     manifest_path=frozen, state_dir=tmp_path / "st", payload=PAYLOAD, head="h", preflight=blocked)
    assert calls == [] and out["gate"]["status"] == ev.GATE_CLOSED
    assert out["gate"]["missing"] == ["preflight: every_primary_asset_ge_18_sessions"]
    assert not (tmp_path / "st").exists()  # başlangıç kaydı bile yok
    out2 = ev.execute(lambda t: calls.append("bars"), lambda t: None, gate_state(20), manifest_path=frozen,
                      state_dir=tmp_path / "st", payload=PAYLOAD, head="h", preflight=lambda: None)
    assert calls == [] and not out2["gate"]["open"]  # geçersiz ön kontrol sonucu = kapalı


def test_execute_default_uses_real_preflight(monkeypatch, frozen, tmp_path):
    called = []
    monkeypatch.setattr(pf, "run", lambda reanalysis=False: called.append(1) or {"open": False, "failed": ["x"]})
    out = ev.execute(lambda t: pytest.fail("loader called"), lambda t: None, gate_state(20), manifest_path=frozen,
                     state_dir=tmp_path / "st", payload=PAYLOAD, head="h")
    assert called == [1] and not out["gate"]["open"]
