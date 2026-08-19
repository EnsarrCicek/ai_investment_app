import pytest

from app.engines.backtest.metrics import (
    compute_extended_metrics,
    expectancy_pct,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
)


def _rising_equity_curve(n: int = 60, daily_return: float = 0.002) -> list[dict]:
    equity = 100_000.0
    curve = []
    for i in range(n):
        curve.append({"date": f"day-{i}", "equity": round(equity, 2)})
        equity *= 1 + daily_return
    return curve


def test_sharpe_ratio_positive_for_steadily_rising_equity():
    result = sharpe_ratio(_rising_equity_curve())
    assert result is not None
    assert result > 0


def test_sharpe_ratio_none_with_insufficient_points():
    assert sharpe_ratio([{"date": "d", "equity": 100.0}]) is None


def test_sharpe_ratio_none_for_constant_equity():
    curve = [{"date": f"d{i}", "equity": 1000.0} for i in range(10)]
    assert sharpe_ratio(curve) is None


def test_sortino_ratio_none_without_any_downside():
    assert sortino_ratio(_rising_equity_curve()) is None  # hiç düşüş yok -> downside std hesaplanamaz


def test_sortino_ratio_computes_for_mixed_curve():
    equities = [1000, 1010, 990, 1020, 980, 1050, 1005, 1080, 1000, 1100]
    curve = [{"date": f"d{i}", "equity": float(e)} for i, e in enumerate(equities)]
    assert sortino_ratio(curve) is not None


def test_profit_factor_ratio_of_gains_to_losses():
    trades = [{"return_pct": 10.0}, {"return_pct": -5.0}, {"return_pct": 5.0}, {"return_pct": -2.0}]
    assert profit_factor(trades) == pytest.approx(15.0 / 7.0, abs=1e-3)  # profit_factor 4 ondalığa yuvarlıyor


def test_profit_factor_none_without_losses():
    assert profit_factor([{"return_pct": 10.0}, {"return_pct": 5.0}]) is None


def test_profit_factor_none_for_empty_trades():
    assert profit_factor([]) is None


def test_expectancy_pct_averages_trade_returns():
    trades = [{"return_pct": 10.0}, {"return_pct": -4.0}]
    assert expectancy_pct(trades) == pytest.approx(3.0)


def test_expectancy_pct_none_for_empty_trades():
    assert expectancy_pct([]) is None


def test_compute_extended_metrics_combines_all_fields():
    backtest_result = {
        "equity_curve": _rising_equity_curve(),
        "trades": [{"return_pct": 10.0}, {"return_pct": -5.0}],
    }
    metrics = compute_extended_metrics(backtest_result)
    assert set(metrics.keys()) == {"sharpe_ratio", "sortino_ratio", "profit_factor", "expectancy_pct"}
