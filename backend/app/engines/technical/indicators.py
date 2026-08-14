"""Saf pandas ile hesaplanan teknik göstergeler.

Üçüncü parti bir TA kütüphanesi yerine burada elle hesaplanmasının nedeni:
AIExplanationEngine'in ileride "nasıl hesaplandığını" doğrulanabilir şekilde
açıklayabilmesi için hesaplama mantığının tamamen bu kod tabanında, denetlenebilir
olması (ana doküman kural 11-12: AI yalnız gerçek/izlenebilir verilere dayanmalı).
"""

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - (100 / (1 + rs))).fillna(50)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, window)
    std = series.rolling(window=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False).mean()


def momentum(series: pd.Series, window: int = 10) -> pd.Series:
    return series.diff(window)


def roc(series: pd.Series, window: int = 10) -> pd.Series:
    return (series.diff(window) / series.shift(window)) * 100


def volume_sma(volume: pd.Series, window: int = 20) -> pd.Series:
    return sma(volume, window)
