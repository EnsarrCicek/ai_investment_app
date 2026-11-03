"""Momentum kesitsel lider sıralaması (yalnız araştırma): sıra yalnız aynı zaman damgasında, eşitlikte deterministik ve
genişlemeyen Top-K, gelecek bar yok, seans gruplaması, ölçülmüş pilot görünürlüğü, gerçek 1m arşivi, holdout yok."""

import inspect
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_pilot import experiment as ex
from app.research.momentum_pilot import ranking as rk
from app.research.momentum_pilot import redesign as rd
from app.research.momentum_pilot import split as sp

T0 = pd.Timestamp("2026-08-06 10:00", tz=ISTANBUL_TZ).as_unit("ns").value
STEP = rk.BAR_NS


def _snap(scores: dict, ts: int = T0) -> pd.DataFrame:
    return pd.DataFrame({"symbol": list(scores), "bar_start_ns": ts, "s": list(scores.values())})


def test_rank_only_within_same_timestamp():
    df = pd.concat([_snap({"A": 0.9, "B": 0.1}), _snap({"A": 0.1, "B": 0.95, "C": 0.5}, T0 + STEP)],
                   ignore_index=True)
    r = rk.rank_within_timestamp(df, "s").to_numpy()
    assert list(r) == [1, 2, 3, 1, 2]


def test_ties_are_deterministic_and_topk_never_expands():
    df = _snap({"D": 0.8, "B": 0.8, "C": 0.8, "A": 0.8, "E": np.nan})
    r1 = rk.rank_within_timestamp(df, "s").to_numpy()
    r2 = rk.rank_within_timestamp(df.sample(frac=1, random_state=3).sort_index(), "s").to_numpy()
    np.testing.assert_array_equal(r1, r2)
    assert dict(zip(df["symbol"], r1))["A"] == 1 and np.isnan(r1[-1])  # eşitlik: sembol artan; NaN evrende yok
    assert rk.topk_mask(r1, 3).sum() == 3  # dört eşit skor varken Top-3 tam 3


def _bars(seed, days=("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")):
    rng = np.random.default_rng(seed)
    frames, p = [], 100.0
    for d in days:
        idx = pd.date_range(f"{d} 09:55", f"{d} 17:55", freq="5min", tz=ISTANBUL_TZ)
        c = p * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx))))
        o = np.concatenate([[p], c[:-1]])
        frames.append(pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.002, "Low": np.minimum(o, c) * 0.998,
                                    "Close": c, "Volume": rng.integers(1000, 9000, len(idx)).astype(float)},
                                   index=idx))
        p = c[-1]
    return pd.concat(frames)


def _ranked(cut=None):
    bench = _bars(0)
    parts = []
    for k, s in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE")):
        b, bb = _bars(k + 1), bench
        if cut is not None:
            b, bb = b[b.index <= cut], bench[bench.index <= cut]
        f = rd.asset_features(b, bb)
        f["symbol"] = s
        parts.append(f)
    return rk.add_ranks(rk.add_percentiles(rd.add_cross_section(pd.concat(parts, ignore_index=True))))


def test_ranks_use_no_future_bars():
    cut = pd.Timestamp("2026-08-06 12:30", tz=ISTANBUL_TZ)
    full, short = _ranked(), _ranked(cut)
    a = full[full["bar_start_ns"] <= cut.as_unit("ns").value].sort_values(["symbol", "bar_start_ns"])
    b = short.sort_values(["symbol", "bar_start_ns"])
    for c in ("MOMENTUM_RANK", "EARLY_LEADER_RANK", "CONFIRMED_LEADER_RANK", "rank_MOMENTUM_RANK",
              "rank_CONFIRMED_LEADER_RANK"):
        np.testing.assert_allclose(a[c].to_numpy(float), b[c].to_numpy(float), equal_nan=True, err_msg=c)


