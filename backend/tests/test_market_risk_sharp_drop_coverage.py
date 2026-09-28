"""MARKET-RISK-1 sert düşüş kapsamı — eksik pencere, zaman sızıntısı, tablo toplamları (ağ yok)."""

from datetime import date

from app.research.market_risk_shadow.sharp_drop_coverage import (
    DROP,
    NO_DROP,
    UNDETERMINED,
    coverage_table,
    first_days,
    forward_drop_outcome,
)
from app.services.market_data.trading_calendar import expected_trading_sessions

CAL = expected_trading_sessions(date(2025, 1, 2), date(2025, 3, 31))


def _closes(values):
    return {d: v for d, v in zip(CAL, values)}


def test_missing_window_is_not_treated_as_no_drop_but_visible_drop_is_certain():
    flat = _closes([100.0] * 20)
    assert forward_drop_outcome(flat, CAL[0], CAL) == NO_DROP
    gap = dict(flat)
    del gap[CAL[5]]
    assert forward_drop_outcome(gap, CAL[0], CAL) == UNDETERMINED
    gap[CAL[3]] = 89.0  # eksik bara rağmen görünen -%11
    assert forward_drop_outcome(gap, CAL[0], CAL) == DROP
    assert forward_drop_outcome(_closes([100.0] * 5), CAL[0], CAL) == UNDETERMINED  # ufuk tamamlanmadı


def test_loss_on_or_before_t_is_not_counted_as_forward_drop():
    values = [100.0, 80.0] + [80.0] * 12  # T=CAL[1] günü zaten -%20 düştü, sonrası düz
    assert forward_drop_outcome(_closes(values), CAL[1], CAL) == NO_DROP
    boundary = [100.0] + [100.0] * 4 + [90.0] + [100.0] * 8
    assert forward_drop_outcome(_closes(boundary), CAL[0], CAL) == DROP  # tam -%10 dahil


def test_table_cells_add_up_and_ratios_use_explicit_denominators():
    items = [("BLOCKED", DROP, True), ("BLOCKED", NO_DROP, False), ("ALLOWED", DROP, False), ("ALLOWED", NO_DROP, False),
             ("INDETERMINATE", DROP, False), ("ALLOWED", UNDETERMINED, False)]
    t = coverage_table(items)
    assert sum(sum(v.values()) for v in t["cells"].values()) == t["total"] == len(items)
    assert t["blocked_that_later_dropped"] == {"num": 1, "den": 2, "share": 0.5}
    assert t["drops_that_were_blocked"] == {"num": 1, "den": 3, "share": 0.3333}
    assert t["outcome_undetermined"] == {"num": 1, "den": 6, "share": 0.1667}
    assert coverage_table([])["drops_that_were_blocked"]["share"] == "N/A"


def test_first_day_view_takes_only_the_start_of_each_consecutive_buy_run():
    rows = [{"raw_class_technical_only": c, "session": str(i)} for i, c in enumerate(["BUY", "WEAK_BUY", "HOLD", "BUY", None, "BUY"])]
    assert [r["session"] for r in first_days(rows)] == ["0", "3", "5"]
