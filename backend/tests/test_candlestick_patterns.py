import pandas as pd

from app.engines.technical.candlestick_patterns import (
    detect_patterns,
    is_bearish_engulfing,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    is_shooting_star,
)


def test_is_doji_true_for_tiny_body():
    assert is_doji(open_=100.0, high=102.0, low=98.0, close=100.05) is True


def test_is_doji_false_for_large_body():
    assert is_doji(open_=100.0, high=112.0, low=98.0, close=110.0) is False


def test_is_hammer_true_for_long_lower_wick_small_body():
    assert is_hammer(open_=105.0, high=106.5, low=100.0, close=106.0) is True


def test_is_hammer_false_for_shooting_star_shape():
    assert is_hammer(open_=100.0, high=105.0, low=98.5, close=99.0) is False


def test_is_shooting_star_true_for_long_upper_wick_small_body():
    assert is_shooting_star(open_=100.0, high=105.0, low=98.5, close=99.0) is True


def test_is_shooting_star_false_for_hammer_shape():
    assert is_shooting_star(open_=105.0, high=106.5, low=100.0, close=106.0) is False


def test_is_bullish_engulfing_true():
    assert is_bullish_engulfing(prev_open=110.0, prev_close=100.0, open_=99.0, close=112.0) is True


def test_is_bullish_engulfing_false_when_prev_not_bearish():
    assert is_bullish_engulfing(prev_open=100.0, prev_close=110.0, open_=99.0, close=112.0) is False


def test_is_bearish_engulfing_true():
    assert is_bearish_engulfing(prev_open=100.0, prev_close=110.0, open_=112.0, close=98.0) is True


def test_is_bearish_engulfing_false_when_curr_not_bearish():
    assert is_bearish_engulfing(prev_open=100.0, prev_close=110.0, open_=112.0, close=115.0) is False


def test_detect_patterns_finds_bullish_engulfing_on_last_bar():
    df = pd.DataFrame(
        [
            {"Open": 90.0, "High": 92.0, "Low": 89.0, "Close": 91.0},  # dolgu bar
            {"Open": 110.0, "High": 111.0, "Low": 99.0, "Close": 100.0},  # düşüş (kırmızı)
            {"Open": 99.0, "High": 113.0, "Low": 98.0, "Close": 112.0},  # bullish engulfing
        ]
    )
    assert detect_patterns(df, index=-1) == ["BULLISH_ENGULFING"]
    assert detect_patterns(df, index=2) == ["BULLISH_ENGULFING"]


def test_detect_patterns_returns_empty_list_when_no_pattern_matches():
    df = pd.DataFrame(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5},
            {"Open": 100.5, "High": 102.0, "Low": 100.0, "Close": 101.5},
        ]
    )
    assert detect_patterns(df, index=-1) == []


def test_detect_patterns_skips_prev_bar_check_at_index_zero():
    df = pd.DataFrame([{"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.05}])
    assert detect_patterns(df, index=0) == ["DOJI"]


def test_detect_patterns_is_causal_future_bars_do_not_change_past_detection():
    base_rows = [
        {"Open": 90.0, "High": 92.0, "Low": 89.0, "Close": 91.0},
        {"Open": 110.0, "High": 111.0, "Low": 99.0, "Close": 100.0},
        {"Open": 99.0, "High": 113.0, "Low": 98.0, "Close": 112.0},
    ]
    truncated = pd.DataFrame(base_rows)
    extended = pd.DataFrame(base_rows + [{"Open": 112.0, "High": 120.0, "Low": 111.0, "Close": 118.0}])

    assert detect_patterns(truncated, index=2) == detect_patterns(extended, index=2)
