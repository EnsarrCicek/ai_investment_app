"""Final holdout protokolü / değerlendiricisi (YALNIZ sentetik girdiler; gerçek holdout sonucu KULLANILMAZ)."""

import inspect
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app.research.momentum_final_holdout import evaluator as ev
from app.research.momentum_final_holdout import protocol as pr
from app.research.momentum_label_v2 import labels as lv

M = lv.MIN_NS
T0 = int(datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc).timestamp() * 1e9)  # 10:00 İstanbul


def swing(start_min, peak_min, low=100.0, high=106.0, cls=lv.INTRADAY_EVALUABLE):
    return lv.Swing(0, 1, low, high, T0 + start_min * M, T0 + peak_min * M, high / low - 1, True, cls)


def make_input(sessions, events, masks, n_rows=12, step=5, entry=101.0):
    """Her seans n_rows satır (5 dk aralık); `masks[rid]` = seans başına aktif satır indeksleri listesi."""
    sess, seg, t = [], [], []
    for s in range(len(sessions)):
        for k in range(n_rows):
            sess.append(s)
            seg.append(s * n_rows)
            t.append(T0 + k * step * M)
    sess, seg, t = np.array(sess), np.array(seg), np.array(t, dtype=np.int64)
    out = {}
    for rid, active in masks.items():
        m = np.zeros(len(sess), dtype=bool)
        for s, rows in enumerate(active):
            for r in rows:
                m[s * n_rows + r] = True
        out[rid] = m
    return ev.EvalInput(sessions, sess, seg, t, np.full(len(sess), entry), events, out)


def state(n_full=20, **kw):
    days = [f"2026-11-{d:02d}" for d in range(2, 2 + n_full)]
    base = {"pilot_manifest_sha256": pr.PILOT_MANIFEST_SHA256, "pilot_cutoff": pr.PILOT_CUTOFF,
            "holdout_sessions": days, "short_sessions": [], "archive_integrity": True, "raw_requests": 10,
            "raw_missing": 0, "raw_invalid": 0, "raw_fingerprint": "f" * 64, "label_v2_sha256": pr.LABEL_V2_SHA256,
            "amendment_chain_valid": True}
    return {**base, **kw}


RULES = [{"rule_id": "R", "status": pr.EVALUABLE, "config_sha256": "x" * 64}]
PAYLOAD = {"version": "TEST", "rules": RULES}
OPEN = lambda: {"open": True, "checks": {"synthetic": True}, "failed": []}  # noqa: E731


@pytest.fixture
def frozen(tmp_path):
    path = tmp_path / "protocol.json"
    pr.freeze_manifest(path, PAYLOAD, datetime(2026, 11, 23, tzinfo=timezone.utc))
    return path


def test_gate_closed_at_19_and_open_at_20(frozen, tmp_path):
    g19 = ev.check_gate(state(19), frozen, tmp_path / "st", payload=PAYLOAD)
    assert g19["status"] == ev.GATE_CLOSED and g19["missing_full_sessions_count"] == 1
    assert any("19 < 20" in x for x in g19["missing"])
    g20 = ev.check_gate(state(20), frozen, tmp_path / "st", payload=PAYLOAD)
    assert g20["status"] == ev.GATE_OPEN and g20["missing"] == []


@pytest.mark.parametrize("bad,needle", [({"archive_integrity": False}, "archive integrity"),
                                        ({"raw_missing": 1}, "raw files"), ({"raw_invalid": 2}, "raw files"),
                                        ({"label_v2_sha256": "0" * 64}, "Label V2"),
                                        ({"pilot_cutoff": "2026-11-05"}, "pilot split")])
def test_gate_reports_exact_missing_condition(frozen, tmp_path, bad, needle):
    g = ev.check_gate(state(25, **bad), frozen, tmp_path / "st", payload=PAYLOAD)
    assert not g["open"] and any(needle in x for x in g["missing"])


