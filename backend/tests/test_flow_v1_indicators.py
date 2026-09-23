"""FLOW 1B — araştırma fiyat/hacim akış vekilleri (CMF20/NSV20/MFI14/PVFS).
Ağ yok; tüm girdiler sentetik."""

import math

import numpy as np
import pandas as pd
import pytest

from app.research.flow_v1 import indicators as fi


def _frame(high, low, close, volume, open_=None):
    n = len(close)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": open_ if open_ is not None else close,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=idx,
        dtype=float,
    )


# ---------------------------------------------------------------- CMF


def test_cmf_normal_matches_hand_computation():
    rng = np.random.default_rng(1)
    close = 100 + rng.normal(0, 1, 25).cumsum()
    high = close + rng.uniform(0.1, 1.0, 25)
    low = close - rng.uniform(0.1, 1.0, 25)
    volume = rng.uniform(1000, 5000, 25)
    df = _frame(high, low, close, volume)
    result = fi.cmf(df, window=20)
    clv = ((close - low) - (high - close)) / (high - low)
    expected = (clv[-20:] * volume[-20:]).sum() / volume[-20:].sum()
    assert result.iloc[-1] == pytest.approx(expected)
    assert result.iloc[:19].isna().all()
    assert result.iloc[19:].notna().all()


def test_cmf_high_equals_low_bar_excluded_from_numerator_and_denominator():
    close = np.full(20, 10.0)
    high = np.full(20, 11.0)
    low = np.full(20, 9.0)
    close[:] = 10.5  # CLV = 0.5 for normal bars
    volume = np.full(20, 100.0)
    # Bar 5: tavan kilidi (H==L==C), çok büyük hacim — dahil edilseydi CMF'yi düşürürdü.
    high[5] = low[5] = close[5] = 12.0
    volume[5] = 1_000_000.0
    result = fi.cmf(_frame(high, low, close, volume), window=20).iloc[-1]
    assert result == pytest.approx(0.5)  # 19 geçerli bar, hepsi CLV=0.5


def test_cmf_all_bars_high_equals_low_is_unavailable_not_zero():
    close = np.full(20, 10.0)
    df = _frame(close, close, close, np.full(20, 100.0))
    assert math.isnan(fi.cmf(df, window=20).iloc[-1])


def test_cmf_zero_total_volume_is_unavailable():
    close = np.linspace(10, 11, 20)
    df = _frame(close + 0.5, close - 0.5, close, np.zeros(20))
    assert math.isnan(fi.cmf(df, window=20).iloc[-1])


def test_cmf_insufficient_history_is_unavailable():
    close = np.linspace(10, 11, 19)
    df = _frame(close + 0.5, close - 0.5, close, np.full(19, 100.0))
    assert fi.cmf(df, window=20).isna().all()


def test_cmf_nan_inside_window_makes_window_unavailable():
    close = np.linspace(10, 11, 25)
    volume = np.full(25, 100.0)
    volume[10] = np.nan
    df = _frame(close + 0.5, close - 0.5, close, volume)
    result = fi.cmf(df, window=20)
    # 10. barı içeren tüm pencereler (son indeks 10..29 ∩ 19..24) NaN
    assert result.iloc[19:25].isna().all()


def test_cmf_range_is_bounded():
    rng = np.random.default_rng(7)
    close = 50 + rng.normal(0, 2, 300).cumsum().clip(-40, None)
    high = close + rng.uniform(0.01, 2, 300)
    low = close - rng.uniform(0.01, 2, 300)
    result = fi.cmf(_frame(high, low, close, rng.uniform(1, 1e6, 300))).dropna()
    assert len(result) > 0
    assert result.between(-1.0, 1.0).all()


def test_cmf_extremes():
    close = np.full(20, 11.0)
    up = fi.cmf(_frame(np.full(20, 11.0), np.full(20, 9.0), close, np.full(20, 5.0))).iloc[-1]
    down = fi.cmf(_frame(np.full(20, 11.0), np.full(20, 9.0), np.full(20, 9.0), np.full(20, 5.0))).iloc[-1]
    assert up == pytest.approx(1.0)
    assert down == pytest.approx(-1.0)


