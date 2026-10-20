"""Başarısız final postmortem'i (yalnız araştırma): tüketilmiş final koruması ve deterministik sınıflayıcılar."""

import numpy as np
import pytest

from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_final import experiment as mf
from app.research.momentum_final import postmortem as pm
from app.research.momentum_round2 import dataset as ds2


def test_consumed_final_is_marked_and_blocked_in_candidate_selection(monkeypatch):
    assert ds2.CONSUMED_FINAL is True and len(ds2.CONSUMED_FINAL_SHA) == 64
    opened = []
    monkeypatch.setattr(pm.r2, "load_pkl", lambda name: opened.append(name) or [])
    with au.candidate_selection():
        assert au.selection_active()
        with pytest.raises(RuntimeError, match="Consumed final cannot be reused for candidate selection"):
            pm.open_consumed_final()
    assert opened == [] and not au.selection_active()
    with pytest.raises(RuntimeError, match="Consumed final"):
        fx.guarded_load("merged_new_d15.pkl", lambda n: pytest.fail("açılmamalı"))
    with pytest.raises(SystemExit):
        mf.freeze_stage()  # tüketilmiş finalden sonra yeni dondurma/seçim yok


def test_selection_context_nesting_and_exception_safety():
    with pytest.raises(ValueError):
        with au.candidate_selection():
            with au.candidate_selection():
                raise ValueError
    assert not au.selection_active()


@pytest.mark.parametrize("kw,expected", [
    (dict(intrinsic=True, caught_1m=True, caught_d0=True, caught_lower_thr=True, caught_d0_lower_thr=True),
     "INTRINSICALLY_UNPREDICTABLE"),
    (dict(intrinsic=False, caught_1m=True, caught_d0=True, caught_lower_thr=False, caught_d0_lower_thr=True),
     "BAR_RESOLUTION_LIMITED"),
    (dict(intrinsic=False, caught_1m=False, caught_d0=True, caught_lower_thr=False, caught_d0_lower_thr=True),
     "LATENCY_LIMITED"),
    (dict(intrinsic=False, caught_1m=False, caught_d0=False, caught_lower_thr=True, caught_d0_lower_thr=True),
     "THRESHOLD_LIMITED"),
    (dict(intrinsic=False, caught_1m=False, caught_d0=True, caught_lower_thr=True, caught_d0_lower_thr=True),
     "MIXED"),
    (dict(intrinsic=False, caught_1m=False, caught_d0=False, caught_lower_thr=False, caught_d0_lower_thr=True),
     "MIXED"),
    (dict(intrinsic=False, caught_1m=False, caught_d0=False, caught_lower_thr=False, caught_d0_lower_thr=False),
     "MISSING_INFORMATION"),
])
def test_counterfactual_category_deterministic(kw, expected):
    assert pm.counterfactual_category(**kw) == expected
    assert pm.counterfactual_category(**dict(reversed(list(kw.items())))) == expected


@pytest.mark.parametrize("minutes,bucket", [(None, "NO_USABLE_EVIDENCE"), (0, "LT_4MIN_1M_INSUFFICIENT"),
                                            (3.9, "LT_4MIN_1M_INSUFFICIENT"), (4, "4_15MIN_1M_POTENTIALLY_USEFUL"),
                                            (15, "4_15MIN_1M_POTENTIALLY_USEFUL"), (15.1, "GT_15MIN_NOT_BAR_LIMITED")])
def test_bar_resolution_bucket(minutes, bucket):
    assert pm.bar_resolution_bucket(minutes) == bucket


def test_gate_effect_arithmetic():
    e = pm.gate_effect({1, 2, 3, 4}, {10, 11}, {10}, {4}, {10}, set())
    assert e["fp_removed"] == 3 and e["fp_removed_share"] == 0.75
    assert e["caught_lost"] == 1 and e["caught_lost_share"] == 0.5 and e["early_lost_share"] == 1.0
    assert pm.gate_effect(set(), set(), set(), set(), set(), set())["fp_removed_share"] is None


def test_volume_gate_rule_deterministic():
    class P:
        ok = np.array([True, True, True, True])
        rel_ret_z_3 = np.array([6.0, 6.0, 4.5, 6.0])
        relvol_3 = np.array([0.5, 2.0, 3.0, np.nan])
    cand = {"feature": "rel_ret_z_3", "threshold": 5.0}
    assert pm.rule(P, cand).tolist() == [True, True, False, True]
    assert pm.rule(P, cand, gate=("relvol_3", 1.5)).tolist() == [False, True, False, False]  # NaN hacim → kapı yok
    assert pm.rule(P, cand, factor=0.8).tolist() == [True, True, True, True]
    assert list(pm.VOLUME_GATES) == ["no_gate", "weak_relvol3_ge_1.0", "medium_relvol3_ge_1.5",
                                     "strong_relvol3_ge_2.0", "r1_participation_volume_anomaly_ge_0.5"]


def test_counterfactual_delays_fixed_and_include_1m_proxy():
    assert pm.DELAYS == (0, 5, 10, 11, 15) and pm.SLIGHT_THRESHOLD == 0.8
    assert pm.THRESHOLD_FACTORS[0] == 1.0  # dondurulmuş eşik referans kolu


def test_ktlev_excluded_from_candidate_selection():
    assert "KTLEV" not in ds2.REFERENCE_ASSETS and "KTLEV" not in ds2.UNTOUCHED_ASSETS
    sel_days, _ = fx.selection_scope()
    with pytest.raises(AssertionError):
        fx.load_selection_rows(lambda name: [{"symbol": "KTLEV", "day": sel_days[0]}])