def test_persistence_never_crosses_sessions():
    rows = {0: np.arange(0, 4), 1: np.arange(4, 8)}
    g = type("G", (), {"rows_of": rows})()
    m = np.array([0, 0, 1, 1, 1, 0, 0, 0], dtype=bool)  # oturum 0 sonu + oturum 1 başı
    assert list(rk.persistent(m, g, 2)) == [False, False, False, True, False, False, False, False]
    assert list(rk.persistent(m, g, 3)) == [False] * 8


def test_policy_grid_predeclared_and_small():
    assert len(rk.POLICIES) == 3 * (3 * 3 + 2 * 3)
    assert rk.KS == (1, 3, 5) and rk.PERSISTENCE == (1, 2, 3) and rk.FLOOR == 0.75
    assert set(rk.SCORE_NAMES) == {"MOMENTUM_RANK", "EARLY_LEADER_RANK", "CONFIRMED_LEADER_RANK"}


def test_ranking_quality_deterministic():
    b = np.repeat([T0, T0 + STEP], 4)
    rows = pd.DataFrame({"bar_start_ns": b, "r": [1, 2, 3, 4, 1, 2, 3, 4]})
    g = type("G", (), {"col": lambda self, c: rows[c].to_numpy(float), "rows": rows,
                       "y": np.array([1, 0, 0, 1, 0, 0, 1, 0], float),
                       "day": np.array([date(2026, 8, 6)] * 8)})()
    q1, q2 = rk.ranking_quality(g, "r"), rk.ranking_quality(g, "r")
    assert q1 == q2
    assert q1["precision@1"] == 0.5 and q1["recall@3"] == pytest.approx(2 / 3, abs=1e-4)


def test_minute_scores_use_only_archived_minutes():
    t = T0 + np.arange(40) * rk.MIN_NS
    def frame(sym, closes, drop=()):
        d = pd.DataFrame({"symbol": sym, "bar_start_ns": t, "session_date": "2026-10-22", "close": closes,
                          "volume": 100.0})
        return d.drop(index=list(drop))
    bars = pd.concat([frame("XU100", np.linspace(100, 101, 40)), frame("AAA", np.linspace(10, 11, 40)),
                      frame("BBB", np.linspace(20, 21, 40), drop=(20,))], ignore_index=True)
    s = rk.minute_scores(bars, "XU100", 1)
    bbb = s[s["symbol"] == "BBB"].set_index("bar_start_ns")
    assert T0 + 20 * rk.MIN_NS not in bbb.index  # eksik dakika eklenmez
    assert np.isnan(bbb.loc[T0 + 35 * rk.MIN_NS, "ret15"])  # 15 dk geri bakışı eksik dakika → değer yok
    assert np.isfinite(bbb.loc[T0 + 36 * rk.MIN_NS, "ret15"])


def test_measured_pilot_visibility_uses_probe_first_seen():
    probe = pd.DataFrame({"symbol": ["AAA"], "bar_start_ns": [T0], "bar_end_ns": [T0 + STEP],
                          "first_seen_ns": [T0 + STEP + 16 * rk.MIN_NS]})
    fn, med = rd.pilot_visibility(probe)
    rows = pd.DataFrame({"symbol": ["AAA", "BBB"], "bar_start_ns": [T0, T0]})
    vis, meas = fn(rows, np.array([T0 + STEP, T0 + STEP]))
    assert meas.tolist() == [True, False]
    assert vis[0] == T0 + STEP + 16 * rk.MIN_NS and vis[1] == T0 + STEP + med


def test_stage_guards_holdout_and_consumed_final():
    src = inspect.getsource(ex.ranking_stage)
    assert 'str(max(sel)) == "2026-09-25"' in src and "max(sel) < min(final)" in src
    assert "holdout_audit(\"before\")" in src and "holdout_audit(\"after\")" in src
    assert "sp.load_primary_bars(a.db, guard, pilot_s" in src
    with pytest.raises(sp.HoldoutAccessError):
        sp.HoldoutGuard(sp.load_manifest()).check_sessions(["2026-11-02"])
