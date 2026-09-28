"""MARKET-RISK-1 hacim deneyi — zaman, pencere, eksik/sıfır hacim, ortak örneklem, ilk AL (ağ yok)."""

import json
import math
from datetime import date

import pandas as pd

from app.research.market_risk_shadow.volume_experiment import VOLUME_SESSIONS, compute_dvol, design
from app.research.market_risk_shadow.sharp_drop_coverage import first_days
from app.services.market_data.trading_calendar import expected_trading_sessions

CAL = expected_trading_sessions(date(2024, 1, 2), date(2025, 3, 31))
T = date(2024, 12, 2)
UPTO = [d for d in CAL if d <= T]


def _vol(values, sessions):
    return pd.Series([float(v) for v in values], index=list(sessions))


def test_formula_uses_exactly_120_sessions_and_future_does_not_matter():
    window = UPTO[-VOLUME_SESSIONS:]
    vol = _vol([100.0] * (VOLUME_SESSIONS - 20) + [200.0] * 20, window)
    value, why = compute_dvol(vol, T)
    assert why is None and math.isclose(value, math.log(2.0))
    with_future = pd.concat([vol, _vol([1e9] * 5, [d for d in CAL if d > T][:5])])
    assert compute_dvol(with_future, T) == (value, None)
    short = vol.iloc[1:]  # 119 seans
    assert compute_dvol(short, T) == (None, "VOLUME_MISSING_EXPECTED_SESSIONS")


def test_zero_missing_nan_negative_volume_are_not_valid():
    window = UPTO[-VOLUME_SESSIONS:]
    base = [100.0] * VOLUME_SESSIONS
    zero = list(base); zero[50] = 0.0
    assert compute_dvol(_vol(zero, window), T) == (None, "ZERO_VOLUME_IN_WINDOW")
    nan = list(base); nan[10] = float("nan")
    assert compute_dvol(_vol(nan, window), T) == (None, "VOLUME_NON_FINITE")
    neg = list(base); neg[10] = -5.0
    assert compute_dvol(_vol(neg, window), T) == (None, "NEGATIVE_VOLUME")
    assert compute_dvol(_vol(base, window).drop(window[60]), T) == (None, "VOLUME_MISSING_EXPECTED_SESSIONS")


def test_both_models_use_identical_rows_and_price_columns():
    samples = [{"x_price": [0.1 * i] * 6, "dvol": float(i)} for i in range(5)]
    price, full = design(samples, False), design(samples, True)
    assert price.shape == (5, 6) and full.shape == (5, 7)
    assert (full[:, :6] == price).all() and list(full[:, 6]) == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_first_buy_days_come_from_original_sequence_not_after_filtering():
    rows = [{"session": f"d{i}", "raw_class_technical_only": c} for i, c in enumerate(["BUY", "BUY", "BUY", "HOLD", "WEAK_BUY"])]
    firsts = {r["session"] for r in first_days(rows)}
    eligible = [r for r in rows if r["session"] != "d0"]  # ilk gün dışlandı
    flagged = [r["session"] for r in eligible if r["session"] in firsts]
    assert firsts == {"d0", "d4"} and flagged == ["d4"]  # d1 yeni "ilk gün" olmadı
