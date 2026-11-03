"""Momentum PILOT derin analizi (yalnız araştırma): holdout reddi, sızıntı yok, gün-gruplu bölme, gerçek 1m arşivi,
nedensel ML öznitelikleri, deterministik matris/sonuç, mobil gölge birincil değil."""

import inspect
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_pilot import deep as dp
from app.research.momentum_pilot import experiment as ex
from app.research.momentum_pilot import split as sp
from app.research.momentum_round2 import experiment as r2

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=ISTANBUL_TZ)
DAYS = ["2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-30", "2026-11-02"]
STUDY = {"sha256": "s" * 64, "config": {"universe_sha256": "u" * 64, "prospective_start_session": "2026-10-22",
                                        "label_manifest_sha256": sp.LABEL_V2_SHA256}}


# ------------------------------------------------------------------ holdout
def test_future_holdout_rejected_for_cached_rows():
    guard = sp.HoldoutGuard(sp.build_manifest(DAYS[:3], STUDY, NOW))
    rows_days = sorted({"2026-10-22", "2026-10-27"})  # önbellekte kesim sonrası gün → load_pilot_context hatası
    with pytest.raises(sp.HoldoutAccessError, match=sp.HOLDOUT_ERROR):
        guard.check_sessions(rows_days)
    assert "guard.check_sessions" in inspect.getsource(ex.load_pilot_context)


def test_mobile_shadow_never_used_as_primary_in_pilot_pipeline():
    src = inspect.getsource(ex.load_pilot_context) + inspect.getsource(dp)
    assert "load_mobile_bars" not in src
    assert "sp.PRIMARY_SOURCE" in inspect.getsource(ex.load_pilot_context)


# ------------------------------------------------------------------ sızıntı
def test_static_feature_list_has_no_future_inputs():
    assert dp.static_leakage_check()["ok"]
    assert not dp.static_leakage_check(("price_z", "mfe_close"))["ok"]
    assert not dp.static_leakage_check(("lead_fraction",))["ok"]


def _synthetic_asset(symbol: str, seed: int, sessions=("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22")):
    rng = np.random.default_rng(seed)
    frames = []
    price = 100.0
    for d in sessions:
        idx = pd.date_range(f"{d} 09:55", f"{d} 17:55", freq="5min", tz=ISTANBUL_TZ)
        r = rng.normal(0, 0.002, len(idx))
        close = price * np.exp(np.cumsum(r))
        open_ = np.concatenate([[price], close[:-1]])
        frames.append(pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) * 1.001,
                                    "Low": np.minimum(open_, close) * 0.999, "Close": close,
                                    "Volume": rng.integers(1000, 5000, len(idx)).astype(float)}, index=idx))
        price = close[-1]
    prov = {"identity_check": "MATCH", "requested_symbol": symbol}
    return r1ds.AssetData(symbol, pd.concat(frames), prov, NOW)


def _truncate(a, cut):
    return r1ds.AssetData(a.symbol, a.bars[a.bars.index <= cut], a.provenance, a.fetched_at)


def test_ml_features_are_causal_truncation_invariant():
    a, b = _synthetic_asset("AAA", 1), _synthetic_asset("XU100", 2)
    day = date(2026, 10, 22)
    full = {r["t"]: r for r in r2.ext_rows_for_day(a, b, day, 15)}
    checked = 0
    for t in list(full)[10::17]:
        cut = pd.Timestamp(t) - timedelta(minutes=20)  # bar başlangıcı ≤ bilgi zamanı − 5 dk
        short = {r["t"]: r for r in r2.ext_rows_for_day(_truncate(a, cut), _truncate(b, cut), day, 15)}
        for k in ("ret_z_3", "ret_z_12", "accel", "accel_pos_3", "rel_ret_z_3", "relvol_3", "breakout_dist_atr",
                  "vwap_reclaim", "gap_pct", "session_ret_z"):
            if k in full[t]:
                assert dp._same(full[t][k], short[t].get(k)), (t, k)
        checked += 1
    assert checked >= 3


# ------------------------------------------------------------------ gün-gruplu bölme
def test_day_group_split_never_mixes_days():
    days = [date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26)]
    folds = dp.day_folds(days)
    assert [d for d, _ in folds] == days
    for d, train in folds:
        assert d not in train and set(train) | {d} == set(days)


