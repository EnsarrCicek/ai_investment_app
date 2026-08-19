"""Göreli güç (relative strength) — BIST endeksine göre
(TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7, adım 10).

Basit ratio yöntemi (Mansfield/IBD RS-line mantığı): asset_close / benchmark_
close oranının zaman içindeki değişimi. Oran yükseliyorsa varlık endeksten
DAHA İYİ performans gösteriyor demektir — mutlak fiyat yönünden bağımsızdır
(hem varlık hem endeks düşse bile varlık daha AZ düşüyorsa oran yine de
yükselir).

Benchmark verisi, RiskEngine'de zaten kullanılan aynı mekanizmayla
(BistProvider, "XU100" -> yfinance "XU100.IS") çekilir — yeni bir provider
metoduna gerek yoktur (bkz. risk/engine.py DEFAULT_BENCHMARK).
"""

import pandas as pd


def relative_strength_ratio(asset_close: pd.Series, benchmark_close: pd.Series) -> pd.Series:
    """İki seriyi ortak tarihlere hizalayıp asset/benchmark oranını döner."""
    aligned = pd.concat([asset_close, benchmark_close], axis=1, join="inner")
    aligned.columns = ["asset", "benchmark"]
    return aligned["asset"] / aligned["benchmark"].replace(0, pd.NA)


def relative_strength_score(ratio: pd.Series, lookback: int = 20) -> float | None:
    """Oranın son `lookback` bardaki % değişimi — pozitif: endeksten daha iyi
    performans (outperformance), negatif: daha kötü (underperformance).
    Yeterli veri yoksa None döner (Missing Data Davranışı — 0 gibi yanlış bir
    "nötr" varsayım UYDURULMAZ).
    """
    if len(ratio) <= lookback:
        return None
    current = ratio.iloc[-1]
    past = ratio.iloc[-1 - lookback]
    if pd.isna(current) or pd.isna(past) or past == 0:
        return None
    return float(((current - past) / past) * 100)


def classify_relative_strength(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score > 3.0:
        return "OUTPERFORMING"
    if score < -3.0:
        return "UNDERPERFORMING"
    return "IN_LINE"
