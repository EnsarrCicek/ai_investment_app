import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.weight_walk_forward import split_walk_forward_indices, walk_forward_optimize_weights
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.engine import DEFAULT_WEIGHTS


def _trending_df(n: int = 120, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    closes = 100 + np.cumsum(rng.normal(0.3, 1.0, n))  # hafif yukarı eğilimli, gürültülü seri
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, n),
        },
        index=idx,
    )


def test_split_walk_forward_indices_produces_non_overlapping_sequential_blocks():
    splits = split_walk_forward_indices(n=100, n_splits=4, train_ratio=0.7)
    assert len(splits) == 4
    for i in range(len(splits) - 1):
        this_test_stop = splits[i][1].stop
        next_train_start = splits[i + 1][0].start
        assert this_test_stop <= next_train_start


def test_split_walk_forward_indices_rejects_too_little_data():
    with pytest.raises(ValueError):
        split_walk_forward_indices(n=20, n_splits=4, train_ratio=0.7)


def test_walk_forward_optimize_weights_returns_one_result_per_fold():
    df = _trending_df(n=120)
    weight_grid = [DEFAULT_WEIGHTS, {**DEFAULT_WEIGHTS, "rsi": 0.05, "roc": 0.30}]

    result = walk_forward_optimize_weights(df, weight_grid, DEFAULT_THRESHOLDS, n_splits=3, train_ratio=0.7)

    assert result["n_folds"] == len(result["folds"])
    assert result["n_folds"] > 0
    for fold in result["folds"]:
        assert fold["chosen_weights"] in weight_grid
        assert isinstance(fold["test_total_return_pct"], float)


def test_walk_forward_optimize_weights_raises_without_valid_splits():
    df = _trending_df(n=20)
    with pytest.raises(ValueError):
        walk_forward_optimize_weights(df, [DEFAULT_WEIGHTS], DEFAULT_THRESHOLDS, n_splits=4, train_ratio=0.7)