def test_protocol_change_closes_gate(frozen, tmp_path):
    g = ev.check_gate(state(20), frozen, tmp_path / "st", payload={**PAYLOAD, "version": "CHANGED"})
    assert not g["open"] and any("fingerprint" in x for x in g["missing"])
    raw = json.loads(frozen.read_text(encoding="utf-8"))
    raw["protocol"]["primary_targets"] = {"FPR": ["<=", 0.5]}
    frozen.write_text(json.dumps(raw), encoding="utf-8")
    g = ev.check_gate(state(20), frozen, tmp_path / "st", payload=PAYLOAD)
    assert any("corrupted" in x for x in g["missing"])


def test_manifest_is_write_once(tmp_path):
    p = tmp_path / "m.json"
    m1, created = pr.freeze_manifest(p, PAYLOAD)
    m2, created2 = pr.freeze_manifest(p, PAYLOAD)
    assert created and not created2 and m1 == m2
    with pytest.raises(pr.ProtocolError):
        pr.freeze_manifest(p, {**PAYLOAD, "version": "V2"})


def test_loader_never_called_while_gate_closed(frozen, tmp_path):
    calls = []
    out = ev.execute(lambda t: calls.append("bars"), lambda t: calls.append("news"), state(19),
                     manifest_path=frozen, state_dir=tmp_path / "st", payload=PAYLOAD, head="h")
    assert out["gate"]["status"] == ev.GATE_CLOSED and calls == []
    assert not (tmp_path / "st").exists()  # başlangıç kaydı bile yazılmaz
    with pytest.raises(ev.GateClosedError):
        ev.load_holdout_input("not a token")
    with pytest.raises(ev.GateClosedError):
        ev.GateToken(object(), ["2026-11-02"])


def _synthetic():
    events = [[swing(10, 40)], [], [swing(20, 30)]]
    return make_input([("AAA", "2026-11-02"), ("BBB", "2026-11-02"), ("CCC", "2026-11-03")], events,
                      {"R": [[2, 3, 4, 6, 7], [], []]})


def test_completion_marker_blocks_second_first_evaluation(frozen, tmp_path):
    st = tmp_path / "st"
    out = ev.execute(lambda t: _synthetic(), lambda t: None, state(20), manifest_path=frozen, state_dir=st,
                     payload=PAYLOAD, head="abc", preflight=OPEN)
    assert out["gate"]["open"] and (st / ev.CONSUMED).exists() and (st / ev.START_RECORD).exists()
    rec = json.loads((st / ev.START_RECORD).read_text(encoding="utf-8"))
    assert {"protocol_sha256", "label_v2_sha256", "amendment_chain_valid", "eligible_sessions",
            "raw_input_fingerprint", "code_head", "timestamp"} <= set(rec) and len(rec["eligible_sessions"]) == 20
    calls = []
    again = ev.execute(lambda t: calls.append(1), lambda t: None, state(20), manifest_path=frozen, state_dir=st,
                       payload=PAYLOAD, head="abc", preflight=OPEN)
    assert again["gate"]["status"] == ev.GATE_CLOSED and calls == []
    re = ev.execute(lambda t: _synthetic(), lambda t: None, state(20), reanalysis=True, manifest_path=frozen,
                    state_dir=st, payload=PAYLOAD, head="abc", preflight=OPEN)
    assert re["result"]["label"] == ev.REANALYSIS and "candidate selection" in re["result"]["warning"]
    assert json.loads((st / ev.RESULT_FILE).read_text(encoding="utf-8"))["label"] == "FIRST_FINAL_EVALUATION"


def test_started_but_unfinished_attempt_also_blocks(frozen, tmp_path):
    st = tmp_path / "st"

    def boom(token):
        raise RuntimeError("crash after start")
    with pytest.raises(RuntimeError):
        ev.execute(boom, lambda t: None, state(20), manifest_path=frozen, state_dir=st, payload=PAYLOAD, head="h", preflight=OPEN)
    g = ev.check_gate(state(20), frozen, st, payload=PAYLOAD)
    assert not g["open"] and any("start/completion" in x for x in g["missing"])


