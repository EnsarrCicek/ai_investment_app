"""Momentum fizibilite denetimi (yalnız araştırma): Pareto, doğrulama maliyeti, gecikme simülasyonu, veri güvenliği."""

import random
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_calibration import experiment as r1x
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.services.momentum.early_momentum_engine import compute_features, confirm_level
from tests.test_momentum_engine import DAY, PROV, build, noise


def _pt(r, fpr, lead, p=0.1):
    return {"recall": r, "false_positive_rate": fpr, "lead_fraction_median": lead, "precision": p}


def test_dominated_points_removed_and_deterministic():
    pts = [_pt(0.6, 0.3, 0.5), _pt(0.5, 0.4, 0.6), _pt(0.7, 0.5, 0.4), _pt(0.6, 0.3, 0.5), _pt(0.2, 0.1, 0.7)]
    keep = fr.pareto_mask(pts)
    assert list(keep) == [True, False, True, True, True]  # (0.5,0.4,0.6) birinci tarafından baskın
    assert list(fr.pareto_mask(list(pts))) == list(keep)
    assert fr.pareto_mask([_pt(0.5, None, 0.5), _pt(0.5, 0.2, 0.5)]).tolist() == [False, True]  # eksik = en kötü


def test_best_under_constraints():
    pts = [_pt(0.6, 0.3, 0.5), _pt(0.4, 0.2, 0.6), _pt(0.3, 0.1, 0.35)]
    assert fr.best_under(pts, "recall", True, {"false_positive_rate": ("<=", 0.25)})["recall"] == 0.4
    assert fr.best_under(pts, "false_positive_rate", False, {"lead_fraction_median": ("<=", 0.40)})[
        "false_positive_rate"] == 0.1
    assert fr.best_under(pts, "recall", True, {"false_positive_rate": ("<=", 0.05)}) is None


@pytest.mark.parametrize("k,n", [(1, 1), (2, 3), (2, 2), (3, 3)])
def test_confirmation_matches_production_confirm_level(k, n):
    rng = random.Random(k * 10 + n)
    raw = np.array([rng.random() < 0.5 for _ in range(60)])
    seg_start = np.array([0] * 25 + [25] * 35)  # iki seans
    got = fr.confirm(raw, seg_start, k, n)
    cfg = ma.MomentumAlertConfig(confirm_k=k, confirm_n=n)
    for i in range(60):
        seq = [ma.LEVEL_WATCH if x else ma.LEVEL_NONE for x in raw[seg_start[i]:i + 1]]
        padded = [ma.LEVEL_NONE] * max(0, n - len(seq)) + seq
        assert got[i] == (confirm_level(padded, cfg) == ma.LEVEL_WATCH), i


def test_confirmation_cost_delays_first_alert():
    raw = np.array([False, True, True, True, True, False])
    seg = np.zeros(6, dtype=int)
    firsts = {f"{k}/{n}": int(np.flatnonzero(fr.confirm(raw, seg, k, n))[0]) for k, n in ((1, 1), (2, 3), (3, 3))}
    assert firsts == {"1/1": 1, "2/3": 2, "3/3": 3}


def _labels(t_ns, entry, mfe, events, high_ns, high, low):
    n = len(t_ns)
    return fr.LabelArrays(np.array(t_ns, dtype=np.int64), np.array(entry, float), np.array(mfe, float),
                          np.zeros(n), np.ones(n, bool), np.array(events), np.array(high_ns, dtype=np.int64),
                          np.array(high, float), np.array(low, float))


def test_metrics_event_ordering_alert_after_peak_not_caught():
    # seans 0: olay, tepe t=20; ilk alarm t=10 (yakalandı). seans 1: olay, tepe t=5; alarm t=10 (tepeden sonra).
    # seans 2: olaysız, alarm (yanlış pozitif). seans 3: olaysız, alarm yok.
    sess = np.array([0, 0, 1, 1, 2, 3])
    final = np.array([True, True, False, True, True, False])
    lab = _labels([10, 15, 0, 10, 10, 10], [101, 102, 100, 110, 100, 100], [0.05, 0.04, 0, 0.01, 0.0, 0],
                  [True, True, False, False], [20, 5, 0, 0], [110, 112, 100, 100], [100, 100, 100, 100])
    m = fr.metrics(final, sess, lab, 0.03)
    assert m["alert_sessions"] == 3 and m["events"] == 2 and m["caught_events"] == 1
    assert m["recall"] == 0.5 and m["false_positive_rate"] == 0.5
    assert m["precision"] == pytest.approx(1 / 3)
    assert m["lead_fraction_median"] == pytest.approx(0.1)


