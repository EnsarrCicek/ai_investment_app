import pandas as pd
import pytest

from app.engines.technical.relative_volume import classify_relative_volume, relative_volume_series


def test_relative_volume_series_is_nan_before_window_fills():
    volume = pd.Series([1000.0] * 25)
    series = relative_volume_series(volume, window=20)

    assert series.iloc[:19].isna().all()
    assert series.iloc[19:].notna().all()


def test_relative_volume_series_ratio_against_median_baseline():
    # Sabit 1000 hacimli 19 gün + 1 aşırı gün (5000) -> medyan 20 barlık
    # pencerede hâlâ 1000 (medyan, aykırı değere SMA kadar duyarlı değil).
    volume = pd.Series([1000.0] * 19 + [5000.0])
    series = relative_volume_series(volume, window=20)

    assert series.iloc[19] == pytest.approx(5.0)  # 5000 / medyan(1000)


def test_relative_volume_series_handles_zero_baseline_without_error():
    volume = pd.Series([0.0] * 25)
    series = relative_volume_series(volume, window=20)
    assert series.iloc[19:].isna().all()


@pytest.mark.parametrize(
    "ratio, expected",
    [
        (0.3, "LOW"),
        (0.5, "NORMAL"),
        (1.0, "NORMAL"),
        (1.5, "HIGH"),
        (2.0, "HIGH"),
        (2.5, "VERY_HIGH"),
        (3.0, "VERY_HIGH"),
    ],
)
def test_classify_relative_volume_thresholds(ratio, expected):
    assert classify_relative_volume(ratio) == expected


def test_classify_relative_volume_returns_unknown_for_nan():
    assert classify_relative_volume(float("nan")) == "UNKNOWN"