def test_primary_alert_collapses_repeated_activations():
    m = ev.rule_metrics(_synthetic(), _synthetic().masks["R"])
    assert m["primary_alerts"] == 1 and m["activations_collapsed"] == 1  # iki aktivasyon → bir birincil alarm
    assert m["TP"] == 1 and m["FP"] == 0 and m["duplicate_alerts"] == 0
    assert m["evaluable_events"] == 2 and m["evaluable_recall"] == 0.5 and m["FPR"] == 0.0
    assert m["alarm_density_per_session"]["2026-11-02"] == {"alerts": 1, "asset_sessions": 2, "density": 0.5}


def test_pass_requires_all_three_thresholds():
    good = {"FPR": 0.25, "evaluable_recall": 0.40, "median_visible_lead": 0.50}
    assert ev.pass_fail(good)["verdict"] == "PASS"
    for k, v in (("FPR", 0.2501), ("evaluable_recall", 0.399), ("median_visible_lead", 0.51)):
        assert ev.pass_fail({**good, k: v})["verdict"] == "FAIL"
    assert ev.pass_fail({**good, "median_visible_lead": None})["verdict"] == "FAIL"


def _news(items, fetch_minutes, first=0):
    f = np.array([T0 + x * M for x in fetch_minutes], dtype=np.int64)
    return ev.NewsData(items, f, T0 + first * M)


def test_news_uses_received_at_not_published_at():
    item = {"item_key": "k", "symbol": "AAA", "event_type": "contract",
            "published_ns": T0 + 60 * M, "received_ns": T0 + 75 * M}  # yayım 11:00, arşive giriş 11:15
    nd = _news([item], range(0, 200, 5))
    cats = ev.logical_catalysts(nd.items)
    assert ev.news_status(nd, cats, "AAA", T0 + 70 * M, 15)[0] == pr.NO_NEWS  # yayımlanmış ama henüz alınmamış
    assert ev.news_status(nd, cats, "AAA", T0 + 75 * M, 15)[0] == pr.NEWS_PRESENT
    assert "published_ns" not in inspect.getsource(ev.news_status)


def test_news_not_observed_differs_from_no_news():
    nd = _news([], list(range(60, 200, 5)), first=60)  # toplayıcı 11:00'de başladı
    assert ev.news_status(nd, [], "AAA", T0 + 50 * M, 15)[0] == pr.NEWS_NOT_OBSERVED  # başlamadan önce
    assert ev.news_status(nd, [], "AAA", T0 + 120 * M, 60)[0] == pr.NO_NEWS
    gap = _news([], [60, 65, 70, 100, 105], first=60)  # 30 dk getirme boşluğu
    assert ev.news_status(gap, [], "AAA", T0 + 105 * M, 30)[0] == pr.NEWS_NOT_OBSERVED
    assert pr.NEWS_NOT_OBSERVED != pr.NO_NEWS


def test_source_revisions_do_not_double_count_catalysts():
    base = {"item_key": "foreks:ecb", "symbol": "AAA", "event_type": "other", "published_ns": T0}
    items = [{**base, "received_ns": T0 + 5 * M}, {**base, "received_ns": T0 + 10 * M}]
    nd = ev.NewsData(items, np.array([T0 + x * M for x in range(0, 60, 5)], dtype=np.int64), T0,
                     {("foreks:ecb", "AAA"): 2})
    cats = ev.logical_catalysts(nd.items)
    assert len(cats) == 1 and cats[0]["received_ns"] == T0 + 5 * M
    c = ev._news_counts([("AAA", T0 + 30 * M)], nd, cats, 30)
    assert c[pr.NEWS_PRESENT] == 1 and c["present_with_revision_metadata"] == 1 and c["present_only_other"] == 1


