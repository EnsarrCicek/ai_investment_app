from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import DataQualityError, check_data_quality

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _fresh_df(rows: int = 80, end: pd.Timestamp | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    idx = pd.date_range(end=end or pd.Timestamp(_NOW), periods=rows, freq="D")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, rows),
        },
        index=idx,
    )


def test_passes_with_fresh_sufficient_data():
    df = _fresh_df(rows=80)
    check_data_quality(df, "TEST", min_history_days=60, now=_NOW)  # exception atmamalı


def test_rejects_insufficient_history():
    df = _fresh_df(rows=30)
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_rejects_missing_columns():
    df = _fresh_df(rows=80).drop(columns=["Volume"])
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "MISSING_COLUMNS"


def test_rejects_missing_ohlcv_in_last_row():
    df = _fresh_df(rows=80)
    df.iloc[-1, df.columns.get_loc("Close")] = np.nan
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "MISSING_OHLCV"


def test_rejects_stale_data():
    stale_end = pd.Timestamp(_NOW) - timedelta(days=10)
    df = _fresh_df(rows=80, end=stale_end)
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "STALE_DATA"


def test_allows_data_within_staleness_tolerance():
    recent_end = pd.Timestamp(_NOW) - timedelta(days=3)  # hafta sonu toleransı içinde
    df = _fresh_df(rows=80, end=recent_end)
    check_data_quality(df, "TEST", min_history_days=60, max_staleness_days=5, now=_NOW)
