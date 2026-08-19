import pandas as pd

from app.engines.technical.breakout import check_retest, confirm_breakout, detect_breakout
from app.engines.technical.support_resistance import SRZone

_RESISTANCE = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=2, last_touch_index=0)
_SUPPORT = SRZone(type="SUPPORT", low=98.0, high=100.0, touch_count=2, last_touch_index=0)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_detect_breakout_returns_none_for_non_positive_atr():
    close = _series([105.0])
    assert detect_breakout(close, _RESISTANCE, index=0, atr=0.0) is None


def test_detect_breakout_returns_none_when_price_stays_inside_zone():
    close = _series([99.0])
    assert detect_breakout(close, _RESISTANCE, index=0, atr=2.0) is None
    assert detect_breakout(close, _SUPPORT, index=0, atr=2.0) is None


def test_detect_breakout_detects_bullish_breakout_above_resistance():
    close = _series([95, 96, 97, 98, 99, 105])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)

    assert event is not None
    assert event.direction == "BULLISH"
    assert event.breakout_atr == 2.5  # (105-100)/2
    assert event.confirmed is None


def test_detect_breakout_detects_bearish_breakdown_below_support():
    close = _series([105, 104, 103, 102, 101, 95])
    event = detect_breakout(close, _SUPPORT, index=5, atr=2.0)

    assert event is not None
    assert event.direction == "BEARISH"
    assert event.breakout_atr == 1.5  # (98-95)/2


def test_confirm_breakout_stays_unknown_without_enough_future_bars():
    close = _series([95, 96, 97, 98, 99, 105, 106, 107])  # index5'ten sonra sadece 2 bar var
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)

    assert event.confirmed is None


def test_confirm_breakout_true_when_price_stays_above_resistance():
    close = _series([95, 96, 97, 98, 99, 105, 106, 107, 108, 109])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)

    assert event.confirmed is True


def test_confirm_breakout_false_when_price_falls_back_into_zone():
    close = _series([95, 96, 97, 98, 99, 105, 106, 99.0, 108, 109])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)

    assert event.confirmed is False


def test_confirm_breakout_bearish_symmetry():
    close = _series([105, 104, 103, 102, 101, 95, 94, 93, 92, 91])
    event = detect_breakout(close, _SUPPORT, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)

    assert event.confirmed is True


def test_check_retest_skipped_when_not_confirmed():
    close = _series([95, 96, 97, 98, 99, 105, 99.5, 99.8, 101])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    # confirmed hâlâ None (confirm_breakout hiç çağrılmadı)
    event = check_retest(close, event, retest_bars=6)

    assert event.retest_held is None


def test_check_retest_held_when_level_holds_after_pullback():
    close = _series([95, 96, 97, 98, 99, 105, 106, 107, 108, 99.5, 99.8, 101])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)
    assert event.confirmed is True

    event = check_retest(close, event, retest_bars=6)
    assert event.retest_held is True


def test_check_retest_broken_when_level_fails_after_pullback():
    close = _series([95, 96, 97, 98, 99, 105, 106, 107, 108, 99.5, 97.0, 96.0])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)
    assert event.confirmed is True

    event = check_retest(close, event, retest_bars=6)
    assert event.retest_held is False


def test_check_retest_none_when_no_pullback_occurs():
    close = _series([95, 96, 97, 98, 99, 105, 106, 107, 108, 109, 110, 111])
    event = detect_breakout(close, _RESISTANCE, index=5, atr=2.0)
    event = confirm_breakout(close, event, confirm_bars=3)
    assert event.confirmed is True

    event = check_retest(close, event, retest_bars=6)
    assert event.retest_held is None
