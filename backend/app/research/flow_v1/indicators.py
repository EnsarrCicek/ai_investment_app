"""FLOW 1B saf fiyat/hacim akış vekilleri (price/volume flow PROXIES).

Hepsi saf pandas/numpy fonksiyonudur (I/O yok). Girdi: TEK bir kesintisiz
seans segmenti (bkz. `dataset.split_into_segments`) — pencereler asla bir
boşluğun üzerinden hesaplanmaz, çünkü çağıran her segmenti ayrı işler.

Ortak sözleşme (projenin Missing Data ilkesi, `technical/scoring.py` ile aynı):
- Tanımsız/eksik değer her zaman NaN'dır; hiçbir yerde `fillna(0)` / ileri-geri
  doldurma YOKTUR.
- `0.0` yalnızca GERÇEK nötrdür (ör. alış/satış baskısı dengede).
- Pencerede herhangi bir girdi NaN ise o pencerenin sonucu NaN'dır.

Formüller kilitli protokoldedir (`flow_v1_protocol_v1.json` -> features).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CMF_WINDOW = 20
NSV_WINDOW = 20
MFI_WINDOW = 14
TURNOVER_WINDOW = 20
ROC_WINDOW = 20

# RESEARCH ONLY — kalibre edilmedi, protokolde ex-ante sabitlendi.
PVFS_CMF_SCALE = 0.25
PVFS_WEIGHTS = {"cmf": 0.5, "nsv": 0.5}


def _window_has_nan(frame: pd.DataFrame | pd.Series, window: int) -> pd.Series:
    """Son `window` satırın herhangi birinde (herhangi bir sütunda) NaN var mı."""
    if isinstance(frame, pd.DataFrame):
        row_nan = frame.isna().any(axis=1)
    else:
        row_nan = frame.isna()
    return row_nan.astype(float).rolling(window=window, min_periods=window).sum() > 0


def close_location_value(df: pd.DataFrame) -> pd.Series:
    """CLV = ((C-L)-(H-C))/(H-L). H==L (tavan/taban kilidi, tek fiyat) veya
    herhangi bir NaN -> NaN (tanımsız). 0'a ASLA çevrilmez."""
    high, low, close = df["High"], df["Low"], df["Close"]
    rng = high - low
    clv = ((close - low) - (high - close)) / rng
    return clv.where(rng > 0)


def cmf(df: pd.DataFrame, window: int = CMF_WINDOW) -> pd.Series:
    """Chaikin Money Flow (vekil).

    Tanımsız CLV'li bar (H==L) hem pay hem paydadan ÇIKARILIR. Pencerede
    OHLCV NaN varsa, pencere < `window` ise veya geçerli-bar hacim toplamı 0
    ise sonuç NaN.
    """
    clv = close_location_value(df)
    volume = df["Volume"].astype(float)
    valid = clv.notna() & volume.notna()
    num = (clv * volume).where(valid, 0.0).rolling(window=window, min_periods=window).sum()
    den = volume.where(valid, 0.0).rolling(window=window, min_periods=window).sum()
    result = num / den.where(den > 0)
    input_nan = _window_has_nan(df[["High", "Low", "Close", "Volume"]], window)
    return result.mask(input_nan)


def nsv(df: pd.DataFrame, window: int = NSV_WINDOW) -> pd.Series:
    """Normalize işaretli hacim: (Σ yükselen-kapanış hacmi − Σ düşen-kapanış
    hacmi) / Σ hacim. Düz kapanış yönsüzdür (pay 0) ama hacmi paydada kalır.
    Her bar bir önceki kapanışa ihtiyaç duyar -> ilk geçerli değer `window+1`.
    """
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    delta = close.diff()
    sign = np.sign(delta)
    signed = sign * volume
    num = signed.rolling(window=window, min_periods=window).sum()
    den = volume.rolling(window=window, min_periods=window).sum()
    result = num / den.where(den > 0)
    # delta'nın NaN'ı (ilk bar veya NaN kapanış) pencereyi geçersiz kılar.
    input_nan = _window_has_nan(pd.DataFrame({"d": delta, "v": volume}), window)
    return result.mask(input_nan)


def mfi(df: pd.DataFrame, window: int = MFI_WINDOW) -> pd.Series:
    """Money Flow Index (vekil, YALNIZCA araştırma — H6).

    TP=(H+L+C)/3, RMF=TP*V. TP artışı -> pozitif akış, düşüş -> negatif, eşit
    -> hiçbiri. MFI = 100*PF/(PF+NF). PF+NF == 0 -> NaN (sahte 50 yok).
    """
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    rmf = tp * df["Volume"].astype(float)
    d_tp = tp.diff()
    pos = rmf.where(d_tp > 0, 0.0)
    neg = rmf.where(d_tp < 0, 0.0)
    pf = pos.rolling(window=window, min_periods=window).sum()
    nf = neg.rolling(window=window, min_periods=window).sum()
    total = pf + nf
    result = 100.0 * pf / total.where(total > 0)
    input_nan = _window_has_nan(pd.DataFrame({"d": d_tp, "r": rmf}), window)
    return result.mask(input_nan)


def median_turnover(df: pd.DataFrame, window: int = TURNOVER_WINDOW) -> pd.Series:
    """medyan(Close*Volume, window) — YAKLAŞIK TL işlem değeri (Close temettü
    düzeltmeli). Yalnızca likidite tanımlayıcısı, sinyal değil."""
    value = df["Close"].astype(float) * df["Volume"].astype(float)
    result = value.rolling(window=window, min_periods=window).median()
    return result.mask(_window_has_nan(value, window))


def price_roc(close: pd.Series, window: int = ROC_WINDOW) -> pd.Series:
    """C_T / C_{T-window} - 1 (oran, yüzde değil)."""
    return close / close.shift(window) - 1.0


def pvfs(cmf_values: pd.Series, nsv_values: pd.Series) -> pd.Series:
    """Aday PVFS (RESEARCH ONLY) = 100 * Σ w_i c_i / Σ w_i, yalnızca mevcut
    bileşenler üzerinden (`technical/scoring.py` AVAILABLE sözleşmesi)."""
    c_cmf = (cmf_values / PVFS_CMF_SCALE).clip(lower=-1.0, upper=1.0)
    c_nsv = nsv_values
    comps = pd.DataFrame({"cmf": c_cmf, "nsv": c_nsv})
    finite = pd.DataFrame(np.isfinite(comps.to_numpy(dtype=float)), index=comps.index, columns=comps.columns)
    weights = pd.Series(PVFS_WEIGHTS, dtype=float)
    num = comps.where(finite, 0.0).mul(weights, axis=1).sum(axis=1)
    den = finite.astype(float).mul(weights, axis=1).sum(axis=1)
    return 100.0 * num / den.where(den > 0)