def test_delay_simulation_is_time_shift_without_lookahead():
    """d dk gecikme @T == 15 dk gecikme @T+(15−d): aynı görünür barlar; T'den sonraki barlar hiçbirinde yok."""
    bars = build(noise(40, 3) + [0.004] * 6 + noise(10, 4))
    config15 = r1x.config_for("F1", delay=15)
    for d in (0, 5, 10):
        cfg = r1x.config_for("F1", delay=d)
        for minute in (20, 35, 50):
            t = datetime.combine(DAY, datetime.min.time(), tzinfo=ISTANBUL_TZ) + timedelta(hours=10, minutes=minute
                                                                                         + 5 * 30)
            a = compute_features("SYN", bars, PROV, t, cfg)
            b = compute_features("SYN", bars, PROV, t + timedelta(minutes=15 - d), config15)
            assert a.status == b.status == ma.STATUS_OK
            assert a.components == b.components and a.persistent == b.persistent
            # gelecek barlar (T'den sonra başlayan) bozulsa bile sonuç değişmez
            future = bars.copy()
            future.loc[future.index > t, "Close"] *= 1.5
            assert compute_features("SYN", future, PROV, t, cfg).components == a.components


def test_selection_loader_never_reads_untouched_or_final():
    sel_days, final_days = fx.selection_scope()
    requested = []
    fake = [{"symbol": "AKBNK", "day": sel_days[0]}, {"symbol": "AKBNK", "day": sorted(final_days)[0]},
            {"symbol": "GARAN", "day": sel_days[-1]}]

    def loader(name):
        requested.append(name)
        return fake

    rows = fx.load_selection_rows(loader)
    assert requested == ["merged_ref_d15.pkl"]
    assert all(r["day"] not in final_days for r in rows) and len(rows) == 2
    bad = [{"symbol": "ENKAI", "day": sel_days[0]}]  # Round 2 dokunulmamış varlık
    with pytest.raises(RuntimeError, match="Untouched final is forbidden"):
        fx.load_selection_rows(lambda name: bad)
    assert not (fx.RUNS / "final.json").exists()
    assert not (fx.ds2.RUNS / "final.json").exists()


@pytest.mark.parametrize("name", ["merged_new_d15.pkl", "ext_new_d15.pkl", "r1_new_F1_d15.pkl", "final.json"])
def test_untouched_final_artifacts_raise(name):
    opened = []
    with pytest.raises(RuntimeError, match="Untouched final is forbidden in feasibility study"):
        fx.guarded_load(name, lambda n: opened.append(n))
    assert opened == []  # yükleyici hiç çağrılmadı
    assert fx.guarded_load("merged_ref_d15.pkl", lambda n: n) == "merged_ref_d15.pkl"


def test_guard_rows_rejects_final_dates_and_untouched_assets():
    sel_days, final_days = fx.selection_scope()
    au.guard_rows([{"symbol": "AKBNK", "day": sel_days[0]}], fx.ds2.UNTOUCHED_ASSETS, final_days)
    with pytest.raises(RuntimeError):
        au.guard_rows([{"symbol": "AKBNK", "day": sorted(final_days)[0]}], fx.ds2.UNTOUCHED_ASSETS, final_days)
    with pytest.raises(RuntimeError):
        au.guard_rows([{"symbol": "TAVHL", "day": sel_days[0]}], fx.ds2.UNTOUCHED_ASSETS, final_days)


def test_three_criteria_frontier_drops_worse_fpr_recall_lead():
    pts = [{**_pt(0.6, 0.3, 0.5), "delay": 15, "config": {}}, {**_pt(0.5, 0.4, 0.6), "delay": 15, "config": {}},
           {**_pt(0.7, 0.5, 0.4), "delay": 15, "config": {}}]
    front = fx.frontier3(pts)
    assert [(q["recall"], q["false_positive_rate"]) for q in front] == [(0.6, 0.3), (0.7, 0.5)]
    assert fx.frontier3(list(reversed(pts))) == front  # sıra bağımsız / deterministik


