import pandas as pd
import pytest

from app.engines.technical.relative_strength import (
    classify_relative_strength,
    relative_strength_ratio,
    relative_strength_score,
)


def _series(values: list[float], start: str = "2026-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_relative_strength_ratio_aligns_on_common_dates():
    asset = _series([100.0, 102.0, 104.0])
    benchmark = _series([50.0, 51.0, 52.0])
    ratio = relative_strength_ratio(asset, benchmark)
    assert list(ratio.round(4)) == [2.0, 2.0, 2.0]


def test_relative_strength_ratio_handles_non_overlapping_dates():
    asset = _series([100.0, 102.0], start="2026-01-01")
    benchmark = _series([50.0, 51.0], start="2026-01-02")  # yalnızca 1 ortak gün
    ratio = relative_strength_ratio(asset, benchmark)
    assert len(ratio) == 1


def test_relative_strength_score_positive_when_asset_outperforms():
    # asset son günde %20 sıçrıyor, benchmark sabit -> oran yükseliyor -> outperformance
    asset = _series([100.0] * 21)
    asset.iloc[-1] = 120.0
    benchmark = _series([50.0] * 21)
    ratio = relative_strength_ratio(asset, benchmark)

    score = relative_strength_score(ratio, lookback=20)
    assert score == pytest.approx(20.0)


def test_relative_strength_score_negative_when_asset_underperforms():
    asset = _series([100.0] * 21)
    benchmark = _series([50.0] * 21)
    benchmark.iloc[-1] = 60.0  # benchmark %20 artıyor, asset sabit -> asset göreceli zayıflıyor

    ratio = relative_strength_ratio(asset, benchmark)
    score = relative_strength_score(ratio, lookback=20)
    assert score < 0


def test_relative_strength_score_none_with_insufficient_history():
    asset = _series([100.0] * 5)
    benchmark = _series([50.0] * 5)
    ratio = relative_strength_ratio(asset, benchmark)
    assert relative_strength_score(ratio, lookback=20) is None


@pytest.mark.parametrize(
    "score, expected",
    [(5.0, "OUTPERFORMING"), (-5.0, "UNDERPERFORMING"), (0.5, "IN_LINE"), (None, "UNKNOWN")],
)
def test_classify_relative_strength(score, expected):
    assert classify_relative_strength(score) == expected
