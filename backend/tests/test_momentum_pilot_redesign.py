"""Momentum pilot sonrası yeniden tasarım (yalnız araştırma): öncü öznitelikler nedensel, veri politikası (tüketilmiş
final / holdout), etiket yalnız hedefte, küçük modeller deterministik, iki aşamalı kurma penceresi."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_pilot import redesign as rd
from app.research.momentum_pilot import split as sp

DAYS = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]


def _bars(seed: int, days=DAYS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames, price = [], 100.0
    for d in days:
        idx = pd.date_range(f"{d} 09:55", f"{d} 17:55", freq="5min", tz=ISTANBUL_TZ)
        close = price * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx))))
        open_ = np.concatenate([[price], close[:-1]])
        frames.append(pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) * 1.002,
                                    "Low": np.minimum(open_, close) * 0.998, "Close": close,
                                    "Volume": rng.integers(1000, 9000, len(idx)).astype(float)}, index=idx))
        price = close[-1]
    return pd.concat(frames)


def _panel(cut=None):
    bench = _bars(0)
    parts = []
    for k, s in enumerate(("AAA", "BBB", "CCC")):
        b = _bars(k + 1)
        bb = bench
        if cut is not None:
            b, bb = b[b.index <= cut], bench[bench.index <= cut]
        f = rd.asset_features(b, bb)
        f["symbol"] = s
        parts.append(f)
    return rd.add_cross_section(pd.concat(parts, ignore_index=True))


def test_precursor_features_are_causal():
    full = _panel()
    cut = pd.Timestamp("2026-08-06 13:00", tz=ISTANBUL_TZ)
    short = _panel(cut)
    cut_ns = cut.as_unit("ns").value
    a = full[full["bar_start_ns"] <= cut_ns].sort_values(["symbol", "bar_start_ns"]).reset_index(drop=True)
    b = short.sort_values(["symbol", "bar_start_ns"]).reset_index(drop=True)
    assert len(a) == len(b)
    for f in rd.FEATURES:
        np.testing.assert_allclose(a[f].to_numpy(float), b[f].to_numpy(float), rtol=1e-9, atol=1e-12,
                                   equal_nan=True, err_msg=f)


def test_feature_families_cover_requested_groups_and_no_future_names():
    assert set(rd.FEATURES) >= set(rd.COMPRESSION + rd.VOLUME + rd.RELATIVE + rd.STRUCTURE + rd.MARKET)
    from app.research.momentum_pilot import deep as dp
    assert dp.static_leakage_check(rd.FEATURES)["ok"]


def test_consumed_final_overlap_rejected(monkeypatch):
    from app.research.momentum_round2 import dataset as ds2
    monkeypatch.setattr(ds2, "selection_and_final", lambda: ([date(2026, 9, 28)], [date(2026, 9, 28)]))
    with pytest.raises(rd.DataPolicyError):
        rd.load_historical(["AKBNK"])


def test_holdout_audit_reports_forbidden():
    out = rd.holdout_audit("test")
    assert set(out["checks"].values()) == {"FORBIDDEN"} and out["cutoff"] == "2026-10-30"
    with pytest.raises(sp.HoldoutAccessError):
        sp.HoldoutGuard(sp.load_manifest()).check_session("2026-11-02")


def _grid():
    panel = _panel()
    days = [date.fromisoformat(d) for d in DAYS[3:]]
    return rd.Grid(panel, days, rd.estimated_visibility(15 * rd.MIN_NS), "TEST")


def test_grid_label_only_in_target_and_session_order():
    g = _grid()
    assert g.X.shape == (len(g.rows), len(rd.FEATURES))
    assert set(np.unique(g.y)) <= {0.0, 1.0}
    assert all((np.diff(g.info[g.rows_of[s]]) > 0).all() for s in g.rows_of)
    assert (g.visible == g.info + 15 * rd.MIN_NS).all()


def test_small_models_deterministic():
    rng = np.random.default_rng(5)
    X = rng.normal(size=(3000, len(rd.FEATURES)))
    X[rng.random(X.shape) < 0.05] = np.nan
    y = (np.nan_to_num(X[:, 0]) + 0.3 * rng.normal(size=3000) > 1.2).astype(float)
    p1 = rd.GBMClassifier(rounds=10).fit(X, y).predict(X)
    p2 = rd.GBMClassifier(rounds=10).fit(X, y).predict(X)
    np.testing.assert_array_equal(p1, p2)
    imp = rd.GBMClassifier(rounds=10).fit(X, y).importance()
    assert int(np.argmax(imp)) == 0
    f1, _ = rd.fit_scorer("logistic", X, y)
    f2, _ = rd.fit_scorer("logistic", X, y)
    np.testing.assert_array_equal(f1(X), f2(X))


def test_two_stage_requires_recent_arming_and_confirmation():
    n = 20
    rows = pd.DataFrame({"p_ret3_z": [0.0] * n, "e_exp_ratio": [1.0] * n, "s_dist_sess_high": [-0.1] * n})
    rows.loc[15, "p_ret3_z"] = 2.0  # onay 15. barda
    rows.loc[18, "p_ret3_z"] = 2.0  # onay 18. barda
    g = SimpleNamespace(rows_of={0: np.arange(n)}, col=lambda c: rows[c].to_numpy(float))
    arm = np.zeros(n)
    arm[4] = 1.0  # kurma 4. barda; 60 dk = 12 bar → 15. bar penceredir, 18. bar değildir
    m = rd.two_stage_mask(g, arm, 0.5)
    assert m[15] and not m[18] and m.sum() == 1


def test_blocks_are_contiguous_grouped_days():
    days = [date(2026, 8, 1) + pd.Timedelta(days=k) for k in range(12)]
    bl = rd.blocks(days, 5)
    assert sum(len(b) for b in bl) == 12 and [d for b in bl for d in b] == sorted(days)
