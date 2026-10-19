"""Momentum Round 2: genişletilmiş öznitelikler, kesitsel bağlam, iki aşamalı dedektör, walk-forward bölme."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_round2 import dataset as ds
from app.research.momentum_round2 import experiment as ex
from app.services.momentum import cross_section as xsec
from app.services.momentum import extended_features as xf
from app.services.momentum.two_stage import SessionTracker, TwoStageConfig, raw_watch

PRIOR_DAYS = [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)]
TODAY = date(2026, 10, 9)


def _session(day, closes, volumes=None, opens=None, start=time(10, 0)):
    n = len(closes)
    idx = pd.DatetimeIndex([datetime.combine(day, start, tzinfo=ISTANBUL_TZ) + timedelta(minutes=5 * i)
                            for i in range(n)])
    c = np.asarray(closes, dtype=float)
    o = np.asarray(opens, dtype=float) if opens is not None else np.concatenate([[c[0]], c[:-1]])
    v = np.asarray(volumes if volumes is not None else [1000.0] * n, dtype=float)
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.001, "Low": np.minimum(o, c) * 0.999,
                         "Close": c, "Volume": v}, index=idx)


def _noisy(seed, n=60, level=100.0, step=0.002):
    rng = np.random.default_rng(seed)
    return level * np.exp(np.cumsum(rng.normal(0, step, n)))


def _history(levels=(100.0, 100.0, 100.0, 100.0)):
    return pd.concat([_session(d, _noisy(i, level=lv)) for i, (d, lv) in enumerate(zip(PRIOR_DAYS, levels))])


def _features(today_closes, bench_today=None, volumes=None, opens=None, prior=None):
    prior = prior if prior is not None else _history()
    day = _session(TODAY, today_closes, volumes, opens)
    base = xf.build_baseline(prior)
    if bench_today is None:
        return xf.bar_features(day, base), day, base
    bprior = _history()
    bday = _session(TODAY, bench_today)
    return (xf.bar_features(day, base, bday, float(bprior["Close"].iloc[-1]), xf.bench_sigma(bprior)), day, base)


def _same(a, b):
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    return a == b or (isinstance(a, float) and abs(a - b) < 1e-12)


# ------------------------------------------------------------------ nedensellik
def test_extended_features_causal_full_day_equals_truncated():
    closes = list(_noisy(42, n=50))
    full, day, base = _features(closes, bench_today=list(_noisy(7, n=50)))
    bprior = _history()
    bday = _session(TODAY, list(_noisy(7, n=50)))
    for k in (1, 2, 5, 17, 33, 50):
        part = xf.bar_features(day.iloc[:k], base, bday[bday.index <= day.index[k - 1]],
                               float(bprior["Close"].iloc[-1]), xf.bench_sigma(bprior))
        for col in full.columns:
            assert _same(full.iloc[k - 1][col], part.iloc[-1][col]), (k, col)


def test_acceleration_no_lookahead_future_bars_ignored():
    closes = list(_noisy(3, n=40))
    base_feats, _, _ = _features(closes)
    shocked = closes[:30] + [c * 1.2 for c in closes[30:]]  # 30. bardan sonra büyük sıçrama
    shocked_feats, _, _ = _features(shocked)
    for col in ("accel", "slope_3", "ret_z_3", "accel_pos_3", "vwap_time_above"):
        assert _same(base_feats.iloc[29][col], shocked_feats.iloc[29][col]), col


def test_snapshot_respects_provider_delay():
    prior = _history()
    today = _session(TODAY, list(_noisy(5, n=40)))
    bars = pd.concat([prior, today])
    t = today.index[20].to_pydatetime() + timedelta(minutes=20)  # bar 20 tam erişilebilir, 21+ değil
    snap = xf.extended_snapshot(bars, t)
    assert snap["n_bars"].value == 21
    later = bars.copy()
    later.iloc[len(prior) + 21:, later.columns.get_loc("Close")] *= 1.3
    assert xf.extended_snapshot(later, t)["ret_z_3"].value == snap["ret_z_3"].value


def test_acceleration_flat_market_is_zero_and_rising_is_positive():
    flat, _, _ = _features([100.0] * 30)
    assert abs(flat.iloc[-1]["accel"]) < 1e-9
    assert abs(flat.iloc[-1]["ret_z_3"]) < 1e-9
    rising, _, _ = _features([100.0] * 20 + [100.0 * 1.004 ** k for k in range(1, 7)])
    assert rising.iloc[-1]["accel"] > 0.5
    assert rising.iloc[-1]["accel_pos_3"] == 3


# ------------------------------------------------------------------ benchmark-göreli
def test_benchmark_relative_return():
    up = [100.0 * 1.003 ** k for k in range(30)]
    same, _, _ = _features(up, bench_today=up)
    assert abs(same.iloc[-1]["rel_ret_z_3"]) < 1e-6  # piyasayla birlikte yükselen: göreli güç yok
    alone, _, _ = _features(up, bench_today=[100.0] * 30)
    assert alone.iloc[-1]["rel_ret_z_3"] > 1.0


def test_benchmark_missing_is_none_not_zero():
    feats, _, _ = _features(list(_noisy(9, n=20)))
    assert feats.iloc[-1]["rel_ret_z_3"] is None and feats.iloc[-1]["rel_accel"] is None
    snap = xf.to_feature_values(feats.iloc[-1])
    assert snap["rel_ret_z_3"].value is None and snap["rel_ret_z_3"].confidence == 0.0


def test_benchmark_bar_missing_at_timestamp_gives_none():
    closes = list(_noisy(11, n=20))
    bprior = _history()
    day = _session(TODAY, closes)
    bday = _session(TODAY, list(_noisy(12, n=20))).drop(index=day.index[-1])  # son bar benchmark'ta yok
    feats = xf.bar_features(day, xf.build_baseline(_history()), bday, float(bprior["Close"].iloc[-1]),
                            xf.bench_sigma(bprior))
    assert pd.isna(feats.iloc[-1]["rel_ret_z_1"])  # ileri doldurma yok
    assert xf.to_feature_values(feats.iloc[-1])["rel_ret_z_1"].value is None


# ------------------------------------------------------------------ kesitsel
def test_cross_sectional_percentile_excludes_self_and_requires_universe():
    panel = {f"S{i}": float(i) for i in range(20)}
    ranks = xsec.cross_sectional_ranks({"S19": 19.0, "S0": 0.0}, panel)
    assert ranks["S19"] == 1.0 and ranks["S0"] == 0.0
    assert xsec.percentile_against(5.0, [1.0, 2.0, None]) is None  # yetersiz panel → None (uydurma 0 yok)
    assert xsec.percentile_against(None, list(range(20))) is None


def test_cross_sectional_no_leakage_uses_same_timestamp_only():
    t0 = datetime(2026, 10, 9, 11, 0, tzinfo=ISTANBUL_TZ)
    t1 = t0 + timedelta(minutes=5)
    rows = []
    for i in range(12):
        for t, val in ((t0, float(i)), (t1, 100.0 + i)):
            rows.append({"symbol": f"S{i}", "t": pd.Timestamp(t), "ret_z_3": val, "relvol_3": val, "accel": val,
                         "session_ret_pct": 1.0, "bench_rv_ratio": 1.0})
    ref = pd.DataFrame(rows)
    target = pd.DataFrame([{"symbol": "NEW", "t": pd.Timestamp(t0), "ret_z_3": 50.0, "relvol_3": 50.0,
                            "accel": 50.0, "session_ret_pct": 1.0, "bench_rv_ratio": 1.0}])
    out = ex.add_cross_section(target, ref)
    assert out.iloc[0]["xs_ret"] == 1.0  # t1'in (gelecek) 100+ değerleri görülseydi 0 olurdu


def test_market_regime_shock_and_unknown():
    assert xsec.market_regime({f"S{i}": -2.5 for i in range(12)}, None)["regime"] == xsec.REGIME_SHOCK
    assert xsec.market_regime({f"S{i}": 0.2 for i in range(12)}, 1.0)["regime"] == xsec.REGIME_NORMAL
    assert xsec.market_regime({"A": 1.0}, None)["regime"] is None


# ------------------------------------------------------------------ gap / VWAP / kilit rejimi / güven
def test_gap_follow_through_trigger_requires_follow_through():
    closes = [102.0 * 1.002 ** k for k in range(8)]
    feats, _, _ = _features(closes, opens=[102.0] + closes[:-1])
    f = feats.iloc[-1].to_dict()
    assert f["gap_pct"] > 1.0 and f["gap_follow_z"] > 1.0
    cfg = TwoStageConfig(use_gap=True)
    assert raw_watch({**f, "r1_level": ma.LEVEL_NONE}, cfg)[0]
    faded, _, _ = _features([102.0, 101.5, 101.0, 100.6, 100.4, 100.3, 100.2, 100.1], opens=[102.0] + [102.0] * 7)
    assert not raw_watch({**faded.iloc[-1].to_dict(), "r1_level": ma.LEVEL_NONE}, cfg)[0]
    assert not raw_watch({**f, "r1_level": ma.LEVEL_NONE}, TwoStageConfig())[0]  # gap tek başına alarm değil


def test_vwap_reclaim():
    feats, _, _ = _features([100.0, 99.0, 98.5, 98.8, 99.5, 100.5, 101.0])
    assert not bool(feats.iloc[2]["vwap_reclaim"])
    assert bool(feats.iloc[-1]["vwap_reclaim"])
    assert 0 < feats.iloc[-1]["vwap_time_above"] < 1


def test_locked_regime_lowers_confidence_but_keeps_baseline():
    locked = pd.concat([_session(d, [100.0] * 60) for d in PRIOR_DAYS[1:]])
    prior = pd.concat([_session(PRIOR_DAYS[0], _noisy(1)), locked])
    base = xf.build_baseline(prior)
    assert base.recent_locked_regime and base.recent_locked_sessions == 3
    assert base.sigma_raw is not None and base.confidence == xf.EXT_DEFAULT.locked_fallback_confidence
    feats = xf.bar_features(_session(TODAY, [100.0 * 1.01 ** k for k in range(10)]), base)
    assert feats.iloc[-1]["ret_z_3"] is not None  # kör değil
    normal = xf.build_baseline(_history())
    assert not normal.recent_locked_regime and normal.confidence == pytest.approx(0.4)


def test_feature_confidence_and_none_values():
    feats, _, _ = _features(list(_noisy(4, n=2)))
    snap = xf.to_feature_values(feats.iloc[-1])
    assert snap["ret_z_12"].samples == 2 and snap["ret_z_12"].confidence < snap["ret_z_1"].confidence
    assert snap["accel"].value is None and snap["accel"].confidence == 0.0


# ------------------------------------------------------------------ iki aşamalı dedektör
def _f(level, **extra):
    return {"r1_level": level, **extra}


def test_watch_before_strong_state_transition():
    tr = SessionTracker(TwoStageConfig(watch_k=1, watch_n=1, strong_k=1, strong_n=1, allow_direct_strong=False))
    first, reasons = tr.step(_f(ma.LEVEL_STRONG))
    assert first == ma.LEVEL_WATCH and "STRONG_DEFERRED_UNTIL_WATCH" in reasons
    assert tr.step(_f(ma.LEVEL_STRONG))[0] == ma.LEVEL_STRONG


def test_direct_strong_only_for_explicit_extreme():
    cfg = TwoStageConfig(watch_k=1, watch_n=1, strong_k=1, strong_n=1)
    extreme = _f(ma.LEVEL_STRONG, price_z_ext=7.0, relvol_3=6.0, breakout_dist_atr=1.0)
    level, reasons = SessionTracker(cfg).step(extreme)
    assert level == ma.LEVEL_STRONG and "DIRECT_STRONG_EXTREME" in reasons
    assert SessionTracker(cfg).step(_f(ma.LEVEL_STRONG, price_z_ext=3.0))[0] == ma.LEVEL_WATCH


def test_watch_persistence_2_of_3():
    tr = SessionTracker(TwoStageConfig())
    assert tr.step(_f(ma.LEVEL_WATCH))[0] == ma.LEVEL_NONE
    assert tr.step(_f(ma.LEVEL_WATCH))[0] == ma.LEVEL_WATCH


def test_context_gate_unavailable_is_skipped_not_faked():
    cfg = TwoStageConfig(use_rel=True, use_xs=True)
    ok, reasons = raw_watch(_f(ma.LEVEL_WATCH), cfg)
    assert ok and "BENCHMARK_UNAVAILABLE" in reasons and "CROSS_SECTION_UNAVAILABLE" in reasons
    assert not raw_watch(_f(ma.LEVEL_WATCH, rel_ret_z_3=0.2, xs_ret=0.99), cfg)[0]
    assert not raw_watch(_f(ma.LEVEL_WATCH, rel_ret_z_3=2.0, xs_ret=0.5), cfg)[0]


def test_strong_precision_must_exceed_watch_for_selection():
    def metric(p, r, fpr, lead=0.3, alerts=50):
        return {"precision": p, "recall": r, "false_positive_rate": fpr, "alert_sessions": alerts,
                "lead_fraction_median": lead}
    good = {"watch": metric(0.15, 0.5, 0.2), "strong": metric(0.25, 0.3, 0.03)}
    bad = {"watch": metric(0.15, 0.5, 0.2), "strong": metric(0.14, 0.3, 0.03)}
    assert ex.eligible(good, [good, good, good])[0]
    ok, checks = ex.eligible(bad, [bad, bad, bad])
    assert not ok and not checks["strong_precision_gt_watch"]


def test_deterministic_classification_and_hash():
    rows = []
    for j in range(12):
        rows.append({"symbol": "AAA", "day": TODAY, "t": datetime(2026, 10, 9, 10, 0, tzinfo=ISTANBUL_TZ)
                     + timedelta(minutes=5 * j), "status": ma.STATUS_OK,
                     "r1_level": ma.LEVEL_STRONG if j % 3 else ma.LEVEL_WATCH, "rel_ret_z_3": 1.5, "xs_ret": 0.95,
                     "rel_ret_z_6": 2.0, "relvol_3": 2.0})
    cfg = ex.two_stage_config("R2_C8_TWO_STAGE")
    a = [r["final_level"] for r in ex.classify_two_stage(rows, cfg)]
    b = [r["final_level"] for r in ex.classify_two_stage(list(reversed(rows)), cfg)]
    assert a == b
    assert ex.candidate_hash("R2_C8_TWO_STAGE") == ex.candidate_hash("R2_C8_TWO_STAGE")
    assert ex.candidate_hash("R2_C8_TWO_STAGE") != ex.candidate_hash("R2_C9_GAP")


# ------------------------------------------------------------------ bölme / izolasyon
def test_walk_forward_split_is_chronological():
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(42)]
    folds = ds.walk_forward_folds(days)
    assert len(folds) == ds.N_SELECTION_BLOCKS - 1
    for f in folds:
        assert max(f["train"]) < min(f["validate"])
        assert not set(f["train"]) & set(f["validate"])
    assert len(folds[-1]["train"]) > len(folds[0]["train"])  # genişleyen pencere


def test_untouched_assets_isolated_and_ktlev_excluded():
    ref, new = set(ds.REFERENCE_ASSETS), set(ds.UNTOUCHED_ASSETS)
    assert not ref & new
    assert ds.HOLDOUT_CASE not in ref and ds.HOLDOUT_CASE not in new
    assert ds.BENCHMARK not in ref | new
    split = {"calibration": [date(2026, 8, d) for d in range(1, 21)],
             "validation": [date(2026, 9, d) for d in range(1, 11)],
             "holdout": [date(2026, 10, d) for d in range(1, 11)]}
    sel, final = ds.selection_and_final(split)
    assert max(sel) < min(final) and final == split["holdout"]


def test_round1_final_config_pinned():
    assert ex.ROUND1_FINAL.confirm_k == 3 and ex.ROUND1_FINAL.rule_mode == "GROUPS"
    from app.research.momentum_calibration import experiment as r1x
    assert r1x.config_hash(ex.ROUND1_FINAL) == ex.ROUND1_FINAL_SHA