# ---------------------------------------------------------------- NSV


def _closes(values, volume=None):
    values = np.asarray(values, dtype=float)
    volume = np.full(len(values), 100.0) if volume is None else np.asarray(volume, dtype=float)
    return _frame(values + 1, values - 1, values, volume)


def test_nsv_all_up_is_plus_one():
    assert fi.nsv(_closes(np.arange(1, 22))).iloc[-1] == pytest.approx(1.0)


def test_nsv_all_down_is_minus_one():
    assert fi.nsv(_closes(np.arange(22, 1, -1))).iloc[-1] == pytest.approx(-1.0)


def test_nsv_flat_closes_are_genuine_zero_not_unavailable():
    result = fi.nsv(_closes(np.full(21, 10.0))).iloc[-1]
    assert result == 0.0


def test_nsv_flat_close_volume_stays_in_denominator():
    closes = np.arange(1, 22, dtype=float)
    closes[-1] = closes[-2]  # son bar düz
    volume = np.full(21, 100.0)
    volume[-1] = 900.0
    result = fi.nsv(_closes(closes, volume)).iloc[-1]
    assert result == pytest.approx(1900.0 / 2800.0)


def test_nsv_zero_volume_is_unavailable():
    assert math.isnan(fi.nsv(_closes(np.arange(1, 22), np.zeros(21))).iloc[-1])


def test_nsv_insufficient_history_needs_window_plus_one_closes():
    result = fi.nsv(_closes(np.arange(1, 21)))  # 20 kapanış -> 19 fark
    assert result.isna().all()
    assert fi.nsv(_closes(np.arange(1, 22))).notna().sum() == 1


def test_nsv_range_is_bounded():
    rng = np.random.default_rng(3)
    closes = 100 + rng.normal(0, 1, 200).cumsum()
    result = fi.nsv(_closes(closes, rng.uniform(1, 1e5, 200))).dropna()
    assert result.between(-1.0, 1.0).all()


# ---------------------------------------------------------------- MFI


def test_mfi_normal_matches_hand_computation():
    rng = np.random.default_rng(11)
    close = 20 + rng.normal(0, 0.5, 20).cumsum()
    high, low = close + 0.3, close - 0.3
    volume = rng.uniform(100, 900, 20)
    result = fi.mfi(_frame(high, low, close, volume), window=14).iloc[-1]
    tp = (high + low + close) / 3
    rmf = tp * volume
    d = np.diff(tp)[-14:]
    r = rmf[-14:]
    pf = r[d > 0].sum()
    nf = r[d < 0].sum()
    assert result == pytest.approx(100 * pf / (pf + nf))


def test_mfi_all_positive_flow_is_100():
    assert fi.mfi(_closes(np.arange(1, 16))).iloc[-1] == pytest.approx(100.0)


def test_mfi_all_negative_flow_is_0():
    assert fi.mfi(_closes(np.arange(16, 1, -1))).iloc[-1] == pytest.approx(0.0)


def test_mfi_zero_flows_is_unavailable_not_50():
    assert math.isnan(fi.mfi(_closes(np.full(15, 10.0))).iloc[-1])


def test_mfi_insufficient_history_is_unavailable():
    assert fi.mfi(_closes(np.arange(1, 15))).isna().all()


# ---------------------------------------------------------------- PVFS


def test_pvfs_research_composite_and_missing_component():
    cmf = pd.Series([0.125, np.nan, 0.5, np.nan])
    nsv = pd.Series([0.5, 0.4, -1.0, np.nan])
    result = fi.pvfs(cmf, nsv)
    assert result.iloc[0] == pytest.approx(100 * (0.5 * 0.5 + 0.5 * 0.5))
    assert result.iloc[1] == pytest.approx(40.0)  # yalnız mevcut bileşen, renormalize
    assert result.iloc[2] == pytest.approx(0.0)  # c_cmf=+1 (clamp), c_nsv=-1 -> gerçek nötr
    assert math.isnan(result.iloc[3])  # hiçbiri yok -> 0 değil
