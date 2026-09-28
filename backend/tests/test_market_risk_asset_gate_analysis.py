"""MARKET-RISK-1 araştırma alternatifi (yalnızca hisse riski engeller) — ağsız."""

import copy
import json

from app.research.market_risk_shadow.asset_gate_analysis import alternative_gate, analyze, runs

RULES = {"ASSET_PERIOD_DECLINE": {"triggered": False}, "ASSET_UNDERPERFORMS_INDEX": {"triggered": False},
         "SHARP_DAILY_DECLINE_OBSERVED": {"triggered": True}}


def _row(day, raw, gate, asset, market="RISK_TRIGGERED"):
    return {"session": f"2025-01-{day:02d}", "raw_class_technical_only": raw, "shadow_gate": gate, "asset_risk": asset,
            "market_risk": market, "technical_status": "OK" if raw else "TECHNICAL_UNAVAILABLE", "technical_score": 30.0,
            "asset_rules": copy.deepcopy(RULES), "asset_measures": {"daily_return_pct": -10.0, "period_return_pct": -12.0},
            "price_move_after_close": {"T+5": 1.0, "T+10": -2.0, "T+20": "PENDING"},
            "t10_path": {"status": "OK", "worst": -3.0, "best": 1.0}}


def test_unknown_asset_risk_is_not_treated_as_passing_and_raw_is_kept():
    unknown = _row(2, "BUY", "INDETERMINATE", "UNDETERMINED")
    before = copy.deepcopy(unknown)
    assert alternative_gate(unknown) == "INDETERMINATE"
    assert unknown == before  # ham karar ve kayıtlı durumlar değişmez
    assert alternative_gate(_row(3, "WEAK_BUY", "BLOCKED", "RISK_TRIGGERED")) == "BLOCKED"
    assert alternative_gate(_row(4, "BUY", "BLOCKED", "NO_DEFINED_RULE_TRIGGERED")) == "ALLOWED_BY_ASSET_FILTER"
    assert alternative_gate(_row(5, "HOLD", "NOT_APPLICABLE", "RISK_TRIGGERED")) == "NOT_APPLICABLE"
    assert alternative_gate(_row(6, None, "NO_RAW_CLASS", "RISK_TRIGGERED")) == "NO_RAW_CLASS"


def test_transitions_add_up_and_episodes_follow_consecutive_sessions(tmp_path):
    rows = [_row(2, "BUY", "BLOCKED", "RISK_TRIGGERED"), _row(3, "BUY", "BLOCKED", "RISK_TRIGGERED"),
            _row(6, "BUY", "BLOCKED", "NO_DEFINED_RULE_TRIGGERED"), _row(7, "BUY", "INDETERMINATE", "UNDETERMINED"),
            _row(8, None, "NO_RAW_CLASS", "UNDETERMINED"), _row(9, "HOLD", "NOT_APPLICABLE", "RISK_TRIGGERED"),
            _row(10, "WEAK_BUY", "BLOCKED", "RISK_TRIGGERED")]
    (tmp_path / "results").mkdir()
    (tmp_path / "universe_manifest.json").write_text(json.dumps({"symbols": ["AAA"]}), encoding="utf-8")
    (tmp_path / "results" / "AAA.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    year = analyze(tmp_path)["years"]["2025"]
    assert sum(year["transitions_current_to_alternative"].values()) == len(rows)
    assert year["transitions_current_to_alternative"]["BLOCKED->ALLOWED_BY_ASSET_FILTER"] == 1
    assert year["transitions_current_to_alternative"]["INDETERMINATE->INDETERMINATE"] == 1
    assert year["asset_sourced_blocked_signals"] == 3 and year["asset_sourced_episodes"] == 2
    assert year["alternative_still_blocked"]["signals"] == 3
    assert year["released_all"]["signals"] == 1
    first = year["episodes"][0]
    assert first["previous_session"].startswith("BİLİNMİYOR") and first["rule_pattern"] == "SHARP_ONLY"


def test_runs_split_on_any_break():
    flags = [True, True, False, True]
    assert runs([{"x": f} for f in flags], lambda r: r["x"]) == [(0, 1), (3, 3)]
