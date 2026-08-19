"""Göreli hacim (relative volume) — TECHNICAL_ANALYSIS_RESEARCH1.md, rapor
madde 7, adım 6.

Mevcut indicators.volume_sma zaten SMA tabanlı bir ortalama hesaplıyordu, ama
yalnızca TechnicalAnalysisEngine'in `confidence`'ı için ham bir oran olarak
kullanılıyordu (bkz. engine.py — volume_confirmation). Bu modül, göreli
hacmi kendi başına anlamlı bir ÖZELLİK olarak formalize eder:

- Medyan tabanlı baseline: SMA yerine rolling median kullanılır — tek bir
  aşırı hacimli gün (ör. bilanço açıklaması) ortalamayı SMA'dan daha az
  çarpıtır (dokümanın "median baseline" önerisi).
- Sınıflandırma eşikleri parametreleştirildi — evrensel sabit değil,
  backtest ile kalibre edilebilir (SystemConfigRepository üzerinden
  entegrasyon aşamasında config-driven hale getirilecek).

Gün-içi zaman-dilimi bazlı baseline (ör. "saat 10:00'daki tipik hacim") bu
sürümde YOK — mevcut BistProvider yalnızca günlük bar döndürüyor; bunun için
intraday veri biriktirme (5m bar persistence) altyapısı gerekir (rapor
madde 7, adım 14 — ertelendi).
"""

import pandas as pd

DEFAULT_THRESHOLDS = {"low": 0.5, "high": 1.5, "very_high": 2.5}


def relative_volume_series(volume: pd.Series, window: int = 20) -> pd.Series:
    """volume / rolling_median(volume, window). İlk `window-1` bar NaN'dır
    (yeterli geçmiş yok) — bu bilinçlidir, 1.0 gibi yanlış bir nötr değer
    UYDURULMAZ (Missing Data Davranışı ile tutarlı, bkz. decision/engine.py).
    """
    baseline = volume.rolling(window=window).median()
    return volume / baseline.replace(0, pd.NA)


def classify_relative_volume(ratio: float, thresholds: dict = DEFAULT_THRESHOLDS) -> str:
    if pd.isna(ratio):
        return "UNKNOWN"
    if ratio >= thresholds["very_high"]:
        return "VERY_HIGH"
    if ratio >= thresholds["high"]:
        return "HIGH"
    if ratio < thresholds["low"]:
        return "LOW"
    return "NORMAL"
