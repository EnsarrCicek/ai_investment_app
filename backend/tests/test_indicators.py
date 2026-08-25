import pandas as pd
import pytest

from app.engines.technical import indicators as ind


def test_sma():
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = ind.sma(series, window=3)
    assert result.iloc[-1] == 4.0
    assert pd.isna(result.iloc[0])


def test_ema_converges_toward_recent_values():
    series = pd.Series([10.0] * 20 + [20.0] * 20)
    result = ind.ema(series, window=5)
    assert result.iloc[-1] > 19.0


def test_rsi_warmup_is_nan_before_window():
    # 25.08.2026 RSI denetimi: klasik Wilder'da ilk `window` fiyat değişimi
    # tamamlanmadan (SMA seed oluşmadan) RSI tanımsızdır — index 0..window-1
    # NaN olmalı, ilk geçerli değer tam index=window'da oluşmalı.
    series = pd.Series([100.0 + i for i in range(30)])
    result = ind.rsi(series, window=14)
    assert result.iloc[0:14].isna().all()
    assert pd.notna(result.iloc[14])


def test_rsi_matches_reference_wilder_values():
    # Elle hesaplanmış (SMA seed + Wilder recursion) referans değerlerle
    # floating-point toleransı dışında birebir eşleşmeli — "yaklaşık Wilder"
    # değil GERÇEK Wilder olduğunu kilit altına alır.
    deltas = [
        1.2, -0.5, 0.8, 1.5, -0.3, 0.6, -1.1, 2.0, -0.4, 0.9,
        -0.7, 1.3, 0.2, -0.9, 1.1, -0.6, 0.5, -0.2, 1.4, -0.8,
    ]
    prices = [100.0]
    for d in deltas:
        prices.append(prices[-1] + d)
    series = pd.Series(prices)
    window = 14

    # Referans: window=14 -> seed = gain/loss[1:15].mean(), sonrası recursive.
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.iloc[1 : window + 1].mean()
    avg_loss = loss.iloc[1 : window + 1].mean()
    expected_at_seed = 100 - (100 / (1 + avg_gain / avg_loss))

    expected = [expected_at_seed]
    ag, al = avg_gain, avg_loss
    for i in range(window + 1, len(series)):
        ag = (ag * (window - 1) + gain.iloc[i]) / window
        al = (al * (window - 1) + loss.iloc[i]) / window
        expected.append(100 - (100 / (1 + ag / al)))

    result = ind.rsi(series, window=window)

    assert result.iloc[window] == pytest.approx(expected[0], abs=1e-9)
    for offset, exp_val in enumerate(expected[:5]):
        assert result.iloc[window + offset] == pytest.approx(exp_val, abs=1e-9)
    assert result.iloc[-1] == pytest.approx(expected[-1], abs=1e-9)


def test_rsi_strictly_increasing_series_is_exactly_100():
    series = pd.Series([100.0 + i for i in range(30)])
    result = ind.rsi(series, window=14)
    assert result.iloc[0:14].isna().all()
    assert (result.iloc[14:] == 100.0).all()


def test_rsi_strictly_decreasing_series_is_exactly_zero():
    series = pd.Series(range(30, 1, -1), dtype=float)
    result = ind.rsi(series, window=14)
    assert result.iloc[0:14].isna().all()
    assert (result.iloc[14:] == 0.0).all()


def test_rsi_flat_series_is_50_only_after_warmup():
    series = pd.Series([100.0] * 30)
    result = ind.rsi(series, window=14)
    assert result.iloc[0:14].isna().all()
    assert (result.iloc[14:] == 50.0).all()


def test_macd_returns_three_series_same_length():
    series = pd.Series(range(1, 50), dtype=float)
    macd_line, signal_line, histogram = ind.macd(series)
    assert len(macd_line) == len(series)
    assert len(signal_line) == len(series)
    assert len(histogram) == len(series)


def test_bollinger_bands_ordering():
    series = pd.Series([10, 12, 9, 15, 11, 13, 10, 14, 12, 16, 9, 18] * 3, dtype=float)
    upper, middle, lower = ind.bollinger_bands(series, window=5)
    valid = upper.dropna().index
    assert (upper.loc[valid] >= middle.loc[valid]).all()
    assert (middle.loc[valid] >= lower.loc[valid]).all()


def test_atr_is_never_negative():
    df = pd.DataFrame(
        {
            "High": [10.0, 11.0, 12.0, 11.0, 13.0],
            "Low": [9.0, 9.0, 10.0, 9.0, 11.0],
            "Close": [9.5, 10.5, 11.0, 10.0, 12.0],
        }
    )
    result = ind.atr(df, window=3)
    assert (result.dropna() >= 0).all()


def test_momentum_and_roc():
    series = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0, 20.0])
    momentum = ind.momentum(series, window=5)
    roc = ind.roc(series, window=5)
    assert momentum.iloc[-1] == 10.0
    assert roc.iloc[-1] == 100.0


def test_volume_sma():
    volume = pd.Series([100, 200, 300, 400, 500], dtype=float)
    result = ind.volume_sma(volume, window=3)
    assert result.iloc[-1] == 400.0


def test_ema_slope_is_positive_for_rising_series():
    series = pd.Series([10.0 + i for i in range(40)])
    result = ind.ema_slope(series, window=10, slope_lookback=5)
    assert result.iloc[-1] > 0


def test_ema_slope_is_zero_for_flat_series():
    series = pd.Series([10.0] * 40)
    result = ind.ema_slope(series, window=10, slope_lookback=5)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_ema_slope_is_negative_for_falling_series():
    series = pd.Series([100.0 - i for i in range(40)])
    result = ind.ema_slope(series, window=10, slope_lookback=5)
    assert result.iloc[-1] < 0
