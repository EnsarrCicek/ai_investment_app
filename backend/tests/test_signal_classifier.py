from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.signal_classifier import SignalInputs, classify_signal
from app.engines.technical.support_resistance import SRZone

_ZONE = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=3, last_touch_index=10)


def _confirmed_breakout(retest_held=None) -> BreakoutEvent:
    return BreakoutEvent(index=10, direction="BULLISH", zone=_ZONE, breakout_atr=2.0, confirmed=True, retest_held=retest_held)


def test_strong_bullish_initiation_requires_all_conditions():
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="HIGH",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "STRONG_BULLISH_INITIATION"


def test_falls_back_to_bullish_confirmed_without_high_volume():
    inputs = SignalInputs(
        technical_score=45.0,
        market_structure="UPTREND",
        breakout_event=_confirmed_breakout(retest_held=True),
        relative_volume_class="NORMAL",  # yüksek hacim yok -> en güçlü sınıfa erişemez
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_signal(inputs) == "BULLISH_CONFIRMED"


def test_bullish_confirmed_without_breakout_event():
    inputs = SignalInputs(technical_score=20.0, market_structure="UPTREND", breakout_event=None)
    assert classify_signal(inputs) == "BULLISH_CONFIRMED"


def test_bullish_candidate_when_structure_not_uptrend():
    inputs = SignalInputs(technical_score=20.0, market_structure="RANGE")
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bullish_candidate_when_breakout_not_confirmed_yet():
    pending = BreakoutEvent(index=10, direction="BULLISH", zone=_ZONE, breakout_atr=1.0, confirmed=None)
    inputs = SignalInputs(technical_score=20.0, market_structure="UPTREND", breakout_event=pending)
    assert classify_signal(inputs) == "BULLISH_CANDIDATE"


def test_bearish_candidate_for_strongly_negative_score():
    inputs = SignalInputs(technical_score=-30.0, market_structure="DOWNTREND")
    assert classify_signal(inputs) == "BEARISH_CANDIDATE"


def test_bearish_candidate_regardless_of_structure():
    inputs = SignalInputs(technical_score=-30.0, market_structure="RANGE")
    assert classify_signal(inputs) == "BEARISH_CANDIDATE"


def test_no_signal_when_all_context_is_unknown():
    inputs = SignalInputs(technical_score=0.0)
    assert classify_signal(inputs) == "NO_SIGNAL"


def test_watchlist_for_mild_positive_score_in_uptrend():
    inputs = SignalInputs(technical_score=8.0, market_structure="UPTREND")
    assert classify_signal(inputs) == "WATCHLIST"


def test_watchlist_for_mild_negative_score_in_downtrend():
    inputs = SignalInputs(technical_score=-8.0, market_structure="DOWNTREND")
    assert classify_signal(inputs) == "WATCHLIST"


def test_neutral_as_default_fallback():
    inputs = SignalInputs(technical_score=5.0, market_structure="RANGE")
    assert classify_signal(inputs) == "NEUTRAL"
