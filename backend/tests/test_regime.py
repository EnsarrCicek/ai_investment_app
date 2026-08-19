import pandas as pd
import pytest

from app.engines.technical.regime import (
    atr_percentile,
    classify_trend_regime,
    classify_volatility_regime,
    efficiency_ratio,
)


def test_atr_percentile_ranks_highest_value_near_100():
    atr = pd.Series([float(i) for i in range(1, 121)])  # sürekli artan ATR
    result = atr_percentile(atr, window=100)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_atr_percentile_ranks_lowest_recent_value_near_0():
    atr = pd.Series([float(i) for i in range(120, 0, -1)])  # sürekli azalan ATR
    result = atr_percentile(atr, window=100)
    assert result.iloc[-1] < 5.0


@pytest.mark.parametrize(
    "percentile, expected",
    [(95.0, "EXTREME"), (75.0, "HIGH"), (50.0, "NORMAL"), (20.0, "LOW")],
)
def test_classify_volatility_regime_thresholds(percentile, expected):
    assert classify_volatility_regime(percentile) == expected


def test_classify_volatility_regime_unknown_for_nan():
    assert classify_volatility_regime(float("nan")) == "UNKNOWN"


def test_efficiency_ratio_is_one_for_straight_line_trend():
    close = pd.Series([float(i) for i in range(30)])
    result = efficiency_ratio(close, window=5)
    assert result.iloc[-1] == pytest.approx(1.0)


def test_efficiency_ratio_is_near_zero_for_choppy_round_trip():
    close = pd.Series([10.0, 12.0, 10.0, 12.0, 10.0])
    result = efficiency_ratio(close, window=4)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_classify_trend_regime_boundaries():
    assert classify_trend_regime(0.8) == "TRENDING"
    assert classify_trend_regime(0.1) == "CHOPPY"
    assert classify_trend_regime(float("nan")) == "UNKNOWN"
