"""İndikatör fonksiyonlarının "causal" olduğunu doğrulayan regresyon testi.

TECHNICAL_ANALYSIS_RESEARCH1.md'nin en sık vurguladığı risk look-ahead bias:
bir bar için hesaplanan gösterge değeri, o bardan SONRA gelen barlar
eklendiğinde DEĞİŞMEMELİDİR — değişirse gösterge gelecekteki veriyi
"görüyor" demektir (ör. merkezi/centered bir pencere ya da ileri bakan bir
swing-point onayı). Bu test, seriyi kısaltıp uzatarak ilk N barın aynı
kaldığını doğrular; AŞAMA 48'den itibaren eklenecek her yeni gösterge/özellik
bu teste eklenmelidir (rapor madde 7, adım 2 — yeni özelliklerden ÖNCE
kurulması gereken güvenlik ağı).
"""

import numpy as np
import pandas as pd
import pytest

from app.engines.technical import indicators as ind
from app.engines.technical.regime import atr_percentile, efficiency_ratio
from app.engines.technical.relative_volume import relative_volume_series
from app.engines.technical.vwap import vwap_series

CUT = 50


def _sample_df(rows: int = 80, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    highs = closes + rng.uniform(0.1, 2, rows)
    lows = closes - rng.uniform(0.1, 2, rows)
    volume = rng.integers(1000, 5000, rows)
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volume})


_INDICATOR_CASES = [
    ("sma", lambda df: ind.sma(df["Close"], 20)),
    ("ema", lambda df: ind.ema(df["Close"], 20)),
    ("rsi", lambda df: ind.rsi(df["Close"])),
    ("macd_line", lambda df: ind.macd(df["Close"])[0]),
    ("macd_signal", lambda df: ind.macd(df["Close"])[1]),
    ("macd_hist", lambda df: ind.macd(df["Close"])[2]),
    ("bollinger_upper", lambda df: ind.bollinger_bands(df["Close"])[0]),
    ("bollinger_middle", lambda df: ind.bollinger_bands(df["Close"])[1]),
    ("bollinger_lower", lambda df: ind.bollinger_bands(df["Close"])[2]),
    ("atr", lambda df: ind.atr(df)),
    ("momentum", lambda df: ind.momentum(df["Close"])),
    ("roc", lambda df: ind.roc(df["Close"])),
    ("volume_sma", lambda df: ind.volume_sma(df["Volume"], 20)),
    ("relative_volume", lambda df: relative_volume_series(df["Volume"], 20)),
    ("ema_slope", lambda df: ind.ema_slope(df["Close"], 20, 5)),
    ("atr_percentile", lambda df: atr_percentile(ind.atr(df), window=20)),
    ("efficiency_ratio", lambda df: efficiency_ratio(df["Close"], window=10)),
    ("vwap", lambda df: vwap_series(df)),
]


@pytest.mark.parametrize("name, fn", _INDICATOR_CASES, ids=[c[0] for c in _INDICATOR_CASES])
def test_indicator_is_causal(name, fn):
    full_df = _sample_df()
    truncated_df = full_df.iloc[:CUT].copy()

    full_series = fn(full_df).iloc[:CUT].reset_index(drop=True)
    truncated_series = fn(truncated_df).reset_index(drop=True)

    pd.testing.assert_series_equal(full_series, truncated_series, check_names=False, atol=1e-9)
