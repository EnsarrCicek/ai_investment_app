"""MARKET-RISK-1 gölge risk değerlendirmesi ve kapısı.

Sentetik seriler yalnızca YAZILIM davranışını doğrular; düşüş tahmin başarısı
veya kayıptan korunma kanıtı DEĞİLDİR. Parametreler doğrulanmamış deneysel settir.
"""

import dataclasses
import math
from datetime import date

import pandas as pd
import pytest

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, DecisionEngine
from app.engines.decision.risk_gate import (
    ALLOWED,
    BLOCKED,
    BUY_DIRECTION_CLASSES,
    INDETERMINATE,
    NOT_APPLICABLE,
    evaluate_shadow_risk_gate,
)
from app.engines.risk.asset_risk import assess_asset_risk
from app.engines.risk.market_risk import assess_market_risk
from app.engines.risk.shadow_inputs import (
    EXPERIMENTAL_PARAMS_V0 as P,
    INSUFFICIENT,
    NO_RULE_TRIGGERED,
    PARTIAL,
    RISK_TRIGGERED,
    UNDETERMINED,
    RiskAssessment,
)
from app.services.market_data.trading_calendar import expected_trading_sessions

SESSIONS = expected_trading_sessions(date(2025, 1, 1), date(2026, 9, 24))
T = SESSIONS[-1]


def _series(values, sessions=None):
    sessions = sessions or SESSIONS[-len(values):]
    return pd.Series(list(values), index=pd.to_datetime(sessions))


def _calm(n=len(SESSIONS), start=100.0):
    # Hafif, düzenli dalgalı yükseliş: risk kuralı tetiklenmez.
    return [start * (1 + 0.0005 * i) * (1 + 0.003 * math.sin(i)) for i in range(n)]


def _market_selloff():
    values = _calm()
    for k in range(1, 16):  # son 15 seansta büyüyen dalgalı düşüş
        values[-k] = values[-k] * (1 - 0.009 * (16 - k)) * (1 + 0.02 * (-1) ** k)
    return values


def _assessment(scope, status, data=None):
    return RiskAssessment(
        scope=scope, as_of_session=T, params_version=P.version, required_sessions=1,
        data_status=data or ("INSUFFICIENT" if status == UNDETERMINED else "SUFFICIENT"),
        data_reason_codes=("RULE:NO_DATA",) if status == UNDETERMINED else (),
        risk_status=status, reason_codes=("X",) if status == RISK_TRIGGERED else (),
    )


TRIGGERED, CLEAR, MISSING = (_assessment("MARKET", RISK_TRIGGERED), _assessment("MARKET", NO_RULE_TRIGGERED),
                             _assessment("MARKET", UNDETERMINED))
A_TRIGGERED, A_CLEAR, A_MISSING = (dataclasses.replace(x, scope="ASSET") for x in (TRIGGERED, CLEAR, MISSING))


# ------------------------------------------------------------------ gate contract


def test_buy_direction_classes_cover_every_positive_classification():
    assert BUY_DIRECTION_CLASSES == {"BUY", "WEAK_BUY"}


@pytest.mark.parametrize("raw", sorted(BUY_DIRECTION_CLASSES))
def test_every_buy_class_is_blocked_by_either_trigger_and_raw_is_preserved(raw):
    for market, asset in ((TRIGGERED, A_CLEAR), (CLEAR, A_TRIGGERED), (TRIGGERED, A_MISSING)):
        result = evaluate_shadow_risk_gate(raw, market, asset)
        assert result.gate_outcome == BLOCKED and result.raw_decision == raw


@pytest.mark.parametrize("raw", ["HOLD", "WEAK_SELL", "SELL"])
def test_non_buy_is_not_applicable_and_keeps_risk_and_data_visible(raw):
    result = evaluate_shadow_risk_gate(raw, TRIGGERED, A_MISSING)
    assert result.gate_outcome == NOT_APPLICABLE and result.raw_decision == raw
    assert result.market.risk_status == RISK_TRIGGERED and result.asset.data_status == INSUFFICIENT


def test_outcomes_never_turn_into_sell_or_hold():
    outcomes = {
        evaluate_shadow_risk_gate(raw, m, a).gate_outcome
        for raw in ("BUY", "WEAK_BUY", "HOLD", "WEAK_SELL", "SELL")
        for m in (TRIGGERED, CLEAR, MISSING)
        for a in (A_TRIGGERED, A_CLEAR, A_MISSING)
    }
    assert outcomes == {ALLOWED, BLOCKED, INDETERMINATE, NOT_APPLICABLE}


def test_missing_required_data_without_trigger_is_indeterminate_and_clear_is_allowed():
    assert evaluate_shadow_risk_gate("BUY", MISSING, A_CLEAR).gate_outcome == INDETERMINATE
    assert evaluate_shadow_risk_gate("BUY", CLEAR, A_CLEAR).gate_outcome == ALLOWED


def test_unknown_decision_class_is_rejected():
    with pytest.raises(ValueError):
        evaluate_shadow_risk_gate("STRONG_BUY", CLEAR, A_CLEAR)


class _Config:
    def get_raw(self, key):
        return {"decision_weights": dict(DEFAULT_WEIGHTS), "decision_thresholds": dict(DEFAULT_THRESHOLDS)}.get(key)


def test_strong_raw_decision_cannot_pass_the_gate_and_production_decision_is_unchanged():
    engine = DecisionEngine(config_repo=_Config(), decision_repo=object())
    decision = engine.decide("THYAO", technical_score=100.0, news_score=100.0, macro_score=100.0, persist=False)
    before = decision.model_dump()

    market = assess_market_risk(_series(_market_selloff()), T, P)
    asset = assess_asset_risk(_series(_calm()), _series(_market_selloff()), T, P)
    shadow = evaluate_shadow_risk_gate(decision.decision, market, asset)

    assert decision.decision == "BUY" and decision.final_score == pytest.approx(100.0)
    assert market.risk_status == RISK_TRIGGERED
    assert shadow.gate_outcome == BLOCKED and shadow.raw_decision == "BUY"
    assert decision.model_dump() == before  # ham/üretim kararı değişmedi


