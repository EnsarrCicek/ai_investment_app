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


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Klasik Wilder RSI — 25.08.2026 RSI denetimi sonucu düzeltildi.

    Önceki sürüm `avg_gain`/`avg_loss` için `ewm(alpha=1/window, adjust=False)`
    kullanıyordu: recursion adımı Wilder'la aynı olsa da, SEED farklıydı —
    `ewm` recursion'a tek bir ham gözlemden (bar 1) başlıyor, bu da ilk
    `window` barı (henüz gerçek bir `window`-barlık ortalama oluşmamışken)
    "geçerli" bir sayıymış gibi üretiyordu; ayrıca `avg_loss == 0` olan
    barlarda (ör. kesintisiz yükseliş) `NaN → fillna(50)` devreye girip
    RSI=100 olması gerekirken 50 (nötr) dönüyordu — bkz. TEKNIK_ANALIZ_
    METODOLOJISI.md.

    Bu sürüm: ilk `window` fiyat değişimi SMA ile "seed" edilir (bar
    `window`'da ilk geçerli değer oluşur), sonrasında Wilder'ın recursive
    düzleştirmesiyle ilerletilir. `window`'dan önceki barlar (yetersiz
    geçmiş) kasıtlı olarak NaN kalır — Missing Data Davranışı ilkesiyle
    uyumlu, hiçbir global `fillna(50)`/`fillna(0)` uygulanmaz.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    n = len(series)
    result = pd.Series(index=series.index, dtype=float)
    if n <= window:
        return result

    avg_gain = float(gain.iloc[1 : window + 1].mean())
    avg_loss = float(loss.iloc[1 : window + 1].mean())
    result.iloc[window] = _rsi_from_averages(avg_gain, avg_loss)

    gain_values = gain.to_numpy()
    loss_values = loss.to_numpy()
    for i in range(window + 1, n):
        avg_gain = (avg_gain * (window - 1) + gain_values[i]) / window
        avg_loss = (avg_loss * (window - 1) + loss_values[i]) / window
        result.iloc[i] = _rsi_from_averages(avg_gain, avg_loss)

    return result


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


def ema_slope(series: pd.Series, window: int = 20, slope_lookback: int = 5) -> pd.Series:
    """EMA'nın son `slope_lookback` bar'daki değişim oranı (%) — TECHNICAL_
    ANALYSIS_RESEARCH1.md, rapor madde 7 adım 7: ham iki-EMA-kesişimi/anlık
    farkı yerine EMA'nın ZAMAN İÇİNDEKİ yönünü ve gücünü ölçer (engine.py'daki
    mevcut "trend" bileşeni yalnızca tek bir anın EMA20-EMA50 farkını alır,
    eğimi değil).
    """
    ema_series = ema(series, window)
    shifted = ema_series.shift(slope_lookback)
    return ((ema_series - shifted) / shifted.replace(0, pd.NA)) * 100
