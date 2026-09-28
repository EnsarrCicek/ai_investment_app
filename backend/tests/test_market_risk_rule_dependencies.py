"""MARKET-RISK-1: her kural yalnızca ihtiyaç duyduğu veriyle, üç durumlu AND/OR.

Sentetik seriler yalnızca yazılım davranışını doğrular.
"""

from datetime import date

import pandas as pd

from app.engines.decision.risk_gate import ALLOWED, BLOCKED, INDETERMINATE, evaluate_shadow_risk_gate
from app.engines.risk.asset_risk import assess_asset_risk
from app.engines.risk.market_risk import assess_market_risk
from app.engines.risk.shadow_inputs import (
    EXPERIMENTAL_PARAMS_V0 as P,
    NO_RULE_TRIGGERED,
    RISK_TRIGGERED,
    UNDETERMINED,
    kleene_and,
    kleene_or,
)
from app.services.market_data.trading_calendar import expected_trading_sessions

SESSIONS = expected_trading_sessions(date(2025, 1, 1), date(2026, 9, 24))
T = SESSIONS[-1]


def _series(values):
    return pd.Series(list(values), index=pd.to_datetime(SESSIONS[-len(values):]))


def _asset(last_values, n=40, base=100.0):
    return _series([base] * (n - len(last_values)) + list(last_values))


INDEX_MISSING_T = _series([1000.0] * 40).iloc[:-1]  # endeksin T barı yok (ör. sağlayıcı NaN satırı)


def _rules(assessment):
    return {r.rule: (r.status, r.triggered) for r in assessment.rules}


def test_kleene_truth_tables():
    assert kleene_and(True, None) is None and kleene_and(False, None) is False and kleene_and(True, True) is True
    assert kleene_or(True, None) is True and kleene_or(False, None) is None and kleene_or(False, False) is False


def test_sharp_daily_decline_is_not_silenced_by_missing_index():
    result = assess_asset_risk(_asset([100.0, 90.0]), INDEX_MISSING_T, T, P)
    assert _rules(result)["SHARP_DAILY_DECLINE_OBSERVED"] == ("EVALUATED", True)
    assert _rules(result)["ASSET_UNDERPERFORMS_INDEX"][0] == "NOT_EVALUATED"
    assert result.risk_status == RISK_TRIGGERED
    assert evaluate_shadow_risk_gate("WEAK_BUY", assess_market_risk(INDEX_MISSING_T, T, P), result).gate_outcome == BLOCKED


def test_one_and_part_alone_never_vetoes():
    # dönem kaybı tetiklenir ama endekse göre zayıflık hesaplanamaz -> belirsiz, veto değil
    decline_only = assess_asset_risk(_asset([100.0, 97.0, 94.0, 91.0, 88.0, 85.0]), INDEX_MISSING_T, T, P)
    assert decline_only.risk_status == UNDETERMINED
    # dönem kaybı tetiklenir, zayıflık kesin YOK (endeks de aynı oranda düştü) -> tetiklenmedi
    index_same = _series([1000.0] * 34 + [1000.0, 970.0, 940.0, 910.0, 880.0, 850.0])
    both_known = assess_asset_risk(_asset([100.0, 97.0, 94.0, 91.0, 88.0, 85.0]), index_same, T, P)
    assert _rules(both_known)["ASSET_PERIOD_DECLINE"] == ("EVALUATED", True)
    assert _rules(both_known)["ASSET_UNDERPERFORMS_INDEX"] == ("EVALUATED", False)
    assert both_known.risk_status == NO_RULE_TRIGGERED


def test_asset_is_determinably_clear_when_known_parts_exclude_the_veto():
    # sert düşüş yok, dönem kaybı yok -> endeks eksik olsa da AND yanlış, OR yanlış
    result = assess_asset_risk(_asset([100.0, 99.0]), INDEX_MISSING_T, T, P)
    assert result.risk_status == NO_RULE_TRIGGERED and result.data_status == "PARTIAL"


def test_market_uses_each_rules_own_window():
    short = P.market_vol_window + P.market_vol_percentile_window - 1  # volatilite hesaplanamaz
    flat = assess_market_risk(_series([100.0] * short), T, P)
    assert _rules(flat)["INDEX_VOLATILITY_ELEVATED"][0] == "NOT_EVALUATED"
    assert flat.risk_status == NO_RULE_TRIGGERED  # zirveden düşüş kesin eşik altında

    dropped_below_trend = assess_market_risk(_series([100.0] * (short - 1) + [90.0]), T, P)
    assert _rules(dropped_below_trend)["INDEX_BELOW_TREND"] == ("EVALUATED", True)
    assert dropped_below_trend.risk_status == RISK_TRIGGERED  # DRAWDOWN VE TREND yeter

    peak = 100.0 + 10.0 * (short - 2)
    rising_then_drop = [100.0 + 10.0 * i for i in range(short - 1)] + [peak * 0.915]  # zirveden %8,5, trendin üstünde
    above_trend_drop = assess_market_risk(_series(rising_then_drop), T, P)
    assert _rules(above_trend_drop)["INDEX_DRAWDOWN_FROM_HIGH"] == ("EVALUATED", True)
    assert _rules(above_trend_drop)["INDEX_BELOW_TREND"] == ("EVALUATED", False)
    assert above_trend_drop.risk_status == UNDETERMINED  # volatilite olmadan karar verilemez


def test_gate_three_valued_outcomes_keep_raw_and_data_visible():
    market_unknown = assess_market_risk(INDEX_MISSING_T, T, P)
    clear_asset = assess_asset_risk(_asset([100.0, 99.0]), _series([1000.0] * 40), T, P)
    assert market_unknown.risk_status == UNDETERMINED
    result = evaluate_shadow_risk_gate("BUY", market_unknown, clear_asset)
    assert result.gate_outcome == INDETERMINATE and result.raw_decision == "BUY"
    assert result.market.data_status == "INSUFFICIENT"
    clear_market = assess_market_risk(_series([100.0] * 300), T, P)
    assert evaluate_shadow_risk_gate("BUY", clear_market, clear_asset).gate_outcome == ALLOWED
