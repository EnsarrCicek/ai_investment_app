"""CURRENT_BEHAVIOR_CHARACTERIZATION — TECH-VOL 1A.

Bu testler, yüksek hacmin Technical davranışını BUGÜN tam olarak nasıl
etkilediğini BELGELER (gelecekteki bir düzeltmeden önce referans). Kalıcı bir
ürün sözleşmesi DEĞİLDİR: bir düzeltme bileti bu davranışı bilinçli olarak
değiştirirse, bu testler o bilette açıkça güncellenmelidir.

Belgelenen mevcut davranış:
- Yüksek hacim = RV20 (V_T / 20 seans medyanı, T dahil) >= 1.5 (HIGH/VERY_HIGH).
- Tek davranışsal etki: diğer tüm STRONG koşulları sağlanıyorsa etiket
  BULLISH_CONFIRMED -> STRONG_BULLISH_INITIATION olur.
- technical_score ve confidence hacimden BAĞIMSIZDIR.
- Bearish sınıflarda hacmin hiçbir etkisi yoktur (yönsel simetri YOK).
"""

import dataclasses
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.engine import technical_score_series
from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.engine import compute_technical_analysis
from app.engines.technical.relative_volume import classify_relative_volume, relative_volume_series
from app.engines.technical.scoring import DEFAULT_TECHNICAL_FAMILY_WEIGHTS, compute_scoring_config_hash
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone

_ZONE = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=3, last_touch_index=10)
_BULL = BreakoutEvent(index=10, direction="BULLISH", zone=_ZONE, breakout_atr=2.0, confirmed=True, retest_held=None)
_STRONG_STATE = SignalInputs(technical_score=45.0, market_structure="UPTREND", breakout_event=_BULL,
                             relative_volume_class="NORMAL", mtf_aligned=True, mtf_consensus="UP")
_WEIGHTS = {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667,
            "ema_slope": 0.2, "roc": 0.1665}


@pytest.mark.parametrize(
    "rv_class, expected",
    [("LOW", "BULLISH_CONFIRMED"), ("NORMAL", "BULLISH_CONFIRMED"), ("UNKNOWN", "BULLISH_CONFIRMED"),
     ("HIGH", "STRONG_BULLISH_INITIATION"), ("VERY_HIGH", "STRONG_BULLISH_INITIATION")],
)
def test_high_volume_only_flips_confirmed_to_strong_under_strong_preconditions(rv_class, expected):
    assert classify_signal(dataclasses.replace(_STRONG_STATE, relative_volume_class=rv_class)) == expected


@pytest.mark.parametrize(
    "state",
    [
        SignalInputs(technical_score=-50.0, market_structure="DOWNTREND"),  # bearish
        SignalInputs(technical_score=39.9, market_structure="UPTREND", breakout_event=_BULL, mtf_aligned=True, mtf_consensus="UP"),
        SignalInputs(technical_score=45.0, market_structure="RANGE", breakout_event=_BULL, mtf_aligned=True, mtf_consensus="UP"),
        SignalInputs(technical_score=45.0, market_structure="UPTREND", breakout_event=None, mtf_aligned=True, mtf_consensus="UP"),
        SignalInputs(technical_score=5.0, market_structure="UPTREND"),
    ],
)
def test_volume_has_no_effect_outside_strong_preconditions(state):
    labels = {classify_signal(dataclasses.replace(state, relative_volume_class=c)) for c in ("LOW", "NORMAL", "HIGH", "VERY_HIGH")}
    assert len(labels) == 1


def test_high_volume_threshold_boundary_and_single_session_ratio():
    assert classify_relative_volume(1.4999) == "NORMAL"
    assert classify_relative_volume(1.5) == "HIGH"
    assert classify_relative_volume(2.5) == "VERY_HIGH"
    volume = pd.Series([100.0] * 19 + [300.0])
    # 20'lik pencere T'yi İÇERİR: medyan(19x100, 300) = 100 -> oran 3.0
    assert relative_volume_series(volume).iloc[-1] == pytest.approx(3.0)


def _frame(n=150, last_volume_multiplier=1.0):
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(0.004 + rng.normal(0, 0.01, n)))
    idx = pd.bdate_range("2024-01-02", periods=n).tz_localize("Europe/Istanbul")
    volume = rng.uniform(9e5, 1.1e6, n)
    volume[-1] *= last_volume_multiplier
    return pd.DataFrame({"Open": close * 0.998, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": volume}, index=idx)


def test_technical_score_series_is_independent_of_volume():
    base = _frame()
    scaled = base.assign(Volume=base["Volume"] * np.random.default_rng(1).uniform(0.1, 10, len(base)))
    fw = dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    pd.testing.assert_series_equal(technical_score_series(base, _WEIGHTS, fw), technical_score_series(scaled, _WEIGHTS, fw))


def test_live_score_and_confidence_unchanged_when_only_volume_spikes():
    fw = dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    h = compute_scoring_config_hash(_WEIGHTS, fw)
    base_df, spike_df = _frame(), _frame(last_volume_multiplier=5.0)
    bench = pd.Series(np.linspace(100, 120, len(base_df)), index=[ts.date() for ts in base_df.index])
    now = datetime(2024, 9, 1, tzinfo=timezone.utc)
    a = compute_technical_analysis(base_df, "TST", _WEIGHTS, fw, h, "TEST", {}, benchmark_close_series=bench, now=now)
    b = compute_technical_analysis(spike_df, "TST", _WEIGHTS, fw, h, "TEST", {}, benchmark_close_series=bench, now=now)
    assert a.relative_volume_class == "NORMAL" and b.relative_volume_class == "VERY_HIGH"
    assert a.technical_score == b.technical_score
    assert a.confidence == b.confidence
