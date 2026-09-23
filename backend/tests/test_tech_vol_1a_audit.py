"""TECH-VOL 1A araştırma yardımcıları — ağ yok, sentetik girdiler."""

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone
from app.research.flow_v1.study import TechnicalBlindViolation
from app.research.technical_volume_audit import states as S
from app.research.technical_volume_audit import study as T

_ZONE = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=3, last_touch_index=10)


def test_high_volume_flag_matches_production_threshold():
    assert S.is_high_volume(1.5) is True
    assert S.is_high_volume(1.4999) is False
    assert S.is_high_volume(float("nan")) is None


def test_price_direction_band():
    assert S.price_direction(0.0051) == "UP"
    assert S.price_direction(0.005) == "FLAT"
    assert S.price_direction(-0.005) == "FLAT"
    assert S.price_direction(-0.0051) == "DOWN"
    assert S.price_direction(float("nan")) is None


def test_spike_vs_sustained():
    assert S.spike_or_sustained(0) == "SPIKE"
    assert S.spike_or_sustained(1) == "INTERMEDIATE"
    assert S.spike_or_sustained(2) == "SUSTAINED"
    assert S.spike_or_sustained(None) is None


def test_production_window_requires_pre_window_bar_and_min_history():
    idx = pd.bdate_range("2024-01-02", periods=200).tz_localize("Europe/Istanbul")
    seg = pd.DataFrame({"Close": np.arange(200.0)}, index=idx)
    assert S.production_window(seg, 100) is None  # T-6ay segment başlangıcından önce -> leading edge
    df = S.production_window(seg, 199)
    assert df is not None and df.index[0].date() >= S.window_start(idx[199])
    assert len(df) >= S.MIN_HISTORY_DAYS


def test_strong_precondition_uses_forced_high_volume():
    bull = BreakoutEvent(index=1, direction="BULLISH", zone=_ZONE, breakout_atr=1.0, confirmed=True)
    state = SignalInputs(technical_score=50.0, market_structure="UPTREND", breakout_event=bull,
                         relative_volume_class="LOW", mtf_aligned=True, mtf_consensus="UP")
    assert S.strong_precondition(state, classify_signal) is True
    assert S.strong_precondition(dataclasses.replace(state, technical_score=30.0), classify_signal) is False


def test_group_delta_is_date_balanced_and_requires_min_group():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"] * 4 + ["2024-01-03"] * 3),
        "ex_10": [0.05, 0.03, 0.01, -0.01, 0.10, 0.0, 0.0],
    })
    g = pd.Series([True, True, False, False, True, False, False])
    c = ~g
    out = T.group_delta(df, g, c, "ex_10", 10)
    # 2. tarihte grup yalnız 1 gözlem -> dışlanır; 1. tarih: 0.04 - 0.00
    assert out["return_delta"]["n_dates"] == 1
    assert out["return_delta"]["mean"] == pytest.approx(0.04)


def test_classification_rule():
    ok_ic = {"ci_low": -0.005, "ci_high": 0.005}
    assert T.classify({"ci_low": -0.02, "ci_high": -0.001}, ok_ic, None, None) == "HARMFUL"
    assert T.classify({"ci_low": 0.001, "ci_high": 0.02}, ok_ic, 0.01, -0.01) == "DIRECTION-CONDITIONAL"
    assert T.classify({"ci_low": 0.001, "ci_high": 0.02}, ok_ic, 0.2, -0.01) == "SUPPORTED"
    assert T.classify({"ci_low": -0.002, "ci_high": 0.002}, ok_ic, None, None) == "REDUNDANT"
    assert T.classify({"ci_low": -0.002, "ci_high": 0.002}, {"ci_low": -0.03, "ci_high": -0.02}, None, None) == "INCONCLUSIVE"
    assert T.classify({"ci_low": -0.01, "ci_high": 0.01}, ok_ic, None, None) == "INCONCLUSIVE"


def test_blind_guard_rejects_technical_level_keys():
    T.assert_blind({"PRIMARY": {"return_delta": {"mean": 0.0}}})
    for key in ("technical_ic", "strong_return", "technical_positive_return", "signal_class_return"):
        with pytest.raises(TechnicalBlindViolation):
            T.assert_blind({"x": {key: 1}})


def test_raw_and_state_data_paths_are_git_ignored():
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("git") is None:
        pytest.skip("git yok")
    root = Path(__file__).resolve().parents[2]
    rel = "backend/app/research/technical_volume_audit/data/production_states.json.gz"
    assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=root).returncode == 0
