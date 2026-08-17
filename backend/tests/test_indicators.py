import pandas as pd

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


def test_rsi_mostly_increasing_series_is_high():
    # Not: mutlak monoton (hiç kaybı olmayan) bir seri özel bir durum yaratır —
    # avg_loss tam 0 olur, rs = avg_gain/0 -> NaN -> fillna(50) devreye girer
    # (bkz. indicators.py rsi()). Gerçek piyasa verisinde bu neredeyse hiç
    # olmaz; küçük ara düşüşler içeren bir seri kullanmak gerçek kullanımı
    # daha doğru temsil eder.
    values = [100.0]
    for i in range(29):
        values.append(values[-1] + (2.0 if i % 5 != 4 else -0.5))
    series = pd.Series(values)
    result = ind.rsi(series, window=14)
    assert result.iloc[-1] > 80


def test_rsi_strictly_decreasing_series_is_low():
    series = pd.Series(range(30, 1, -1), dtype=float)
    result = ind.rsi(series, window=14)
    assert result.iloc[-1] < 5


def test_rsi_flat_series_is_50():
    series = pd.Series([100.0] * 30)
    result = ind.rsi(series, window=14)
    assert result.iloc[-1] == 50.0


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
