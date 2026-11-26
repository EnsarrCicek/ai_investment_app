"""Final holdout protokolü V2: varlık uygunluğu, V2 manifesti, ön kontrol, modlar (d15/d20/gerçek gözlem), look-ahead
güvenliği ve tek seferlik yürütme. YALNIZ sentetik veriler; gerçek holdout sonucu KULLANILMAZ."""

import inspect
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app.research.momentum_final_holdout import evaluator as ev
from app.research.momentum_final_holdout import modes as md
from app.research.momentum_final_holdout import preflight as pf
from app.research.momentum_final_holdout import protocol as pr
from app.research.momentum_final_holdout import protocol_v2 as p2
from app.research.momentum_label_v2 import labels as lv

M = lv.MIN_NS
D0 = int(datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc).timestamp() * 1e9)  # 10:00 İstanbul
UNI = [f"S{k:02d}" for k in range(86)] + ["KONTR"]


def t(hhmm):  # İstanbul saati → ns (aynı gün)
    h, m = map(int, hhmm.split(":"))
    return D0 + ((h - 10) * 60 + m) * M


def eligibility(kontr=0, n=23):
    counts = {s: n for s in UNI[:-1]} | {"KONTR": kontr}
    return p2.asset_eligibility(counts, UNI, 23, {"KONTR": 0.041})


@pytest.fixture
def v2_manifest(tmp_path):
    payload = p2.protocol_v2_payload(eligibility(), UNI, [f"d{k}" for k in range(23)])
    path = tmp_path / "v2.json"
    p2.freeze_v2(path, payload, datetime(2026, 11, 26, tzinfo=timezone.utc))
    return path


# ------------------------------------------------------------------ uygunluk
def test_uniform_eligibility_policy():
    e = p2.asset_eligibility({"A": 18, "B": 17, "C": 0, "D": 23}, ["A", "B", "C", "D"], 23)
    assert {s: r["status"] for s, r in e.items()} == {"A": p2.EVALUABLE_ASSET, "B": p2.NOT_EVALUABLE_ASSET,
                                                      "C": p2.NOT_EVALUABLE_ASSET, "D": p2.EVALUABLE_ASSET}
    assert "valid prospective FULL sessions 17 < 18" in e["B"]["reason"]  # nesnel kapsam gerekçesi
    k = eligibility()["KONTR"]
    assert k["status"] == p2.NOT_EVALUABLE_ASSET and "single" not in k["reason"].lower()  # doğrulanmamış iddia yok


def test_v2_payload_preserves_frozen_parts_and_discloses(v2_manifest):
    m = p2.load_v2(v2_manifest)
    p, v1 = m["protocol"], pr.load_manifest()["protocol"]
    assert p["previous_protocol"]["protocol_sha256"] == p2.V1_PROTOCOL_SHA256 == pf.EXPECTED_PROTOCOL_SHA256
    for k in ("label", "primary_targets", "rules", "alert_unit", "split", "pass_rule", "secondary_news_analysis"):
        assert p[k] == v1[k], k
    assert p["primary_targets"] == {"FPR": ["<=", 0.25], "evaluable_recall": [">=", 0.4],
                                    "median_visible_lead": ["<=", 0.5]}
    assert p["original_universe"]["count"] == 87 and p["evaluable_universe"]["count"] == 86
    assert "KONTR" in p["original_universe"]["symbols"] and "KONTR" not in p["evaluable_universe"]["symbols"]
    assert p["disclosure"]["original_87_asset_design_meets_coverage"] is False
    assert "ONLY to the evaluable assets" in p["disclosure"]["generalization"]
    assert p["holdout_outcomes_read_at_creation"] is False and p2.v2_matches_code(m)
    assert p["modes"][p2.MODE_A]["role"] == "PRIMARY PASS/FAIL" and "never changes" in p["modes"][p2.MODE_B]["role"]


def test_v2_write_once_and_v1_untouched(v2_manifest):
    before = pr.MANIFEST_PATH.read_bytes()
    with pytest.raises(p2.ProtocolV2Error):
        p2.freeze_v2(v2_manifest, p2.protocol_v2_payload(eligibility(kontr=18), UNI, ["x"]))
    raw = json.loads(v2_manifest.read_text(encoding="utf-8"))
    raw["protocol"]["evaluable_universe"]["symbols"].append("KONTR")
    v2_manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(p2.ProtocolV2Error):
        p2.load_v2(v2_manifest)
    assert pr.MANIFEST_PATH.read_bytes() == before