def test_frontier_answers_fpr_limits_and_base_rate_multiples():
    pts = [{**_pt(0.6, 0.3, 0.5, 0.12), "delay": 15, "config": {"i": 0}},
           {**_pt(0.45, 0.18, 0.55, 0.16), "delay": 15, "config": {"i": 1}},
           {**_pt(0.30, 0.08, 0.62, 0.25), "delay": 15, "config": {"i": 2}}]
    a = fx.frontier_answers(pts, base=0.075)
    assert a["max_recall_fpr_le_0.25"]["config"] == {"i": 1}
    assert a["max_recall_fpr_le_0.1"]["config"] == {"i": 2}
    assert a["max_recall_fpr_le_0.25"]["specificity"] == pytest.approx(0.82)
    assert a["min_fpr_lead_le_0.5"]["config"] == {"i": 0}
    assert a["min_fpr_lead_le_0.3"] is None
    assert a["min_lead_precision_ge_2x_base"]["config"] == {"i": 1}
    assert a["min_lead_precision_ge_3x_base"]["config"] == {"i": 2}


def test_confirmation_lag_minutes():
    raw = np.array([False, True, True, True, False, True, True])
    seg = np.zeros(7, dtype=int)
    t = np.arange(7) * 5  # dakika
    lags = {}
    for k, n in ((1, 1), (2, 3), (2, 2), (3, 3)):
        first_conf = int(np.flatnonzero(fr.confirm(raw, seg, k, n))[0])
        lags[f"{k}/{n}"] = int(t[first_conf] - t[1])
    assert lags == {"1/1": 0, "2/3": 5, "2/2": 5, "3/3": 10}


def test_delay_decomposition_sums_to_total():
    m = au.MIN_NS
    start = 1_000 * m
    d = au.decompose_delay(start, start + 15 * m, start + 20 * m, start + 30 * m, 15)
    assert d["D_feature_formation"] == 10 and d["A_bar_completion"] == 5 and d["E_threshold_gating"] == 5
    assert d["C_confirmation"] == 10 and d["B_provider"] == 15 and d["total"] == 45
    assert sum(v for k, v in d.items() if k != "total") == d["total"]
    assert au.decompose_delay(start, None, None, None, 15) is None


def test_event_timeline_ordering_and_peak_cutoff():
    m = au.MIN_NS
    info = np.arange(10) * 5 * m
    raw = np.array([0, 0, 1, 1, 1, 1, 0, 0, 0, 0], bool)
    conf = fr.confirm(raw, np.zeros(10, int), 3, 3)
    strong = conf & (np.arange(10) >= 5)
    late = np.zeros(10, bool)
    late[8] = True  # tepeden sonra: zaman çizgisine girmez
    tl = au.event_timeline(info, {"raw_watch": raw, "confirmed_watch": conf, "strong": strong, "late": late},
                           move_start_ns=0, peak_ns=35 * m)
    assert tl["move_start"] <= tl["raw_watch"] <= tl["confirmed_watch"] <= tl["strong"] <= tl["peak"]
    assert tl["late"] is None


@pytest.mark.parametrize("ev,d0raw,d15raw,d15alert,expected", [
    (0.2, 0.2, 0.3, 0.4, "EARLY_OK"),
    (0.7, 0.7, 0.9, None, "DATA_LATE"),
    (None, None, None, None, "DATA_LATE"),
    (0.2, 0.6, 0.8, None, "ENGINE_LATE"),   # eşik gecikmesizken bile geç
    (0.2, 0.2, 0.3, 0.7, "ENGINE_LATE"),    # 15 dk'da ham hâlâ erken; doğrulama geç yaptı
    (0.3, 0.35, 0.85, 0.98, "MIXED"),       # KTLEV benzeri: sağlayıcı gecikmesi ham alarmı bile geç yapıyor
])
def test_timing_classification(ev, d0raw, d15raw, d15alert, expected):
    assert au.classify_timing(ev, d0raw, d15raw, d15alert) == expected


