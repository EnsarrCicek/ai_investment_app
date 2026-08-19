"""Volatilite ve trend/range rejim sınıflandırması —
TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7 adım 8.

Amaç: RSI/Bollinger gibi göstergelerin "rejime duyarlı" kullanılabilmesi için
önce piyasanın hangi rejimde olduğunu bilmek gerekir — sabit/aşırı
basitleştirilmiş bir eşik (ör. "RSI>70 ise SAT") trend piyasasında yanlış
sinyal üretir (dokümanın en çok vurguladığı noktalardan biri). Bu modül
henüz RSI/Bollinger'ı yeniden ağırlıklandırmıyor (bu, entegrasyon aşamasında
— rapor madde 7 adım 9'da — yapılacak); sadece rejimi HESAPLAR.

İki bağımsız eksen:
1. Volatilite rejimi: güncel ATR'nin son N barlık ATR dağılımındaki
   percentile'ı (LOW/NORMAL/HIGH/EXTREME).
2. Trend/Range rejimi: Kaufman Efficiency Ratio (net hareket / toplam
   mutlak hareket) — market_structure.classify_trend'in HH/HL/LH/LL tabanlı
   yapısal bakışını, tamamen ATR-bağımsız ikinci bir bakış açısıyla
   (fiyatın ne kadar "gürültüsüz/verimli" hareket ettiği) tamamlar.
"""

import pandas as pd


def atr_percentile(atr: pd.Series, window: int = 100) -> pd.Series:
    """Güncel ATR'nin son `window` barlık ATR dağılımı içindeki percentile'ı
    (0-100). `rolling().rank(pct=True)` yalnızca GEÇMİŞ pencereye bakar
    (causal) — mevcut/geçmiş barlar arasındaki sırayı kullanır, gelecekteki
    hiçbir bar'a bakmaz.
    """
    return atr.rolling(window=window, min_periods=window // 2).rank(pct=True) * 100


def classify_volatility_regime(percentile: float) -> str:
    if pd.isna(percentile):
        return "UNKNOWN"
    if percentile >= 90:
        return "EXTREME"
    if percentile >= 70:
        return "HIGH"
    if percentile <= 30:
        return "LOW"
    return "NORMAL"


def efficiency_ratio(close: pd.Series, window: int = 10) -> pd.Series:
    """Kaufman Efficiency Ratio: net hareket / toplam (mutlak) hareket.
    1'e yakın = güçlü, gürültüsüz bir trend; 0'a yakın = choppy/range piyasa
    (fiyat çok hareket etmiş ama net olarak hiçbir yere gitmemiş).
    """
    net_change = (close - close.shift(window)).abs()
    total_change = close.diff().abs().rolling(window=window).sum()
    return net_change / total_change.replace(0, pd.NA)


def classify_trend_regime(er: float, threshold: float = 0.3) -> str:
    if pd.isna(er):
        return "UNKNOWN"
    return "TRENDING" if er >= threshold else "CHOPPY"
