"""CURRENT_BEHAVIOR_CHARACTERIZATION — TECH-VOL 1A/1B.

Hacmin Technical davranışını BUGÜN (ENGINE_VERSION 1.15.0, TECH-VOL 1B
sonrası) tam olarak nasıl etkilediğini BELGELER. Kalıcı bir ürün sözleşmesi
DEĞİLDİR; gelecekteki bir bilet bu davranışı bilinçli değiştirirse bu testler
o bilette açıkça güncellenmelidir.

Belgelenen davranış:
- Yüksek hacim = RV20 (V_T / 20 seans medyanı, T dahil) >= 1.5 — hâlâ
  hesaplanır ve `relative_volume_class` olarak kaydedilir (gözlemsel veri).
- 1.14.0'da STRONG_BULLISH_INITIATION yüksek hacim GEREKTİRİYORDU; 1.15.0'da
  (TECH-VOL 1B) bu kapı KALDIRILDI: hacim hiçbir bullish/bearish sınıfı
  belirlemez. Kural tersine ÇEVRİLMEDİ.
- Hacmin kalan TEK sınıflandırma etkisi: skor -15..15 bandında ve piyasa
  yapısı + göreli güç de UNKNOWN iken, UNKNOWN hacim NO_SIGNAL (veri yok)
  ile NEUTRAL arasında seçim yapar. Bu bir sinyal-gücü kapısı değildir;
  geçerli bir sinyali VETO EDEMEZ (bullish/bearish dallar önce değerlendirilir).
- technical_score ve confidence hacimden BAĞIMSIZDIR.
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
_RV_CLASSES = ("LOW", "NORMAL", "HIGH", "VERY_HIGH", "UNKNOWN")
_WEIGHTS = {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667,
            "ema_slope": 0.2, "roc": 0.1665}


@pytest.mark.parametrize("rv_class", _RV_CLASSES)
def test_strong_is_identical_for_every_volume_class_when_non_volume_prerequisites_hold(rv_class):
    assert classify_signal(dataclasses.replace(_STRONG_STATE, relative_volume_class=rv_class)) == "STRONG_BULLISH_INITIATION"


_FAILING_STATES = {
    "score_below_40": (dataclasses.replace(_STRONG_STATE, technical_score=39.99), "BULLISH_CONFIRMED"),
    "not_uptrend": (dataclasses.replace(_STRONG_STATE, market_structure="RANGE"), "BULLISH_CANDIDATE"),
    "no_breakout_event": (dataclasses.replace(_STRONG_STATE, breakout_event=None), "BULLISH_CONFIRMED"),
    "unconfirmed_breakout": (dataclasses.replace(_STRONG_STATE, breakout_event=dataclasses.replace(_BULL, confirmed=False)), "BULLISH_CANDIDATE"),
    "broken_breakout": (dataclasses.replace(_STRONG_STATE, breakout_event=dataclasses.replace(_BULL, retest_held=False)), "BULLISH_CONFIRMED"),
    "bearish_breakout": (dataclasses.replace(_STRONG_STATE, breakout_event=dataclasses.replace(_BULL, direction="BEARISH")), "BULLISH_CANDIDATE"),
    "mtf_not_up": (dataclasses.replace(_STRONG_STATE, mtf_consensus="DOWN"), "BULLISH_CONFIRMED"),
    "mtf_not_aligned": (dataclasses.replace(_STRONG_STATE, mtf_aligned=False), "BULLISH_CONFIRMED"),
}


@pytest.mark.parametrize("name", sorted(_FAILING_STATES))
@pytest.mark.parametrize("rv_class", _RV_CLASSES)
def test_failing_non_volume_prerequisite_falls_to_same_lower_class_for_every_volume(name, rv_class):
    state, expected = _FAILING_STATES[name]
    assert classify_signal(dataclasses.replace(state, relative_volume_class=rv_class)) == expected


@pytest.mark.parametrize(
    "state",
    [
        SignalInputs(technical_score=-50.0, market_structure="DOWNTREND"),
        SignalInputs(technical_score=-50.0, market_structure="UNKNOWN"),
        SignalInputs(technical_score=20.0, market_structure="UNKNOWN"),
        SignalInputs(technical_score=5.0, market_structure="UPTREND"),
        SignalInputs(technical_score=-5.0, market_structure="DOWNTREND"),
    ],
)
def test_unknown_volume_cannot_veto_or_change_any_signal_class(state):
    labels = {classify_signal(dataclasses.replace(state, relative_volume_class=c)) for c in _RV_CLASSES}
    assert len(labels) == 1


def test_only_remaining_volume_effect_is_explicit_no_signal_data_availability_label():
    # skor -15..15 bandı + yapı ve göreli güç UNKNOWN: "hiç bağlam yok" etiketi
    empty = SignalInputs(technical_score=5.0, market_structure="UNKNOWN", relative_strength_class="UNKNOWN")
    assert classify_signal(dataclasses.replace(empty, relative_volume_class="UNKNOWN")) == "NO_SIGNAL"
    assert classify_signal(dataclasses.replace(empty, relative_volume_class="NORMAL")) == "NEUTRAL"
    # bullish/bearish bantta UNKNOWN hacim hiçbir zaman NO_SIGNAL üretmez
    for score, expected in ((20.0, "BULLISH_CANDIDATE"), (-20.0, "BEARISH_CANDIDATE")):
        s = dataclasses.replace(empty, technical_score=score, relative_volume_class="UNKNOWN")
        assert classify_signal(s) == expected


def test_high_volume_threshold_boundary_and_single_session_ratio_still_computed():
    assert classify_relative_volume(1.4999) == "NORMAL"
    assert classify_relative_volume(1.5) == "HIGH"
    assert classify_relative_volume(2.5) == "VERY_HIGH"
    volume = pd.Series([100.0] * 19 + [300.0])
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


def test_live_score_confidence_and_signal_class_unchanged_when_only_volume_spikes():
    fw = dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    h = compute_scoring_config_hash(_WEIGHTS, fw)
    base_df, spike_df = _frame(), _frame(last_volume_multiplier=5.0)
    bench = pd.Series(np.linspace(100, 120, len(base_df)), index=[ts.date() for ts in base_df.index])
    now = datetime(2024, 9, 1, tzinfo=timezone.utc)
    a = compute_technical_analysis(base_df, "TST", _WEIGHTS, fw, h, "TEST", {}, benchmark_close_series=bench, now=now)
    b = compute_technical_analysis(spike_df, "TST", _WEIGHTS, fw, h, "TEST", {}, benchmark_close_series=bench, now=now)
    assert a.relative_volume_class == "NORMAL" and b.relative_volume_class == "VERY_HIGH"  # metadata hâlâ kaydediliyor
    assert a.technical_score == b.technical_score
    assert a.confidence == b.confidence
    assert a.signal_class == b.signal_class  # 1.15.0: hacim sinyal sınıfını belirlemez
