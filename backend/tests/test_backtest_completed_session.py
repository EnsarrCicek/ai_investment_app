from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.engines.backtest.engine import BacktestEngine
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.backtest.walk_forward import WalkForwardOptimizer

TZ = ZoneInfo("Europe/Istanbul")


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


def _bday_df(periods: int, end: str, seed: int = 5) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=periods, freq="B")
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    return pd.DataFrame(
        {
            "Open": closes - 0.2,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, len(dates)),
        },
        index=dates,
    )


def _append_partial_row(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    row = pd.DataFrame(
        {"Open": [999.0], "High": [1000.0], "Low": [1.0], "Close": [1.0], "Volume": [999_000_000]},
        index=pd.to_datetime([date_str]),
    )
    return pd.concat([df, row])


# now: piyasa acik (kapanistan/finalization payindan ONCE) -- 26.08 satiri PARTIAL.
_NOW_MARKET_OPEN = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)


def test_backtest_engine_run_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=120, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


def test_backtest_engine_compare_strategies_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=120, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


def test_walk_forward_optimizer_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=200, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    optimizer = WalkForwardOptimizer(provider=provider, config_repo=_FakeConfigRepo())

    result = optimizer.run("TEST", period="1y", train_days=60, test_days=20, now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    last_window = result["windows"][-1]
    assert last_window["test_to"] == "2026-08-25"  # partial (26.08) hicbir pencereye girmedi


def test_backtest_engine_run_partial_row_content_never_changes_result(fake_provider):
    # HATA 3B ana regresyon kilidi (ucdan uca): iki AYRI partial satir --
    # sonuc BIREBIR ayni olmali.
    completed = _bday_df(periods=120, end="2026-08-25")

    row_calm = pd.DataFrame(
        {"Open": [100.0], "High": [100.5], "Low": [99.5], "Close": [100.0], "Volume": [1000]},
        index=pd.to_datetime(["2026-08-26"]),
    )
    row_wild = pd.DataFrame(
        {"Open": [1.0], "High": [99999.0], "Low": [0.5], "Close": [99999.0], "Volume": [999_000_000]},
        index=pd.to_datetime(["2026-08-26"]),
    )

    result_calm = BacktestEngine(
        provider=fake_provider(history_df=pd.concat([completed, row_calm])), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=_NOW_MARKET_OPEN)
    result_wild = BacktestEngine(
        provider=fake_provider(history_df=pd.concat([completed, row_wild])), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result_calm["total_return_pct"] == result_wild["total_return_pct"]
    assert result_calm["trade_count"] == result_wild["trade_count"]
    assert result_calm["max_drawdown_pct"] == result_wild["max_drawdown_pct"]
    assert result_calm["backtest_data_as_of"] == result_wild["backtest_data_as_of"] == "2026-08-25"