# ------------------------------------------------------------------ ön kontrol V2
def good_state(n=20, **kw):
    s = {"holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 2 + n)],
         "valid_sessions": {u: 23 for u in UNI[:-1]} | {"KONTR": 0},
         "archive_integrity": True, "raw_requests": 10, "raw_missing": 0, "raw_invalid": 0, "raw_fingerprint": "f" * 64,
         "amendment_chain_valid": True, "amendments": list(pf.EXPECTED_AMENDMENTS), "unapproved_changes": [],
         "snapshot_sha256": pf.ORIGINAL_SNAPSHOT_SHA256, "snapshot_file_sha256": pf.ORIGINAL_SNAPSHOT_FILE_SHA256,
         "label_v2_sha256": pr.LABEL_V2_SHA256}
    return {**s, **kw}


def pre(state, v2_manifest, tmp_path, **kw):
    return pf.check_v2(state, v2_path=v2_manifest, state_dir=tmp_path / "st", **kw)


def test_preflight_v2_ready_with_kontr_excluded(v2_manifest, tmp_path):
    r = pre(good_state(), v2_manifest, tmp_path)
    assert r["open"] and r["failed"] == [] and r["excluded"] == ["KONTR"] and len(r["evaluable"]) == 86
    assert r["info"]["evaluable_asset_sessions"] == 86 * 23