def test_missing_config_is_not_approximated():
    def missing():
        raise FileNotFoundError("frozen artifact missing")
    rules = pr.resolve_rules({"C_FROZEN_REL_RET_Z3_1OF1_D15": missing,
                              "A_X": lambda: {"rule_id": "A_X", "definition": {"t": 1}}})
    assert rules[0]["status"] == pr.NOT_EVALUABLE and "config_sha256" not in rules[0]
    assert rules[1]["status"] == pr.EVALUABLE
    res = ev.evaluate(_synthetic(), None, [rules[0]])
    assert res["rules"]["C_FROZEN_REL_RET_Z3_1OF1_D15"]["verdict"] == pr.NOT_EVALUABLE


def test_real_rules_reconstruct_from_artifacts_exactly():
    rules = {r["rule_id"]: r for r in pr.resolve_rules()}
    assert all(r["status"] == pr.EVALUABLE for r in rules.values())
    c = rules["C_FROZEN_REL_RET_Z3_1OF1_D15"]
    assert c["source_sha256"] == pr.FROZEN_CANDIDATE_SHA256 and c["definition"]["threshold"] == pr.FROZEN_THRESHOLD
    assert rules["A_ROUND1_FINAL_WATCH_3OF3_D15"]["source_sha256"] == pr.ROUND1_FINAL_SHA256
    assert set(ev.MASK_KEYS) == set(rules)


def test_stress_breakdowns_predeclared():
    inp = make_input([("A", "2026-11-02"), ("B", "2026-11-02")], [[swing(10, 40)], [swing(0, 8)]],
                     {"R": [[3], []]})
    m = ev.rule_metrics(inp, inp.masks["R"])
    b = ev.breakdowns(inp, inp.masks["R"], m)
    assert b["broad_market_high_participation_sessions"]["sessions"] == 2  # tüm varlık-seanslarda olay
    assert b["yahoo_latency_lost_events"]["evaluable_events"] == 1  # 8 dk'lık olay d15'te yakalanamaz
    assert b["opening_period_events"]["evaluable_events"] == 2


def test_no_training_and_no_threshold_search():
    src = inspect.getsource(ev) + inspect.getsource(pr)
    for w in ("sklearn", "lightgbm", "xgboost", ".fit(", "LogisticRegression", "quantile(", "argmax", "grid"):
        assert w not in src
    assert pr.TARGETS == {"FPR": ["<=", 0.25], "evaluable_recall": [">=", 0.40], "median_visible_lead": ["<=", 0.50]}
    assert pr.NEWS_WINDOWS_MIN == (15, 30, 60) and pr.REQUIRED_FULL_SESSIONS == 20


def test_evaluate_reports_each_rule_independently_without_selection():
    inp = _synthetic()
    inp.masks["R2"] = inp.masks["R"].copy()
    res = ev.evaluate(inp, None, RULES + [{"rule_id": "R2", "status": pr.EVALUABLE, "config_sha256": "y" * 64}])
    assert set(res["rules"]) == {"R", "R2"} and all(v["verdict"] in ("PASS", "FAIL") for v in res["rules"].values())
    assert "not selection" in res["selection_note"] and "best" not in json.dumps(res["rules"], default=str)


def test_holdout_outcomes_remain_forbidden_for_development_access():
    from app.research.momentum_pilot import split as sp
    from app.research.momentum_sources import holdout
    guard = sp.HoldoutGuard(sp.load_manifest())
    assert guard.cutoff == pr.PILOT_CUTOFF
    with pytest.raises(sp.HoldoutAccessError):  # bar/etiket/olay/alarm/lead hattının girişi: sorgudan ÖNCE hata
        sp.load_primary_bars(None, guard, [pr.HOLDOUT_START], "5m")
    for f in ("v2_events", "peak", "mfe", "alerts", "lead", "candidate_results"):
        with pytest.raises(sp.HoldoutAccessError):
            holdout.assert_news_join_allowed([pr.HOLDOUT_START], [f])
    assert "build_input" not in inspect.getsource(ev.check_gate) + inspect.getsource(ev.collect_gate_state)
