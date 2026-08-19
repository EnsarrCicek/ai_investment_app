"""Piyasa yapısı: swing high/low tespiti ve HH/HL/LH/LL sınıflandırması
(TECHNICAL_ANALYSIS_RESEARCH1.md — rapor madde 7, adım 3).

İki temel ilke:
1. Look-ahead-bias-safe onay gecikmesi: bir bar'ın swing high/low olduğu,
   ancak sağındaki (gelecekteki) `right_bars` kadar bar tamamlandıktan SONRA
   "onaylanır". Serinin son `right_bars` bar'ı için henüz onay verilemez —
   bu bir eksiklik değil, bilinçli bir güvenlik sınırıdır (aksi halde
   gelecekteki veri kullanılmış/"repaint" edilmiş olur).
2. Config/backtest ile ayarlanabilirlik: `left_bars`/`right_bars` pencere
   büyüklüğü sabit "evrensel doğru" değil, parametreleştirilmiş (varsayılan
   5/5 — klasik fraktal pivot tanımı), ileride backtest ile kalibre edilebilir.

Kapsam notu: Bu modül yalnızca yapı tespiti/etiketlemesi yapar; henüz
TechnicalAnalysisEngine'in skoruna bağlanmadı (bkz. KURULUM_GUNLUGU.md,
AŞAMA 48 — Support/Resistance ve Breakout modülleri de bittikten sonra,
backtest ile doğrulanarak tek seferde entegre edilecek).
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SwingType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass
class SwingPoint:
    index: int
    date: pd.Timestamp
    price: float
    type: SwingType
    label: str | None = None  # HH / HL / LH / LL — aynı tipteki bir önceki swing'e göre


def find_swing_points(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> list[SwingPoint]:
    """Klasik fraktal pivot: High[i], [i-left_bars, i+right_bars] penceresindeki
    en yüksek değerse swing high; Low[i] en düşükse swing low.

    Not: Eşit değerli (tie) barlarda basit bir >= karşılaştırması birden fazla
    komşu bar'ı swing point olarak işaretleyebilir — gerçek fiyat verisinde
    (float) bu son derece nadir olduğundan bilinçli olarak ele alınmadı.
    """
    highs, lows = df["High"], df["Low"]
    points: list[SwingPoint] = []
    n = len(df)
    for i in range(left_bars, n - right_bars):
        window_high = highs.iloc[i - left_bars : i + right_bars + 1]
        if highs.iloc[i] == window_high.max():
            points.append(SwingPoint(index=i, date=df.index[i], price=float(highs.iloc[i]), type=SwingType.HIGH))
        window_low = lows.iloc[i - left_bars : i + right_bars + 1]
        if lows.iloc[i] == window_low.min():
            points.append(SwingPoint(index=i, date=df.index[i], price=float(lows.iloc[i]), type=SwingType.LOW))
    points.sort(key=lambda p: p.index)
    return points


def label_structure(points: list[SwingPoint]) -> list[SwingPoint]:
    """Ardışık aynı tipteki swing point'leri karşılaştırıp HH/HL/LH/LL etiketler
    (yerinde mutasyon + aynı liste döner). İlk high/low'un karşılaştıracak
    öncülü olmadığından label'ı None kalır.
    """
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    for p in points:
        if p.type == SwingType.HIGH:
            if last_high is not None:
                p.label = "HH" if p.price > last_high.price else "LH"
            last_high = p
        else:
            if last_low is not None:
                p.label = "HL" if p.price > last_low.price else "LL"
            last_low = p
    return points


def classify_trend(points: list[SwingPoint], lookback: int = 4) -> str:
    """Son `lookback` etiketlenmiş swing point'e bakarak basit bir çoğunluk
    kuralıyla piyasa yapısını sınıflandırır (UPTREND/DOWNTREND/RANGE/UNKNOWN).

    Bu, dokümanın "regime" kavramının en basit/yapısal hali — ATR/ADX tabanlı
    volatilite ve trend/range rejim sınıflandırması ayrı bir modülde
    (rapor madde 7, adım 8) eklenecek.
    """
    labeled = [p for p in points if p.label is not None][-lookback:]
    if not labeled:
        return "UNKNOWN"
    bullish = sum(1 for p in labeled if p.label in ("HH", "HL"))
    bearish = sum(1 for p in labeled if p.label in ("LH", "LL"))
    if bullish > bearish:
        return "UPTREND"
    if bearish > bullish:
        return "DOWNTREND"
    return "RANGE"


def analyze_market_structure(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5, lookback: int = 4) -> dict:
    """Üç adımı (tespit, etiketleme, sınıflandırma) birleştiren, engine'in
    çağıracağı tek giriş noktası."""
    points = label_structure(find_swing_points(df, left_bars=left_bars, right_bars=right_bars))
    return {
        "structure": classify_trend(points, lookback=lookback),
        "swing_points": points,
    }
