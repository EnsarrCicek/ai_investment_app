"""MARKET-RISK-1 (gölge mod) — XU100 günlük kapanışlarından piyasa riski.

Kapsamda YOK: piyasa genişliği (tarihsel endeks üyeliği doğrulanamadı), KAP,
VBTS, emir defteri. Bunların yokluğu değerlendirmeyi BELİRSİZ yapmaz.

Her kural YALNIZCA kendi geçmiş uzunluğuyla doğrulanır (bkz. `shadow_inputs`),
T sonrası veri kullanılmaz; birleşim üç durumludur:
    DRAWDOWN VE (VOLATİLİTE VEYA TREND)
Ör. zirveden düşüş kesin olarak eşik altındaysa, uzun geçmiş isteyen volatilite
kuralı hesaplanamasa bile sonuç "tetiklenmedi"dir; düşüş eşik üstünde ve trend
kuralı tetiklenmemişken volatilite hesaplanamıyorsa sonuç BELİRSİZ'dir.

Ölçümler:
  * INDEX_DRAWDOWN_FROM_HIGH: son `market_high_lookback` kapanışın zirvesinden düşüş.
  * INDEX_VOLATILITY_ELEVATED: `market_vol_window` günlük log-getiri std'sinin,
    son `market_vol_percentile_window` değer içindeki yüzdelik sırası (`<=`).
  * INDEX_BELOW_TREND: kapanış < son `market_trend_window` kapanışın basit ortalaması.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from app.engines.risk.shadow_inputs import (
    EVALUATED,
    INSUFFICIENT,
    MEASURE_DECIMALS,
    NOT_EVALUATED,
    RiskAssessment,
    RuleResult,
    ShadowRiskParams,
    build_assessment,
    kleene_and,
    kleene_or,
    validate_daily_closes,
)


def _rule(name, closes, as_of_session, required, compute) -> RuleResult:
    validated = validate_daily_closes(closes, as_of_session, required)
    if validated.status == INSUFFICIENT:
        return RuleResult(name, NOT_EVALUATED, None, required, validated.reason_codes)
    triggered, measure = compute(validated.closes)
    return RuleResult(name, EVALUATED, bool(triggered), required, (), _plain(measure))


def _plain(value):
    return value if value is None or isinstance(value, bool) else float(value)


def assess_market_risk(index_closes: pd.Series | None, as_of_session: date, params: ShadowRiskParams) -> RiskAssessment:
    def drawdown(c):
        value = round((1.0 - c.iloc[-1] / c.max()) * 100.0, MEASURE_DECIMALS)
        return value >= params.market_drawdown_trigger_pct, value

    def trend(c):
        below = bool(c.iloc[-1] < float(c.mean()))
        return below, below

    def volatility(c):
        log_returns = pd.Series([math.log(b / a) for a, b in zip(c.iloc[:-1], c.iloc[1:])])
        history = log_returns.rolling(params.market_vol_window).std().dropna()
        percentile = round(float((history <= float(history.iloc[-1])).mean() * 100.0), MEASURE_DECIMALS)
        return percentile >= params.market_vol_percentile_trigger, percentile

    rules = [
        _rule("INDEX_DRAWDOWN_FROM_HIGH", index_closes, as_of_session, params.market_high_lookback, drawdown),
        _rule("INDEX_VOLATILITY_ELEVATED", index_closes, as_of_session,
              params.market_vol_window + params.market_vol_percentile_window, volatility),
        _rule("INDEX_BELOW_TREND", index_closes, as_of_session, params.market_trend_window, trend),
    ]
    dd, vol, tr = (r.triggered for r in rules)
    composite = kleene_and(dd, kleene_or(vol, tr))
    measures = {
        "drawdown_from_high_pct": rules[0].measure,
        "vol_percentile": rules[1].measure,
        "below_trend": rules[2].measure,
    }
    return build_assessment("MARKET", as_of_session, params.version, rules, composite, measures)
