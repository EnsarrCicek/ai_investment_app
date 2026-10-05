import csv
import hashlib
from datetime import date

from app.research.position_exit import official_run as orun
from app.research.position_exit.normalized import Bar
from app.services.market_data.trading_calendar import expected_trading_sessions

S = expected_trading_sessions(date(2025, 3, 3), date(2025, 4, 30))
COLS = ["trade_date", "share_code", "status", "open", "high", "low", "close", "previous_last_price", "total_traded_quantity_raw",
        "total_traded_value_raw", "corporate_action_flag", "suspended_flag", "price_basis", "source_file", "source_sha256"]


def flat_bars(price=10.0, days=S):
    return {d: Bar(price, price * 1.01, price * 0.99, price, 1000) for d in days}


def test_hash_or_session_scope_mismatch_not_run(tmp_path):
    p = tmp_path / "ABC.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for d in S[:3]:
            w.writerow({k: "" for k in COLS} | {"trade_date": d.isoformat(), "status": "OK", "open": "1", "high": "1", "low": "1",
                                                "close": "1", "total_traded_quantity_raw": "5", "suspended_flag": "0"})
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    allowed = [d.isoformat() for d in S[:3]]
    review = {"usable_sessions": allowed, "bound_to": {"raw_csv_sha256": digest}}
    tech = {"raw_csv_sha256": digest, "accepted": allowed, "records": [{"session": t, "status": "OK", "raw_class": "HOLD"} for t in allowed]}
    assert orun.symbol_inputs("ABC", review, tech, p)["status"] == "RUN"
    assert orun.symbol_inputs("ABC", review | {"bound_to": {"raw_csv_sha256": "x"}}, tech, p)["reason"] == "RAW_CSV_HASH_MISMATCH"
    assert orun.symbol_inputs("ABC", review, tech | {"accepted": allowed[:2]}, p)["reason"] == "TECHNICAL_SESSIONS_NOT_EQUAL_TO_REVIEW_SCOPE"


def test_entry_on_missing_next_session_is_unevaluable_not_skipped():
    bars = flat_bars()
    bars.pop(S[1])  # sinyalden sonraki beklenen seans izinli değil/bar yok
    classes = {d: "HOLD" for d in S if d in bars} | {S[0]: "BUY"}
    res = orun.evaluate_symbols({"ABC": {"sessions": S, "bars": bars, "classes": classes}})
    assert res["completed"] == [] and res["open"] == []
    assert res["unevaluable"][0]["reason"] == "ENTRY_EXECUTION_UNDETERMINED"


def test_open_at_data_end_is_separate_and_not_force_sold():
    bars = flat_bars()
    classes = {d: "HOLD" for d in S} | {S[0]: "BUY"}
    res = orun.evaluate_symbols({"ABC": {"sessions": S[:5], "bars": bars, "classes": classes}})
    assert len(res["open"]) == 1 and res["completed"] == []
    ref = res["open"][0]["runs"]["REF"]
    assert ref["open_at_end"] and ref["sales"] == []
    table = orun.open_table(res["open"])
    assert table["REF"]["position_open_at_data_end"] == 1


def test_b_principal_planned_vs_actual_and_completed_table():
    bars = flat_bars()
    up = 11.5
    bars[S[2]] = Bar(10.0, 11.6, 10.0, up, 1000)  # hedef kapanışı (giriş 10)
    bars[S[3]] = Bar(11.0, 11.2, 10.4, 10.5, 1000)  # T+1 açılışı plan fiyatının altında; kapanış hedef altı (yeniden plan yok)
    classes = {d: "HOLD" for d in S} | {S[0]: "BUY", S[6]: "SELL"}
    res = orun.evaluate_symbols({"ABC": {"sessions": S[:10], "bars": bars, "classes": classes}})
    ep = res["completed"][0]
    (b,) = ep["b_principal"]
    assert abs(b["planned_net"] - 1.0) < 1e-9 and b["actual_net"] < b["planned_net"]
    t = orun.completed_table(res["completed"])
    assert t["B_principal"]["actual_below_planned"] == 1 and t["B_principal"]["episodes_cum_net_reached_1_incl_later_sales"] == 1  # kalan satışıyla; hedef satışı tek başına değil
    assert t["REF"]["exit_reasons"] == {"REFERENCE_EXIT": 1}
