import pandas as pd
import pytest

from app.services.market_data.changes import compute_period_changes


def _history(prices: dict[str, float]) -> pd.DataFrame:
    """{'YYYY-MM-DD': close} sözlüğünden minimal bir OHLCV DataFrame üretir."""
    index = pd.to_datetime(list(prices.keys()))
    closes = list(prices.values())
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [0] * len(closes)},
        index=index,
    )


def test_empty_history_returns_all_none():
    result = compute_period_changes(pd.DataFrame())
    assert result == {"1d": None, "1w": None, "1m": None, "3m": None, "6m": None, "1y": None}


def test_computes_known_percentage_changes():
    history = _history(
        {
            "2025-08-18": 100.0,  # ~1 yıl önce
            "2026-05-20": 90.0,  # ~3 ay önce
            "2026-07-19": 80.0,  # ~1 ay önce
            "2026-08-11": 95.0,  # 1 hafta önce
            "2026-08-17": 98.0,  # 1 gün önce
            "2026-08-18": 100.0,  # son fiyat
        }
    )

    result = compute_period_changes(history)

    assert result["1d"] == pytest.approx(round((100 - 98) / 98 * 100, 2))
    assert result["1w"] == pytest.approx(round((100 - 95) / 95 * 100, 2))
    assert result["1m"] == pytest.approx(round((100 - 80) / 80 * 100, 2))
    assert result["3m"] == pytest.approx(round((100 - 90) / 90 * 100, 2))


def test_returns_none_when_not_enough_history_for_period():
    # Yalnızca son 10 günlük veri var — 1 yıl/6 ay geriye gidilemez.
    history = _history({f"2026-08-{d:02d}": 100.0 for d in range(1, 11)})
    result = compute_period_changes(history)

    assert result["1y"] is None
    assert result["6m"] is None
    assert result["1d"] is not None
