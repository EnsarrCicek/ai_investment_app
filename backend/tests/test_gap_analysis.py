import pandas as pd
import pytest

from app.engines.technical.gap_analysis import classify_gap, is_gap_filled, latest_gap


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_latest_gap_none_with_insufficient_history():
    df = _df([{"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0}])
    assert latest_gap(df, atr=2.0) is None


def test_latest_gap_none_for_non_positive_atr():
    df = _df(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 105.0, "High": 106.0, "Low": 104.0, "Close": 105.0},
        ]
    )
    assert latest_gap(df, atr=0.0) is None


def test_latest_gap_computes_upward_gap():
    df = _df(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 105.0, "High": 106.0, "Low": 104.5, "Close": 105.5},
        ]
    )
    gap = latest_gap(df, atr=2.0)
    assert gap["direction"] == "UP"
    assert gap["gap_pct"] == pytest.approx(5.0)
    assert gap["gap_atr"] == pytest.approx(2.5)


def test_latest_gap_computes_downward_gap():
    df = _df(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 95.0, "High": 96.0, "Low": 94.0, "Close": 95.5},
        ]
    )
    gap = latest_gap(df, atr=2.0)
    assert gap["direction"] == "DOWN"
    assert gap["gap_pct"] == pytest.approx(-5.0)


def test_is_gap_filled_true_when_price_returns_to_prev_close():
    df = _df(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 105.0, "High": 106.0, "Low": 99.5, "Close": 104.0},  # gün içi 99.5'e kadar indi
        ]
    )
    assert is_gap_filled(df) is True


def test_is_gap_filled_false_when_gap_stays_open():
    df = _df(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0},
            {"Open": 105.0, "High": 106.0, "Low": 104.5, "Close": 105.5},  # 101 seviyesine hiç dönmedi
        ]
    )
    assert is_gap_filled(df) is False


@pytest.mark.parametrize(
    "gap, filled, expected",
    [
        (None, None, "UNKNOWN"),
        ({"gap_pct": 0.5, "gap_atr": 0.3, "direction": "UP"}, False, "NO_SIGNIFICANT_GAP"),
        ({"gap_pct": 5.0, "gap_atr": 2.5, "direction": "UP"}, True, "GAP_FILLED"),
        ({"gap_pct": 5.0, "gap_atr": 2.5, "direction": "UP"}, False, "GAP_UP_OPEN"),
        ({"gap_pct": -5.0, "gap_atr": -2.5, "direction": "DOWN"}, False, "GAP_DOWN_OPEN"),
    ],
)
def test_classify_gap(gap, filled, expected):
    assert classify_gap(gap, filled) == expected
