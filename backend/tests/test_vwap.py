import pandas as pd
import pytest

from app.engines.technical.vwap import anchored_vwap_series, price_vs_vwap_pct, vwap_series


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [99.0, 101.0, 103.0],
            "High": [101.0, 103.0, 105.0],
            "Low": [99.0, 101.0, 103.0],
            "Close": [100.0, 102.0, 104.0],
            "Volume": [1000.0, 2000.0, 1000.0],
        }
    )


def test_vwap_series_computes_cumulative_volume_weighted_average():
    result = vwap_series(_df())
    assert result.iloc[0] == pytest.approx(100.0)
    assert result.iloc[1] == pytest.approx(101.333333, rel=1e-5)
    assert result.iloc[2] == pytest.approx(102.0)


def test_vwap_series_is_causal_future_bars_do_not_change_past_values():
    full = _df()
    truncated = full.iloc[:2]

    full_vwap = vwap_series(full).iloc[:2].reset_index(drop=True)
    truncated_vwap = vwap_series(truncated).reset_index(drop=True)

    pd.testing.assert_series_equal(full_vwap, truncated_vwap, check_names=False)


def test_anchored_vwap_series_is_nan_before_anchor():
    result = anchored_vwap_series(_df(), anchor_index=1)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx(102.0)
    assert result.iloc[2] == pytest.approx(102.666667, rel=1e-5)


def test_anchored_vwap_series_rejects_out_of_range_anchor():
    with pytest.raises(ValueError):
        anchored_vwap_series(_df(), anchor_index=5)
    with pytest.raises(ValueError):
        anchored_vwap_series(_df(), anchor_index=-1)


def test_price_vs_vwap_pct_positive_when_above_vwap():
    assert price_vs_vwap_pct(close=105.0, vwap=100.0) == pytest.approx(5.0)


def test_price_vs_vwap_pct_negative_when_below_vwap():
    assert price_vs_vwap_pct(close=95.0, vwap=100.0) == pytest.approx(-5.0)


def test_price_vs_vwap_pct_none_for_zero_vwap():
    assert price_vs_vwap_pct(close=100.0, vwap=0.0) is None
