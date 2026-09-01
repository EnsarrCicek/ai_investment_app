from app.engines.technical.horizon_classifier import (
    BELIRSIZ,
    KISA_VADELI,
    ORTA_VADELI,
    UZUN_VADELI,
    HorizonInputs,
    classify_horizon,
)
from app.engines.technical.multi_timeframe import check_alignment


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


# HATA 7C-FIX (01.09.2026): eksik (UNKNOWN) bir MTF zaman dilimi, gerçek
# check_alignment() üzerinden artık aligned=False/consensus="UNKNOWN"
# üretiyor -- full_confirmation'ın "günlük+haftalık uyumlu" şartını TEK
# BAŞINA sağlayamamalı (diğer üç şart -- trend_regime/relative_strength --
# tam olsa bile).
def test_incomplete_mtf_evidence_cannot_satisfy_full_confirmation():
    alignment = check_alignment({"1d": "UP", "1wk": "UNKNOWN"})
    inputs = HorizonInputs(
        signal_class="BULLISH_CONFIRMED",
        market_structure="UPTREND",
        trend_regime="TRENDING",
        relative_strength_class="OUTPERFORMING",
        mtf_aligned=alignment["aligned"],
        mtf_consensus=alignment["consensus"],
    )
    # full_confirmation MTF şartı sağlanamıyor ama trend_regime=="TRENDING"
    # partial_confirmation'ı (DEĞİŞMEYEN diğer dal) hâlâ sağlıyor.
    assert classify_horizon(inputs) == ORTA_VADELI


def test_incomplete_mtf_consensus_alone_cannot_satisfy_partial_confirmation():
    alignment = check_alignment({"1d": "UP", "1wk": "UNKNOWN"})
    inputs = HorizonInputs(
        signal_class="BULLISH_CONFIRMED",
        market_structure="UPTREND",
        trend_regime="CHOPPY",  # partial_confirmation'ın trend_regime dalı da kapalı
        relative_strength_class="UNKNOWN",
        mtf_aligned=alignment["aligned"],
        mtf_consensus=alignment["consensus"],
    )
    # Eski davranışta consensus="UP" olurdu ve mtf_consensus==expected_consensus
    # partial_confirmation'ı sağlardı -- artık consensus="UNKNOWN", hiçbir
    # partial_confirmation dalı sağlanamıyor.
    assert classify_horizon(inputs) == KISA_VADELI


def test_neutral_signal_is_undetermined():
    inputs = HorizonInputs(signal_class="NEUTRAL")
    assert classify_horizon(inputs) == BELIRSIZ


def test_no_signal_is_undetermined():
    inputs = HorizonInputs(signal_class="NO_SIGNAL")
    assert classify_horizon(inputs) == BELIRSIZ