# ------------------------------------------------------------------ assessors


def test_market_selloff_triggers_and_calm_series_does_not():
    assert assess_market_risk(_series(_market_selloff()), T, P).risk_status == RISK_TRIGGERED
    calm = assess_market_risk(_series(_calm()), T, P)
    assert calm.risk_status == NO_RULE_TRIGGERED and calm.data_status == "SUFFICIENT"
    assert calm.params_version == P.version and set(calm.measures) >= {"drawdown_from_high_pct", "vol_percentile"}


def test_required_history_is_derived_from_lookbacks():
    assert P.required_market_sessions() == max(20, 50, 20 + 250)
    assert P.required_asset_sessions() == max(5, 20) + 1
    short = assess_market_risk(_series(_calm(n=P.required_market_sessions() - 1)), T, P)
    # yalnızca uzun geçmiş isteyen volatilite kuralı hesaplanamaz; diğerleri kendi pencereleriyle çalışır
    assert short.data_status == PARTIAL
    assert short.data_reason_codes == ("INDEX_VOLATILITY_ELEVATED:MISSING_EXPECTED_SESSIONS",)


@pytest.mark.parametrize("mutate, code", [
    (lambda s: s.drop(s.index[-1]), "AS_OF_SESSION_MISSING"),  # T barı yok / eski veri
    (lambda s: s.drop(s.index[-10]), "MISSING_EXPECTED_SESSIONS"),
    (lambda s: pd.concat([s, s.iloc[[-3]]]), "DUPLICATE_SESSIONS"),
    (lambda s: s.where(s.index != s.index[-5], float("nan")), "NON_FINITE_OR_NON_POSITIVE_CLOSE"),
    (lambda s: s.where(s.index != s.index[-5], float("inf")), "NON_FINITE_OR_NON_POSITIVE_CLOSE"),
])
def test_bad_input_is_insufficient_not_forward_filled(mutate, code):
    result = assess_market_risk(mutate(_series(_calm())), T, P)
    assert result.data_status == INSUFFICIENT and any(c.endswith(code) for c in result.data_reason_codes)
    assert result.risk_status == UNDETERMINED


def test_non_session_as_of_date_is_insufficient():
    result = assess_market_risk(_series(_calm()), date(2026, 9, 26), P)  # Cumartesi
    assert result.data_status == INSUFFICIENT and all(c.endswith("AS_OF_NOT_EXPECTED_SESSION") for c in result.data_reason_codes)


def test_misaligned_asset_and_index_leave_only_rules_needing_that_window_unevaluated():
    asset = _series(_calm()).drop(pd.Timestamp(SESSIONS[-3]))
    result = assess_asset_risk(asset, _series(_calm()), T, P)
    status = {r.rule: r.status for r in result.rules}
    assert status == {"ASSET_PERIOD_DECLINE": "NOT_EVALUATED", "ASSET_UNDERPERFORMS_INDEX": "NOT_EVALUATED",
                      "SHARP_DAILY_DECLINE_OBSERVED": "EVALUATED"}
    assert result.data_status == PARTIAL and result.risk_status == UNDETERMINED


def test_data_after_t_cannot_change_the_t_result():
    t_prev = SESSIONS[-2]
    series = _series(_market_selloff())
    truncated = series[series.index <= pd.Timestamp(t_prev)]
    wild_future = series.copy()
    wild_future.iloc[-1] = wild_future.iloc[-1] * 50  # T sonrası (t_prev'e göre) uç değer
    a = assess_market_risk(truncated, t_prev, P)
    b = assess_market_risk(wild_future, t_prev, P)
    assert (a.risk_status, a.measures) == (b.risk_status, b.measures)


# ------------------------------------------------------------------ threshold boundaries


def _flat_then(last_values, base=100.0):
    return _series([base] * (P.required_asset_sessions() + 5 - len(last_values)) + list(last_values))


@pytest.mark.parametrize("close, hit", [(85.0, True), (85.01, False)])
def test_asset_period_decline_boundary_is_inclusive(close, hit):
    # 5 seanslık kayıp tam %15 (dahil) / hemen üstü; endeks düz -> göreli kayıp da eşik üstü.
    asset = _flat_then([100.0, 97.0, 94.0, 91.0, 88.0, close])  # kademeli: günlük kural devreye girmez
    result = assess_asset_risk(asset, _flat_then([]), T, P)
    assert ("ASSET_PERIOD_DECLINE" in result.reason_codes) is hit
    assert (result.risk_status == RISK_TRIGGERED) is hit


@pytest.mark.parametrize("close, hit", [(90.5, True), (90.51, False)])
def test_sharp_daily_decline_boundary_is_inclusive_and_named_as_observation(close, hit):
    result = assess_asset_risk(_flat_then([100.0, close]), _flat_then([]), T, P)
    assert ("SHARP_DAILY_DECLINE_OBSERVED" in result.reason_codes) is hit
    assert not any("LIMIT" in c or "TABAN" in c for c in result.reason_codes)


@pytest.mark.parametrize("close, hit", [(92.0, True), (92.01, False)])
def test_market_drawdown_boundary_is_inclusive(close, hit):
    values = [100.0] * (P.required_market_sessions() - 1) + [close]
    result = assess_market_risk(_series(values), T, P)
    assert ("INDEX_DRAWDOWN_FROM_HIGH" in result.reason_codes) is hit