def _fp(**over):
    base = dict(locked=False, volume_missing=False, regime_shock=False, rel_ret_z_3=2.0, gap_pct=0.0, ret_close=0.01,
                breakout=0.0, volume_anomaly=0.8, relvol_3=1.0, mfe_close=0.02, accel=0.2, accel_next_min=0.1,
                visible_minute=11 * 60)
    return au.fp_flags(**{**base, **over})


def test_fp_taxonomy_deterministic_primary_secondary():
    assert au.classify_fp(_fp()) == ("OTHER", [])
    assert au.classify_fp(_fp(volume_anomaly=0.1))[0] == "PRICE_SPIKE_NO_VOLUME"
    p, s = au.classify_fp(_fp(regime_shock=True, relvol_3=3.0, mfe_close=0.005, visible_minute=17 * 60 + 5))
    assert p == "BENCHMARK_SHOCK" and s == ["VOLUME_SPIKE_NO_CONTINUATION", "LATE_DAY_NOISE"]
    assert au.classify_fp(_fp(gap_pct=2.0, ret_close=-0.01))[0] == "GAP_THEN_FADE"
    assert au.classify_fp(_fp(accel=1.0, accel_next_min=-0.2, mfe_close=0.01))[0] == "SHORT_LIVED_ACCELERATION"
    assert au.classify_fp(_fp(rel_ret_z_3=float("nan")))[0] == "OTHER"  # eksik bağlam bayrak üretmez
    assert au.classify_fp(_fp(locked=True, rel_ret_z_3=0.1))[0] == "LOCKED_OR_ILLIQUID_HISTORY"
    flags = _fp(regime_shock=True, rel_ret_z_3=0.1)
    assert au.classify_fp(flags) == au.classify_fp(dict(reversed(list(flags.items()))))


def test_fn_taxonomy_deterministic_primary_secondary():
    assert au.classify_fn({}) == ("OTHER", [])
    p, s = au.classify_fn({"CONFIRMATION_DELAY": True, "PROVIDER_DELAY": True, "ABRUPT_VERTICAL_JUMP": True})
    assert p == "ABRUPT_VERTICAL_JUMP" and s == ["PROVIDER_DELAY", "CONFIRMATION_DELAY"]
    assert au.classify_fn({"BENCHMARK/CROSS_SECTION_GATE": True, "NO_EARLY_PRICE_EVIDENCE": False}) == \
        ("BENCHMARK/CROSS_SECTION_GATE", [])


def test_subset_labels_matches_metrics_on_session_subset():
    sess = np.array([0, 0, 1, 1, 2, 3])
    final = np.array([True, True, False, True, True, False])
    lab = _labels([10, 15, 0, 10, 10, 10], [101, 102, 100, 110, 100, 100], [0.05, 0.04, 0, 0.01, 0.0, 0],
                  [True, True, False, False], [20, 5, 0, 0], [110, 112, 100, 100], [100, 100, 100, 100])
    keep = np.array([True, False, True, False])  # seans 0 (yakalanan olay) + seans 2 (YP)
    rows, inv, sub = fx.subset_labels(lab, sess, keep)
    m = fr.metrics(final[rows], inv, sub, 0.03)
    assert m["events"] == 1 and m["caught_events"] == 1 and m["false_positive_rate"] == 1.0
    assert m["alert_sessions"] == 2 and m["lead_fraction_median"] == pytest.approx(0.1)


def test_lead_fraction_helper():
    assert au.lead_fraction(105.0, 100.0, 110.0) == 0.5
    assert au.lead_fraction(99.0, 100.0, 110.0) == 0.0
    assert au.lead_fraction(105.0, 100.0, 100.0) is None
    assert au.lead_fraction(float("nan"), 100.0, 110.0) is None


def test_grid_is_deterministic_and_has_no_ktlev():
    a = list(fx.grid(fx.WATCH_GRID))
    assert a == list(fx.grid(fx.WATCH_GRID)) and len(a) == 6 * 2 * 4 * 4 * 4 * 2 * 4
    assert "KTLEV" not in fx.ds2.REFERENCE_ASSETS
    sel_days, _ = fx.selection_scope()
    with pytest.raises(AssertionError):  # KTLEV seçim/ızgara satırlarına giremez
        fx.load_selection_rows(lambda name: [{"symbol": "KTLEV", "day": sel_days[0]}])