# ------------------------------------------------------------------ 1m
def _min_bars(minutes, closes, vols=None, start="2026-10-22 10:00"):
    t0 = pd.Timestamp(start, tz=ISTANBUL_TZ).value
    c = np.asarray(closes, float)
    return pd.DataFrame({"bar_start_ns": t0 + np.asarray(minutes) * dp.MIN_NS, "close": c, "low": c, "high": c,
                         "volume": np.full(len(c), 100.0) if vols is None else np.asarray(vols, float)})


def test_1m_signals_use_only_archived_minutes():
    full = _min_bars(range(40), [100 + 0.2 * k for k in range(40)])
    holey = full.drop(index=[5]).reset_index(drop=True)  # 10:05 dakikası arşivde yok
    start = int(full["bar_start_ns"].iloc[0])
    end = start + 40 * dp.MIN_NS
    a = dp.signal_times(full, None, 1, None, start, end)
    b = dp.signal_times(holey, None, 1, None, start, end)
    # 10:20 başlangıçlı barın 15 dk geri bakışı 10:05 → eksik: o an için ivme/hacim hesaplanmaz, uydurulmaz
    assert a["acceleration"] is not None and b["acceleration"] is not None
    assert b["acceleration"] >= a["acceleration"]
    win = pd.Series(holey["volume"].to_numpy(), index=pd.to_datetime(holey["bar_start_ns"], utc=True))
    assert win.rolling("15min").count().min() < 15  # eksik dakika doldurulmadı
    assert dp.signal_times(full, None, 1, None, start, end)["volume_anomaly"] is None  # taban yoksa yok


def test_relative_return_needs_real_benchmark_bars():
    asset = _min_bars(range(30), [100 + 0.2 * k for k in range(30)])
    start = int(asset["bar_start_ns"].iloc[0])
    end = start + 30 * dp.MIN_NS
    assert dp.signal_times(asset, None, 1, None, start, end)["relative_return"] is None
    flat = _min_bars(range(30), [50.0] * 30)
    assert dp.signal_times(asset, flat, 1, None, start, end)["relative_return"] is not None


# ------------------------------------------------------------------ determinizm
def _rows(n_sessions=4, per=10, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sessions):
        d = date(2026, 10, 22) + timedelta(days=s)
        for k in range(per):
            rows.append({"symbol": f"S{s % 2}", "day": d, "t": datetime(2026, 10, 22, 10, 0, tzinfo=ISTANBUL_TZ)
                         + timedelta(days=s, minutes=5 * k), "status": "OK", "persistent": False, "data_gap": False,
                         "components": {"price_impulse": float(rng.random()), "volume_anomaly": float(rng.random()),
                                        "breakout": 0.0},
                         **{f: float(rng.normal()) for f in ("price_z", "ret_z_3", "ret_z_12", "accel",
                                                             "rel_ret_z_3", "xs_ret", "relvol_3",
                                                             "breakout_dist_atr", "gap_pct", "session_ret_z")},
                         "accel_pos_3": int(rng.integers(0, 4)), "vwap_reclaim": bool(rng.random() > 0.5),
                         "regime": "SHOCK" if rng.random() > 0.8 else "NORMAL", "recent_locked_regime": False})
    return rows


def test_feature_matrix_deterministic():
    from app.research.momentum_feasibility import experiment as fx
    a, b = dp.feature_matrix(fx.Panel(_rows())), dp.feature_matrix(fx.Panel(_rows()))
    assert a.shape == (40, len(dp.FEATURES))
    np.testing.assert_array_equal(a, b)


def test_logistic_baseline_deterministic_and_sensible():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(400, 3))
    y = (X[:, 0] + 0.2 * rng.normal(size=400) > 0.8).astype(float)
    st = dp.Standardizer().fit(X)
    b1, b2 = dp.fit_logistic(st.transform(X), y), dp.fit_logistic(st.transform(X), y)
    np.testing.assert_array_equal(b1, b2)
    assert b1[1] > 0 and abs(b1[1]) > abs(b1[2]) and abs(b1[1]) > abs(b1[3])
    assert dp.auc(dp.predict(b1, st.transform(X))[y == 1], dp.predict(b1, st.transform(X))[y == 0]) > 0.9


