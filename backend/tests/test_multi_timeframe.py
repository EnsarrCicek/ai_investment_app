import pandas as pd

from app.engines.technical.multi_timeframe import check_alignment, resample_to_weekly_close, timeframe_direction


def test_timeframe_direction_up_for_rising_series():
    close = pd.Series([100.0 + i for i in range(40)])
    assert timeframe_direction(close, window=10, slope_lookback=5) == "UP"


def test_timeframe_direction_down_for_falling_series():
    close = pd.Series([200.0 - i for i in range(40)])
    assert timeframe_direction(close, window=10, slope_lookback=5) == "DOWN"


def test_timeframe_direction_flat_for_constant_series():
    close = pd.Series([100.0] * 40)
    assert timeframe_direction(close, window=10, slope_lookback=5) == "FLAT"


def test_timeframe_direction_unknown_for_insufficient_history():
    close = pd.Series([100.0, 101.0])
    assert timeframe_direction(close, window=20, slope_lookback=5) == "UNKNOWN"


def test_check_alignment_true_when_all_timeframes_agree():
    result = check_alignment({"1d": "UP", "1wk": "UP"})
    assert result["aligned"] is True
    assert result["consensus"] == "UP"


def test_check_alignment_conflicting_when_directions_oppose():
    result = check_alignment({"1d": "UP", "1wk": "DOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "CONFLICTING"


def test_check_alignment_mixed_for_partial_agreement():
    result = check_alignment({"1d": "UP", "1wk": "FLAT"})
    assert result["aligned"] is False
    assert result["consensus"] == "MIXED"


def test_check_alignment_unknown_when_no_timeframe_resolved():
    result = check_alignment({"1d": "UNKNOWN", "1wk": "UNKNOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


def test_resample_to_weekly_close_reduces_to_weekly_last_values():
    idx = pd.date_range("2024-01-01", periods=14, freq="D")  # Pzt 2024-01-01 .. Paz 2024-01-14 (2 tam hafta)
    daily_close = pd.Series(range(1, 15), index=idx, dtype=float)  # 1..14

    weekly = resample_to_weekly_close(daily_close)

    assert len(weekly) == 2
    assert weekly.iloc[0] == 7.0  # ilk haftanın son günü (2024-01-07, Pazar) -> 7
    assert weekly.iloc[-1] == 14.0  # ikinci haftanın son günü (2024-01-14, Pazar) -> 14


def test_weekly_resample_direction_matches_underlying_trend_without_extra_fetch():
    # AŞAMA 48/18: haftalık yön, ek bir yfinance isteği olmadan günlük
    # seriden türetilebiliyor mu — asıl doğrulanan budur.
    idx = pd.date_range("2023-01-02", periods=140, freq="D")
    daily_close = pd.Series([100.0 + 0.5 * i for i in range(140)], index=idx)

    weekly = resample_to_weekly_close(daily_close)

    assert timeframe_direction(weekly, window=10, slope_lookback=4) == "UP"