@pytest.mark.parametrize("bad,failed", [
    ({"holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 21)]}, "holdout_full_sessions_ge_20"),
    ({"valid_sessions": {u: 23 for u in UNI[:-1]} | {"S05": 17}}, "evaluable_coverage"),
    ({"valid_sessions": {u: 18 for u in UNI[:-1]}}, None),  # 86*18 = 1548 < 1566
    ({"amendments": ["AMD-001-EOD-PROBE-VALIDATION-RACE"]}, "amendment_chain_valid"),
    ({"snapshot_sha256": "0" * 64}, "original_snapshot_intact"),
    ({"raw_invalid": 1}, "raw_hash_integrity"), ({"raw_fingerprint": None}, "raw_hash_integrity"),
    ({"label_v2_sha256": "0" * 64}, "label_v2_sha")])
def test_preflight_v2_each_condition_fail_closed(v2_manifest, tmp_path, bad, failed):
    r = pre(good_state(**bad), v2_manifest, tmp_path)
    assert not r["open"] and (failed or "evaluable_coverage") in r["failed"]


def test_preflight_v2_rule_drift_consumed_and_corrupt_manifest(v2_manifest, tmp_path):
    drift = [{**x, "config_sha256": "0" * 64} for x in pr.load_manifest()["protocol"]["rules"]]
    assert pre(good_state(), v2_manifest, tmp_path, live_rules=drift)["failed"] == ["rule_config_sha"]
    st = tmp_path / "st"
    st.mkdir()
    (st / "FINAL_HOLDOUT_CONSUMED").write_text("{}", encoding="utf-8")
    assert pre(good_state(), v2_manifest, tmp_path)["failed"] == ["one_shot_not_consumed"]
    r = pf.check_v2(good_state(), v2_path=tmp_path / "missing.json", state_dir=tmp_path / "x")
    assert {"eligibility_policy_frozen", "evaluable_coverage", "rule_config_sha", "protocol_v2_sha"} <= set(r["failed"])


# ------------------------------------------------------------------ look-ahead (Mod C)
def test_bar_completed_1000_seen_1020_is_visible_only_at_1020():
    vis = md.observed_visibility(np.array([t("10:00")]), np.array([t("10:00")]), np.array([t("10:20")]))
    assert vis[0] == t("10:20")


def test_required_bar_not_yet_visible_waits():
    ends = np.array([t("10:25"), t("10:30")])
    seen = np.array([t("10:27"), t("10:50")])
    vis = md.observed_visibility(np.array([t("10:29"), t("10:30")]), ends, seen)
    assert list(vis) == [t("10:29"), t("10:50")]  # 10:30 barı 10:50'de görüldü → satır 10:50'den önce yok


def test_eod_first_seen_1900_is_unusable_live():
    info = np.array([t("11:00")])
    vis = md.observed_visibility(info, np.array([t("11:00")]), np.array([t("19:00")]))
    cov = md.live_coverage(vis, info, np.array([0]), np.array([t("18:10")]))
    assert vis[0] == t("19:00") and not cov["usable"][0] and cov["live_sessions"] == set()


def test_probe_outage_blocks_rows_until_missing_history_seen():
    ends = np.array([t("10:05"), t("10:10"), t("10:15"), t("10:20")])
    seen = np.array([t("10:23"), t("19:00"), t("19:00"), t("10:38")])  # 10:10–10:15 kesinti → EOD
    vis = md.observed_visibility(np.array([t("10:05"), t("10:20")]), ends, seen)
    assert vis[0] == t("10:23") and vis[1] == t("19:00")  # eksik geçmiş gelecekten doldurulmaz


def test_benchmark_later_than_asset():
    bars = {"AAA": (np.array([t("10:30")]), np.array([t("10:40")])),
            "XU100": (np.array([t("10:30")]), np.array([t("10:55")]))}
    info = np.array([t("10:30")])
    assert md.live_visible_times(info, ["AAA"], ["ASSET"], bars, "XU100")[0] == t("10:40")
    assert md.live_visible_times(info, ["AAA"], ["ASSET", "BENCHMARK"], bars, "XU100")[0] == t("10:55")


def test_never_used_before_first_seen_randomized():
    rng = np.random.default_rng(7)
    ends = np.sort(rng.integers(0, 10_000, 200)) * M
    seen = ends + rng.integers(0, 3_000, 200) * M
    info = rng.integers(0, 12_000, 500) * M
    vis = md.observed_visibility(info, ends, seen)
    for i, v in zip(info, vis):
        need = seen[ends <= i]
        assert v == (md.NO_TIME if not len(need) else max(need.max(), i))


def test_revisions_never_applied_and_first_seen_values_loaded():
    from app.research.momentum_pilot import split as sp
    src = inspect.getsource(sp.load_primary_bars)
    assert "FROM bars" in src and "bar_revision" not in src  # ilk görülen değerler; revizyon tablosu okunmaz
    assert "bar_revision" not in inspect.getsource(md)


# ------------------------------------------------------------------ modlar
def tiny(t_shift=0):
    sess = np.array([0] * 6)
    tt = np.array([t("10:10") + k * 5 * M + t_shift for k in range(6)], dtype=np.int64)
    ev_ = [[lv.Swing(0, 1, 100.0, 106.0, t("10:10"), t("10:40"), 0.06, True, lv.INTRADAY_EVALUABLE)]]
    mask = np.array([False, True, True, False, False, False])
    rid = "A_ROUND1_FINAL_WATCH_3OF3_D15"
    return ev.EvalInput([("AAA", "2026-11-02")], sess, np.zeros(6, int), tt, np.full(6, 101.0), ev_, {rid: mask})


RULES = [{"rule_id": "A_ROUND1_FINAL_WATCH_3OF3_D15", "status": "EVALUABLE", "config_sha256": "x"}]


def test_d20_and_live_modes_never_change_primary_verdict():
    a = tiny()
    b = md.shift_input(a, a.t_ns + 5 * M, a.entry)
    out = md.evaluate_modes(a, b, {}, None, RULES)
    rid = RULES[0]["rule_id"]
    assert out["primary_mode"] == p2.MODE_A and out["primary_verdicts"][rid] == out[p2.MODE_A]["rules"][rid]["verdict"]
    assert "verdict" not in out[p2.MODE_B]["rules"][rid] and "sensitivity_targets_check" in out[p2.MODE_B]["rules"][rid]
    assert out[p2.MODE_C][rid]["status"] == p2.NOT_EVALUABLE_LIVE


def test_live_mode_requires_minimum_live_coverage():
    a = tiny()
    rid = RULES[0]["rule_id"]
    cov = {"live_sessions": {0}, "share": {0: 1.0}}
    out = md.evaluate_modes(a, a, {rid: {"input": a, "coverage": cov, "live_symbols": ["AAA"]}}, None, RULES)
    assert out[p2.MODE_C][rid]["status"] == p2.NOT_EVALUABLE_LIVE and out[p2.MODE_C][rid]["live_asset_sessions"] == 1


# ------------------------------------------------------------------ V2 tek seferlik yürütme
PAYLOAD = {"version": "TEST", "rules": RULES}


@pytest.fixture
def v1_frozen(tmp_path):
    p = tmp_path / "v1.json"
    pr.freeze_manifest(p, PAYLOAD, datetime(2026, 11, 23, tzinfo=timezone.utc))
    return p


def gate_state(n=20):
    return {"pilot_manifest_sha256": pr.PILOT_MANIFEST_SHA256, "pilot_cutoff": pr.PILOT_CUTOFF,
            "holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 2 + n)], "short_sessions": [],
            "archive_integrity": True, "raw_requests": 10, "raw_missing": 0, "raw_invalid": 0,
            "raw_fingerprint": "f" * 64, "label_v2_sha256": pr.LABEL_V2_SHA256, "amendment_chain_valid": True}


def run(tmp_path, v1, v2, loader, pre_fn, n=20):
    return ev.execute_v2(loader, lambda tok: None, gate_state(n), manifest_path=v1, v2_path=v2,
                         state_dir=tmp_path / "st", payload=PAYLOAD, head="h", preflight=pre_fn,
                         evaluate_fn=lambda a, b, c, nd, rules: {"primary_mode": p2.MODE_A, "synthetic": True})


def open_pre(v2, **over):
    ev_list = p2.load_v2(v2)["protocol"]["evaluable_universe"]["symbols"]
    base = {"open": True, "failed": [], "checks": {"x": True}, "evaluable": ev_list,
            "holdout_sessions": [f"2026-11-{d:02d}" for d in range(2, 22)], "raw_fingerprint": "f" * 64}
    return lambda: {**base, **over}


def loaded(v2, sessions=None):
    syms = p2.load_v2(v2)["protocol"]["evaluable_universe"]["symbols"][:3]
    sess = sessions or [f"2026-11-{d:02d}" for d in range(2, 22)]
    return lambda tok: {"A": None, "B": None, "C": {}, "fingerprint": {"sessions": sess, "symbols": syms}}


def test_execute_v2_closed_paths_never_load(tmp_path, v1_frozen, v2_manifest):
    calls = []

    def spy(tok):
        calls.append(1)
    assert not run(tmp_path, v1_frozen, v2_manifest, spy, open_pre(v2_manifest), n=19)["gate"]["open"]
    blocked = lambda: {"open": False, "failed": ["evaluable_coverage"]}  # noqa: E731
    assert run(tmp_path, v1_frozen, v2_manifest, spy, blocked)["gate"]["missing"] == ["preflight_v2: evaluable_coverage"]
    diff = run(tmp_path, v1_frozen, v2_manifest, spy, open_pre(v2_manifest, raw_fingerprint="e" * 64))
    assert any("fingerprint differ" in x for x in diff["gate"]["missing"])
    other = run(tmp_path, v1_frozen, v2_manifest, spy, open_pre(v2_manifest, evaluable=["S00"]))
    assert any("evaluable list differs" in x for x in other["gate"]["missing"])
    assert calls == [] and not (tmp_path / "st").exists()


def test_execute_v2_one_shot_and_post_load_fingerprint(tmp_path, v1_frozen, v2_manifest):
    out = run(tmp_path, v1_frozen, v2_manifest, loaded(v2_manifest), open_pre(v2_manifest))
    assert out["result"]["status"] == "COMPLETED" and out["result"]["synthetic"]
    rec = json.loads((tmp_path / "st" / ev.START_RECORD).read_text(encoding="utf-8"))
    assert rec["protocol_v2_sha256"] == p2.load_v2(v2_manifest)["protocol_sha256"] and len(rec["evaluable_assets"]) == 86
    assert (tmp_path / "st" / ev.CONSUMED).exists()
    again = run(tmp_path, v1_frozen, v2_manifest, loaded(v2_manifest), open_pre(v2_manifest))
    assert not again["gate"]["open"]  # ikinci "ilk" değerlendirme yok
    st2 = tmp_path / "b"
    st2.mkdir()
    bad = ev.execute_v2(loaded(v2_manifest, sessions=["2026-11-02"]), lambda tok: None, gate_state(20),
                        manifest_path=v1_frozen, v2_path=v2_manifest, state_dir=st2 / "st", payload=PAYLOAD,
                        head="h", preflight=open_pre(v2_manifest), evaluate_fn=lambda *a: pytest.fail("evaluated"))
    assert bad["result"]["status"] == ev.FINGERPRINT_MISMATCH


def test_v2_modules_do_not_train_or_search():
    src = "".join(inspect.getsource(x) for x in (md, p2, pf))
    for w in ("sklearn", "lightgbm", ".fit(", "argmax", "grid", "quantile("):
        assert w not in src
    assert p2.MODE_DELAYS == {p2.MODE_A: 15, p2.MODE_B: 20} and p2.LIVE_TIMELY_MAX_MIN == 30