def test_standardizer_uses_training_rows_only():
    tr = np.array([[1.0], [3.0], [np.nan]])
    st = dp.Standardizer().fit(tr)
    assert st.med[0] == 2.0
    np.testing.assert_allclose(st.transform(np.array([[np.nan]])), st.transform(np.array([[2.0]])))


def test_evaluate_subset_equals_single_day_panel():
    T0 = pd.Timestamp("2026-10-22 10:00", tz=ISTANBUL_TZ).value
    sess = np.array([0, 0, 0, 1, 1, 1])
    t = np.array([T0 + k * 300_000_000_000 for k in (0, 1, 2)] * 2, dtype=np.int64) + np.repeat([0, 86_400 * 10**9], 3)
    entry = np.array([100.0, 101, 102, 50, 50, 50])
    ev0 = lv.Swing(0, 2, 99.0, 106.0, int(t[0]), int(t[2]), 0.07, True, lv.INTRADAY_EVALUABLE)
    lab = fr.LabelArrays(t, entry, entry, entry, np.ones(6, bool), np.zeros(2, bool), np.zeros(2, np.int64),
                         np.zeros(2), np.zeros(2))
    p = SimpleNamespace(sessions=[("A", date(2026, 10, 22)), ("A", date(2026, 10, 23))], sess=sess, labels={15: lab},
                        rows=[{}] * 6)
    mask = np.array([False, True, False, True, False, False])
    events = [[ev0], []]
    one = dp.evaluate_subset(p, events, mask, 15, {date(2026, 10, 22)})
    assert one["alerts"] == 1 and one["TP"] == 1 and one["FP"] == 0 and one["non_event_sessions"] == 0
    other = dp.evaluate_subset(p, events, mask, 15, {date(2026, 10, 23)})
    assert other["alerts"] == 1 and other["FP"] == 1 and other["FPR_v2"] == 1.0
    both = dp.evaluate_subset(p, events, mask, 15)
    assert both["alerts"] == 2 and both["TP"] == 1


def test_experimental_outputs_are_labelled():
    assert dp.EXPERIMENTAL == "EXPERIMENTAL — NOT FROZEN"
    assert dp.ML_LABEL == "EXPERIMENTAL ML BASELINE"


# ------------------------------------------------------------------ 5 günlük pilot, seçim ve dondurma
PILOT5 = ["2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-30"]


def test_observed_sessions_give_exactly_five_pilot_sessions():
    frame = pd.DataFrame({"session_date": [*PILOT5[:4], "2026-10-28", "2026-10-30", "2026-11-02", "2026-11-03"],
                          "session_class": ["FULL"] * 4 + ["SHORT_SESSION", "FULL", "FULL", "SHORT_SESSION"]})
    full = sp.observed_full_sessions(frame, "2026-10-22")
    assert "2026-10-28" not in full and "2026-10-29" not in full and "2026-11-03" not in full
    split = sp.resolve_split(full)
    assert split["pilot_sessions"] == PILOT5 and split["pilot_cutoff_session"] == "2026-10-30"
    assert split["status"] == sp.COMPLETE and split["holdout_sessions_observed"] == 1


