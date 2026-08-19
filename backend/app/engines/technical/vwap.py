"""VWAP (Volume Weighted Average Price) ve Anchored VWAP —
TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7 adım 14 (intraday kısım).

VWAP, gün-içi barların (bkz. models/intraday_bar.py) hacim-ağırlıklı ortalama
fiyatıdır — kurumsal işlemcilerin "adil fiyat" referansı olarak kullandığı,
GÜNLÜK barlarla hesaplanamayan bir göstergedir (bu yüzden 5m bar biriktirme
altyapısı — AŞAMA 48/14b — gerekiyordu). "Anchored" VWAP, hesaplamanın seans
açılışından değil, belirli bir referans bar'dan (ör. bir kırılım/haber
anından) başlamasıdır.

Bu modül saf pandas fonksiyonlarından oluşur — Firestore'a bağımlı değildir,
IntradayBarRepository'den çekilmiş bir DataFrame'i (Open/High/Low/Close/
Volume) girdi alır.
"""

import pandas as pd


def _typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["High"] + df["Low"] + df["Close"]) / 3


def vwap_series(df: pd.DataFrame) -> pd.Series:
    """Seansın başından itibaren kümülatif VWAP — her bar yalnızca o ana
    kadarki barları kullanır (causal, ileriye bakmaz)."""
    typical = _typical_price(df)
    cumulative_pv = (typical * df["Volume"]).cumsum()
    cumulative_volume = df["Volume"].cumsum().replace(0, pd.NA)
    return cumulative_pv / cumulative_volume


def anchored_vwap_series(df: pd.DataFrame, anchor_index: int) -> pd.Series:
    """`anchor_index`'ten itibaren (dahil) VWAP hesaplar; öncesi NaN'dır."""
    if anchor_index < 0 or anchor_index >= len(df):
        raise ValueError(f"Geçersiz anchor_index: {anchor_index} (0..{len(df) - 1} aralığında olmalı)")
    anchored = vwap_series(df.iloc[anchor_index:])
    result = pd.Series(index=df.index, dtype=float)
    result.iloc[anchor_index:] = anchored.values
    return result


def price_vs_vwap_pct(close: float, vwap: float) -> float | None:
    """Fiyatın VWAP'a göre % konumu — pozitif: VWAP üzerinde (alıcı baskın
    bölge), negatif: altında. VWAP tanımsız/0 ise None döner."""
    if vwap == 0 or pd.isna(vwap):
        return None
    return round((close - vwap) / vwap * 100, 3)
