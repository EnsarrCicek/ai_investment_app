import pandas as pd
import pytest

from app.engines.backtest.engine import simulate, technical_score_series
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.engine import DEFAULT_WEIGHTS


def _uptrend_df(n=80):
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 + pd.Series(range(n), dtype=float) * 0.5
    close.index = idx
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": [1000.0] * n},
        index=idx,
    )


def test_technical_score_series_matches_input_length_and_bounds():
    df = _uptrend_df()
    series = technical_score_series(df, DEFAULT_WEIGHTS)
    assert len(series) == len(df)
    assert series.dropna().between(-100, 100).all()


def test_simulate_executes_buy_then_sell_on_signals():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame({"Close": [100.0, 110.0, 120.0, 90.0, 80.0]}, index=idx)
    # gün 0: BUY sinyali, gün 3: SELL sinyali, aradakiler nötr
    scores = pd.Series([50.0, 10.0, 10.0, -50.0, -10.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["entry_price"] == 100.0
    assert trade["exit_price"] == 90.0
    assert trade["return_pct"] == pytest.approx(-10.0)
    assert result["final_equity"] == 900.0


def test_simulate_stays_flat_without_buy_signal():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=idx)
    scores = pd.Series([0.0, 0.0, 0.0], index=idx)

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trade_count"] == 0
    assert result["final_equity"] == 1000.0


def test_simulate_force_closes_open_position_at_end():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Close": [100.0, 110.0, 120.0]}, index=idx)
    scores = pd.Series([50.0, 10.0, 10.0], index=idx)  # yalnızca BUY sinyali, hiç SELL yok

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["trade_count"] == 1
    assert result["trades"][0]["note"].startswith("Backtest sonunda")
    assert result["final_equity"] == pytest.approx(1200.0)
