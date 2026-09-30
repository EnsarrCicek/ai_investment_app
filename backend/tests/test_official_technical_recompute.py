import copy
import math
from datetime import date

import pandas as pd

from app.research.official_bist.recompute_technical import evaluate_symbol
from app.services.market_data.trading_calendar import expected_trading_sessions

SESSIONS = expected_trading_sessions(date(2024, 5, 7), date(2024, 12, 20))  # sentetik, BSOKE aralığı
T_PRE, T_POST = date(2024, 12, 9), date(2024, 12, 11)


def synthetic_rows(start=0):
    rows = []
    for i, d in enumerate(SESSIONS[start:]):
        c = 50 + 5 * math.sin(i / 9) + i * 0.05
        if d >= date(2024, 12, 10):
            c = c * 0.262165  # bedelli sonrası ham ölçek
        rows.append({"trade_date": d.isoformat(), "open": f"{c:.4f}", "high": f"{c * 1.01:.4f}", "low": f"{c * 0.99:.4f}",
                     "close": f"{c:.4f}", "total_traded_quantity_raw": "100000"})
    return rows


INDEX = pd.Series([1000 + i for i in range(len(SESSIONS))], index=SESSIONS)


def run(rows, t, flags=()):
    return evaluate_symbol("BSOKE", rows, list(flags), INDEX, [t])[0]


def test_future_bars_and_future_event_do_not_change_T():
    base = run(synthetic_rows(), T_PRE)
    changed = synthetic_rows()
    for r in changed:
        if r["trade_date"] > T_PRE.isoformat():
            r.update(open="1", high="1", low="1", close="1")
    assert base["status"] == "OK" and base["applied_events"] == []
    assert run(changed, T_PRE) == base


def test_event_applied_after_effective_date():
    rows = synthetic_rows()
    fk = float(next(r["close"] for r in rows if r["trade_date"] == "2024-12-09"))
    rec = run(rows, T_POST)
    assert rec["status"] == "OK" and rec["applied_events"] == [f"2024-12-10 DK={(fk + 3 * 1.0) / 4 / fk:.6f}"]


def test_insufficient_official_history_rejected():
    rec = run(synthetic_rows(start=40), T_PRE)
    assert rec["status"] == "HESAPLANAMADI" and rec["reason"].startswith("RESMI_GECMIS_YETERSIZ")


def test_unexplained_corporate_action_flag_rejected():
    rec = run(synthetic_rows(), T_PRE, flags=[{"trade_date": "2024-10-01", "OZSERMAYE HALI": "02"}])
    assert rec["status"] == "HESAPLANAMADI" and rec["reason"].startswith("ACIKLANAMAYAN_KURUMSAL_ISLEM_ISARETI")


def test_raw_rows_not_mutated():
    rows = synthetic_rows()
    before = copy.deepcopy(rows)
    run(rows, T_POST)
    assert rows == before
