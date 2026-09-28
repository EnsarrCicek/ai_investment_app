"""MARKET-RISK-1 (gölge mod) — hisseye özgü risk.

Kapsamda YOK: hacim/likidite bozulması, KAP, VBTS işlem tedbirleri, emir defteri.

Her kural yalnızca İHTİYAÇ DUYDUĞU veriyle değerlendirilir (bkz. `shadow_inputs`):
  * SHARP_DAILY_DECLINE_OBSERVED: yalnızca hissenin T ve T-1 kapanışları.
  * ASSET_PERIOD_DECLINE: yalnızca hissenin son `asset_drop_window`+1 kapanışı.
  * ASSET_UNDERPERFORMS_INDEX: hisse VE endeksin son `asset_relative_window`+1
    kapanışı, aynı beklenen seans listesinde hizalı.
Birleşim üç durumludur: (DÖNEM KAYBI VE ENDEKSE GÖRE ZAYIFLIK) VEYA SERT GÜNLÜK DÜŞÜŞ.
Endeks verisi eksik olsa bile, hisse verisiyle kesin tetiklenen sert günlük düşüş
tek başına sonucu belirler; AND'in yalnız bir parçası tetiklendiğinde veto oluşmaz.

"SHARP_DAILY_DECLINE_OBSERVED" yalnızca bir fiyat hareketi gözlemidir: resmî fiyat
sınırı/referans fiyat olmadan "taban" veya "satılamaz" anlamına gelmez; günlük
OHLCV bir emrin gerçekleştiğini ya da gerçekleşmediğini kanıtlamaz.
"""

from __future__ import annotations

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
    pct_change_over,
    validate_daily_closes,
)


def assess_asset_risk(
    asset_closes: pd.Series | None, index_closes: pd.Series | None, as_of_session: date, params: ShadowRiskParams
) -> RiskAssessment:
    def asset_only(name, sessions, trigger_pct):
        required = sessions + 1
        validated = validate_daily_closes(asset_closes, as_of_session, required)
        if validated.status == INSUFFICIENT:
            return RuleResult(name, NOT_EVALUATED, None, required, tuple(f"ASSET_{c}" for c in validated.reason_codes))
        change = pct_change_over(validated.closes, sessions)
        return RuleResult(name, EVALUATED, bool(change <= -trigger_pct), required, (), float(change))

    def relative():
        window = params.asset_relative_window
        required = window + 1
        asset = validate_daily_closes(asset_closes, as_of_session, required)
        index = validate_daily_closes(index_closes, as_of_session, required)
        missing = tuple(f"ASSET_{c}" for c in asset.reason_codes) + tuple(f"INDEX_{c}" for c in index.reason_codes)
        if missing:
            return RuleResult("ASSET_UNDERPERFORMS_INDEX", NOT_EVALUATED, None, required, missing)
        diff = round(pct_change_over(asset.closes, window) - pct_change_over(index.closes, window), MEASURE_DECIMALS)
        return RuleResult(
            "ASSET_UNDERPERFORMS_INDEX", EVALUATED, bool(diff <= -params.asset_relative_underperformance_trigger_pct),
            required, (), float(diff),
        )

    decline = asset_only("ASSET_PERIOD_DECLINE", params.asset_drop_window, params.asset_drop_trigger_pct)
    underperform = relative()
    sharp = asset_only("SHARP_DAILY_DECLINE_OBSERVED", 1, params.asset_sharp_daily_drop_trigger_pct)
    rules = [decline, underperform, sharp]
    composite = kleene_or(kleene_and(decline.triggered, underperform.triggered), sharp.triggered)
    measures = {
        "period_return_pct": decline.measure,
        "relative_to_index_pct": underperform.measure,
        "daily_return_pct": sharp.measure,
    }
    return build_assessment("ASSET", as_of_session, params.version, rules, composite, measures)
