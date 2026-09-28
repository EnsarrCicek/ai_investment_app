"""MARKET-RISK-1 sepet karşılaştırması — saf yardımcılar (ağ yok)."""

from datetime import date

from app.research.market_risk_shadow.basket_review import _outcomes, _stats, blocked_episodes, path_extremes
from app.services.market_data.trading_calendar import expected_trading_sessions

CAL = expected_trading_sessions(date(2025, 12, 1), date(2026, 1, 30))


def test_path_extremes_uses_only_closes_and_never_substitutes_missing_or_pending():
    closes = {d: 100.0 + i for i, d in enumerate(CAL)}
    t = CAL[0]
    ok = path_extremes(closes, t, CAL, 10)
    assert ok == {"status": "OK", "worst": 1.0, "best": 10.0}
    gap = dict(closes)
    del gap[CAL[4]]
    assert path_extremes(gap, t, CAL, 10) == {"status": "MISSING"}
    assert path_extremes(closes, CAL[-3], CAL, 10) == {"status": "PENDING"}
    assert path_extremes(gap, CAL[4], CAL, 10) == {"status": "MISSING_T"}


def test_zero_observations_report_na_not_percent():
    assert _stats([]) == {"n": 0, "median": "N/A", "negative_share": "N/A"}
    empty = _outcomes([])
    assert empty["T+10"]["median"] == "N/A" and empty["T+10_path"]["median_worst_close"] == "N/A"


def test_unavailable_horizons_are_counted_separately():
    rows = [
        {"price_move_after_close": {"T+5": 2.0, "T+10": "MISSING", "T+20": "PENDING"}, "t10_path": {"status": "MISSING"}},
        {"price_move_after_close": {"T+5": -1.0, "T+10": 3.0, "T+20": "PENDING"}, "t10_path": {"status": "OK", "worst": -2.0, "best": 3.0}},
    ]
    out = _outcomes(rows)
    assert out["T+5"] == {"n": 2, "median": 0.5, "negative_share": 0.5, "unavailable": 0, "positive_count": 1, "negative_count": 1}
    assert out["T+10"]["n"] == 1 and out["T+10"]["unavailable"] == 1
    assert out["T+20"]["n"] == 0 and out["T+20"]["unavailable"] == 2
    assert out["T+10_path"]["n"] == 1 and out["T+10_path"]["unavailable"] == 1


def test_consecutive_blocked_sessions_count_as_one_episode():
    gates = ["ALLOWED", "BLOCKED", "BLOCKED", "NOT_APPLICABLE", "BLOCKED", "INDETERMINATE", "BLOCKED", "BLOCKED"]
    rows = [{"session": f"d{i}", "shadow_gate": g} for i, g in enumerate(gates)]
    episodes = blocked_episodes(rows)
    assert [(e["start"], e["length"]) for e in episodes] == [("d1", 2), ("d4", 1), ("d6", 2)]
