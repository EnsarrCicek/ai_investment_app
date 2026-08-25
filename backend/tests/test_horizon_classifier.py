from app.engines.technical.horizon_classifier import (
    BELIRSIZ,
    KISA_VADELI,
    ORTA_VADELI,
    UZUN_VADELI,
    HorizonInputs,
    classify_horizon,
)


def test_strong_bullish_initiation_is_always_short_term():
    inputs = HorizonInputs(
        signal_class="STRONG_BULLISH_INITIATION",
        market_structure="UPTREND",
        trend_regime="TRENDING",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_horizon(inputs) == KISA_VADELI


def test_fully_confirmed_bullish_trend_is_long_term():
    inputs = HorizonInputs(
        signal_class="BULLISH_CONFIRMED",
        market_structure="UPTREND",
        trend_regime="TRENDING",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_horizon(inputs) == UZUN_VADELI


def test_fully_confirmed_bearish_trend_is_long_term():
    inputs = HorizonInputs(
        signal_class="BEARISH_CANDIDATE",
        market_structure="DOWNTREND",
        trend_regime="TRENDING",
        relative_strength_class="UNDERPERFORMING",
        mtf_aligned=True,
        mtf_consensus="DOWN",
    )
    assert classify_horizon(inputs) == UZUN_VADELI


def test_partially_confirmed_bullish_trend_is_medium_term_via_mtf():
    inputs = HorizonInputs(
        signal_class="BULLISH_CONFIRMED",
        market_structure="UPTREND",
        trend_regime="CHOPPY",
        relative_strength_class="IN_LINE",
        mtf_aligned=True,
        mtf_consensus="UP",
    )
    assert classify_horizon(inputs) == ORTA_VADELI


def test_partially_confirmed_bullish_trend_is_medium_term_via_trend_regime():
    inputs = HorizonInputs(
        signal_class="BULLISH_CONFIRMED",
        market_structure="UPTREND",
        trend_regime="TRENDING",
        relative_strength_class="UNKNOWN",
        mtf_aligned=False,
        mtf_consensus="CONFLICTING",
    )
    assert classify_horizon(inputs) == ORTA_VADELI


def test_bullish_signal_without_any_structural_confirmation_is_short_term():
    inputs = HorizonInputs(
        signal_class="BULLISH_CANDIDATE",
        market_structure="RANGE",
        trend_regime="CHOPPY",
        relative_strength_class="UNKNOWN",
        mtf_aligned=False,
        mtf_consensus="UNKNOWN",
    )
    assert classify_horizon(inputs) == KISA_VADELI


def test_bearish_signal_without_any_structural_confirmation_is_short_term():
    inputs = HorizonInputs(
        signal_class="BEARISH_CANDIDATE",
        market_structure="RANGE",
        trend_regime="CHOPPY",
        relative_strength_class="UNKNOWN",
        mtf_aligned=False,
        mtf_consensus="UNKNOWN",
    )
    assert classify_horizon(inputs) == KISA_VADELI


def test_neutral_signal_is_undetermined():
    inputs = HorizonInputs(signal_class="NEUTRAL")
    assert classify_horizon(inputs) == BELIRSIZ


def test_no_signal_is_undetermined():
    inputs = HorizonInputs(signal_class="NO_SIGNAL")
    assert classify_horizon(inputs) == BELIRSIZ