def test_repository_manifest_complete_and_immutable(tmp_path):
    m = sp.load_manifest()
    b = m["manifest"]
    assert b["status"] == sp.COMPLETE and b["pilot_sessions"] == PILOT5 and b["pilot_cutoff_session"] == "2026-10-30"
    path = tmp_path / "m.json"
    path.write_text(sp.MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    from app.research.momentum_collector import manifest as mm
    again, changed = sp.refresh_manifest([*PILOT5, "2026-11-02", "2026-11-04"], mm.load(), NOW, path, tmp_path / "h")
    assert not changed and again == m


@pytest.mark.parametrize("day", ["2026-11-02", "2026-11-03", "2026-11-04", "2027-01-01"])
def test_holdout_dates_forbidden(day):
    guard = sp.HoldoutGuard(sp.load_manifest())
    with pytest.raises(sp.HoldoutAccessError, match=sp.HOLDOUT_ERROR):
        guard.check_session(day)
    guard.check_session("2026-10-30")


def test_five_day_folds_deterministic():
    days = [date.fromisoformat(d) for d in PILOT5]
    assert dp.day_folds(days) == dp.day_folds(list(days))
    assert len(dp.day_folds(days)) == 5 and all(len(t) == 4 and d not in t for d, t in dp.day_folds(days))


def test_candidate_grid_predeclared():
    assert list(dp.GRID) == ["C0_frozen_candidate", "C1_+weak_volume", "C2_+medium_volume",
                             "C3_+benchmark_shock_filter", "C4_+weak_volume+benchmark", "A0_round1_watch",
                             "A1_+benchmark_shock_filter", "A2_+weak_volume", "A3_+relative_strength",
                             "A4_+acceleration", "A5a_benchmark+weak_volume", "A5b_benchmark+relative",
                             "A5c_benchmark+acceleration", "A5d_weak_volume+relative",
                             "A5e_weak_volume+acceleration", "A5f_relative+acceleration"]
    assert all(set(s["gates"]) <= set(dp.GATES) and len(s["gates"]) <= 2 for s in dp.GRID.values())
    assert dp.TARGETS == {"FPR_v2_max": 0.25, "recall_evaluable_v2_min": 0.40, "median_lead_v2_max": 0.50}
    with pytest.raises(ValueError):
        dp.grid_mask(SimpleNamespace(rows=[]), {}, {"base": "A", "gates": ("new_gate",)})


def _m(fpr, rec, lead, prec=0.3, ev=10):
    return {"FPR_v2": fpr, "recall_evaluable_v2": rec, "median_lead_v2": lead, "precision_v2": prec,
            "evaluable_events": ev}


def test_selection_prefers_simpler_stable_rule_and_allows_no_candidate():
    good, lodo_ok = _m(0.2, 0.5, 0.4), {"catastrophic_folds": 0, "folds_meeting_targets": 3}
    pooled = {"A0_round1_watch": good, "A5d_weak_volume+relative": _m(0.1, 0.6, 0.3, 0.5)}
    lodo = {"A0_round1_watch": lodo_ok, "A5d_weak_volume+relative": {"catastrophic_folds": 0,
                                                                     "folds_meeting_targets": 5}}
    assert dp.select_candidate(pooled, lodo)["selected"] == "A0_round1_watch"  # daha az kapı önce
    lodo["A0_round1_watch"] = {"catastrophic_folds": 2, "folds_meeting_targets": 3}
    assert dp.select_candidate(pooled, lodo)["selected"] == "A5d_weak_volume+relative"
    bad = dp.select_candidate({"A0_round1_watch": _m(0.3, 0.5, 0.4)}, {"A0_round1_watch": lodo_ok})
    assert bad["selected"] is None and bad["decision"].startswith("NO CANDIDATE")
    ml_only = dp.select_candidate({"ML": good}, {"ML": lodo_ok})
    assert ml_only["selected"] is None  # ML ızgarada değil: otomatik seçilemez


def test_catastrophic_fold_definition():
    assert dp.catastrophic(_m(0.1, 0.1, 0.4)) and dp.catastrophic(_m(0.5, 0.6, 0.4))
    assert dp.catastrophic(_m(0.1, 0.6, 0.8)) and not dp.catastrophic(_m(0.2, 0.5, 0.5))


def test_frozen_candidate_deterministic_and_write_once(tmp_path):
    cand = {"feature": "rel_ret_z_3", "comparison": ">=", "threshold": 5.094139728812382}
    manifest = sp.load_manifest()
    a = dp.candidate_payload("A3_+relative_strength", cand, manifest, "2026-11-03T00:00:00+00:00")
    b = dp.candidate_payload("A3_+relative_strength", cand, manifest, "2026-11-03T00:00:00+00:00")
    assert a == b and a["label_v2_sha256"] == sp.LABEL_V2_SHA256 and a["pilot_manifest_sha256"] == manifest["sha256"]
    path = tmp_path / "c.json"
    d1 = dp.freeze_candidate(a, path)
    assert dp.freeze_candidate(b, path) == d1 and d1["sha256"] == sp.cd.sha256_of(a)
    with pytest.raises(dp.CandidateFreezeError):
        dp.freeze_candidate({**a, "grid_name": "A4_+acceleration"}, path)


def test_selection_pipeline_reads_only_manifest_pilot_sessions():
    src = inspect.getsource(ex.load_pilot_context)
    assert 'pilot = list(manifest["manifest"]["pilot_sessions"])' in src and "sp.HoldoutGuard(manifest)" in src
    assert "2026-11" not in inspect.getsource(ex.deep_stage) + inspect.getsource(dp)
