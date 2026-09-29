import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.research.position_exit import __main__ as cli
from app.research.position_exit.engine import ScenarioError, simulate

SCENARIOS = json.loads((Path(__file__).resolve().parents[1] / "app/research/position_exit/scenarios_TEMSILI.json")
                       .read_text(encoding="utf-8"))["scenarios"]
BY_NAME = {s["name"]: s for s in SCENARIOS}
PARAMS = {"target_pct": 10, "stop_loss_pct": 8, "trailing_pct": 5, "max_holding_sessions": 20, "lot_size": 1,
          "fees": {"commission_rate_pct": "0.1", "min_commission": "0", "slippage_pct_assumption": "0"}}


def scenario(bars, qty=100, price="10.00", fees="1.00", params=None, session="2026-09-01"):
    return {"data_origin": "TEMSILI", "symbol": "ORNEK",
            "entry": {"session": session, "quantity": qty, "price": price, "fees": fees, "fees_basis": "ASSUMED"},
            "params": params or copy.deepcopy(PARAMS),
            "bars": [{"session": d, "close": c} for d, c in bars]}


def fill(rid, req, session, qty, price=None, final=True, **extra):
    r = {"report_id": rid, "request_id": req, "session": session, "filled_quantity": qty, "final": final, **extra}
    if price is not None:
        r["price"] = price
    return r


def run_named(name, policy):
    sc = BY_NAME[name]
    run = next(r for r in sc["runs"] if r["policy"] == policy)
    return simulate(sc, policy, run["executions"])


def conserved(res, qty0):
    s, ex = res["summary"], res["_exact"]
    applied = [r for r in res["reports"] if r["result"] == "APPLIED" and r["filled_quantity"]]
    assert s["sold_quantity"] + s["remaining_quantity"] == qty0
    assert sum(r["filled_quantity"] for r in applied) == s["sold_quantity"]
    allocated = sum(Decimal(r["allocated_cost"]) for r in applied)
    assert abs(ex["principal"] - ex["remaining_cost"] - allocated) <= Decimal("0.01") * max(1, len(applied))
    assert ex["realized"] == pytest.approx(ex["net_proceeds"] - (ex["principal"] - ex["remaining_cost"]))


# --- Zorunlu senaryolar -------------------------------------------------------------------------

def test_s1_three_policies_quantity_cash_and_remaining_cost():
    a, b, c = (run_named("S1_1000_TL_TO_1100_TL", p) for p in ("A_FULL_AT_TARGET", "B_RECOVER_PRINCIPAL", "C_HALF_THEN_TRAIL"))
    assert a["initial_principal"] == "1001.00"
    assert (a["summary"]["sold_quantity"], a["summary"]["remaining_cost"], a["summary"]["cumulative_net_sale_proceeds"]) == (100, "0.00", "1098.90")
    assert (b["summary"]["sold_quantity"], b["summary"]["remaining_cost"], b["summary"]["cumulative_net_sale_proceeds"]) == (92, "80.08", "1010.99")
    assert (c["summary"]["sold_quantity"], c["summary"]["remaining_cost"], c["summary"]["cumulative_net_sale_proceeds"]) == (50, "500.50", "549.45")
    assert b["summary"]["principal_recovered"] and not c["summary"]["principal_recovered"]
    for res in (a, b, c):
        conserved(res, 100)


def test_s8_sale_proceeds_differ_from_realized_profit():
    b = run_named("S1_1000_TL_TO_1100_TL", "B_RECOVER_PRINCIPAL")["summary"]
    assert b["cumulative_net_sale_proceeds"] == "1010.99" and b["realized_pnl"] == "90.07"
    assert b["remaining_cost"] == "80.08"  # anapara geri alındı ama kalan maliyet sıfır DEĞİL


def test_s2_whole_lot_forces_selling_all_ten():
    res = run_named("S2_10_LOTS_AT_100_PRICE_110_WHOLE_LOT", "B_RECOVER_PRINCIPAL")
    assert res["requests"][0]["quantity"] == 10
    assert res["summary"]["remaining_quantity"] == 0 and res["summary"]["principal_recovered"]


def test_b_not_reachable_is_reported_without_request():
    params = copy.deepcopy(PARAMS)
    params["fees"]["min_commission"] = "500"
    res = simulate(scenario([("2026-09-02", "11.00")], params=params), "B_RECOVER_PRINCIPAL", [])
    t = res["timeline"][0]
    assert "B_RECOVERY_NOT_REACHABLE_WITH_REMAINING_QUANTITY" in t["notes"] and "request" not in t


def test_s3_stop_before_target_full_exit_all_policies():
    for policy in ("A_FULL_AT_TARGET", "B_RECOVER_PRINCIPAL", "C_HALF_THEN_TRAIL"):
        res = run_named("S3_STOP_BEFORE_TARGET", policy)
        req = res["requests"][0]
        assert (req["primary_reason"], req["quantity"], req["session"]) == ("STOP_LOSS", 100, "2026-09-04")
        assert res["summary"]["realized_pnl"] == "-96.91"
        conserved(res, 100)


def test_s4_trailing_level_never_loosens_and_exits_on_reversal():
    res = run_named("S4_RALLY_CONTINUES_THEN_REVERSES", "C_HALF_THEN_TRAIL")
    levels = [Decimal(t["trailing_level"]) for t in res["timeline"] if t.get("trailing_level")]
    assert levels == sorted(levels) and levels[-1] == Decimal("11.875")
    assert [r["primary_reason"] for r in res["requests"]] == ["TARGET", "TRAILING_STOP"]
    assert res["summary"]["remaining_quantity"] == 0
    conserved(res, 100)


def test_s5_gap_down_uses_reported_price_not_target_or_stop_level():
    res = run_named("S5_GAP_DOWN_BELOW_LEVELS", "B_RECOVER_PRINCIPAL")
    first, second = [r for r in res["reports"] if r["result"] == "APPLIED"]
    assert first["price"] == "10.20" and first["net_proceeds"] == "937.46"
    assert second["price"] == "8.90"  # zarar sınırı 9.20 değil
    assert res["requests"][1]["primary_reason"] == "STOP_LOSS"
    # anapara ancak ikinci (zarar sınırı) satışından SONRA kümülatif tahsilatla aşıldı
    assert res["summary"]["principal_recovered_session"] == "2026-09-08"
    conserved(res, 100)


def test_s6_not_filled_and_partial_fill_then_re_request():
    a = run_named("S6_NOT_FILLED_AND_PARTIAL", "A_FULL_AT_TARGET")
    assert a["requests"][0]["status"] == "NOT_FILLED_CLOSED"
    assert a["summary"]["remaining_quantity"] == 100 and a["summary"]["cumulative_net_sale_proceeds"] == "0.00"
    assert a["summary"]["open_request"] == "A_FULL_AT_TARGET-R2"
    b = run_named("S6_NOT_FILLED_AND_PARTIAL", "B_RECOVER_PRINCIPAL")
    assert [r["status"] for r in b["requests"]] == ["PARTIALLY_FILLED_CLOSED", "NOT_FILLED_CLOSED"]
    assert b["requests"][1]["quantity"] == 61  # yalnızca kalan eksik için
    assert b["timeline"][2]["request"] == "SUPPRESSED_PENDING:B_RECOVER_PRINCIPAL-R1"
    assert not b["summary"]["principal_recovered"]
    conserved(b, 100)


def test_s7_single_lot_min_commission_duplicate_and_max_hold():
    c = run_named("S7_SINGLE_LOT_MIN_COMMISSION_DUPLICATE_MAX_HOLD", "C_HALF_THEN_TRAIL")
    assert any(n.startswith("C_HALF_BELOW_ONE_LOT") for n in c["timeline"][1]["notes"])
    assert c["requests"][0]["reasons"] == ["MAX_HOLD"] and c["requests"][0]["session"] == "2026-09-08"
    assert [r["result"] for r in c["reports"]] == ["APPLIED", "IGNORED_DUPLICATE"]
    assert c["reports"][0]["commission"] == "5.00" and c["summary"]["realized_pnl"] == "-5.10"
    b = run_named("S7_SINGLE_LOT_MIN_COMMISSION_DUPLICATE_MAX_HOLD", "B_RECOVER_PRINCIPAL")
    assert b["summary"]["cumulative_net_sale_proceeds"] == "105.00" and b["summary"]["principal_recovered"]
    assert b["summary"]["realized_pnl"] == "0.00"


# --- Mekanizma testleri -------------------------------------------------------------------------

def test_request_alone_changes_nothing():
    res = simulate(scenario([("2026-09-02", "11.00"), ("2026-09-03", "11.20")]), "A_FULL_AT_TARGET", [])
    assert res["requests"][0]["status"] == "PENDING"
    assert res["summary"]["remaining_quantity"] == 100 and res["summary"]["cumulative_net_sale_proceeds"] == "0.00"
    assert res["timeline"][1]["request"] == "SUPPRESSED_PENDING:A_FULL_AT_TARGET-R1"


def test_same_session_fill_is_lookahead_and_rejected():
    res = simulate(scenario([("2026-09-02", "11.00")]), "A_FULL_AT_TARGET",
                   [fill("X", "A_FULL_AT_TARGET-R1", "2026-09-02", 100, "11.00")])
    assert res["reports"][0]["result"] == "REJECTED_LOOKAHEAD"
    assert res["summary"]["remaining_quantity"] == 100


def test_overfill_conflicting_duplicate_and_unknown_request_rejected():
    bars = [("2026-09-02", "11.00"), ("2026-09-03", "11.00"), ("2026-09-04", "11.00")]
    reps = [fill("X1", "A_FULL_AT_TARGET-R1", "2026-09-03", 60, "11.00", final=False),
            fill("X1", "A_FULL_AT_TARGET-R1", "2026-09-03", 70, "11.00", final=False),
            fill("X2", "A_FULL_AT_TARGET-R1", "2026-09-04", 50, "11.00"),
            fill("X3", "NOPE", "2026-09-04", 10, "11.00"),
            fill("X4", "A_FULL_AT_TARGET-R1", "2026-09-04", 5, "11.00")]
    res = simulate(scenario(bars), "A_FULL_AT_TARGET", reps)
    assert [r["result"] for r in res["reports"]] == ["APPLIED", "REJECTED_CONFLICTING_DUPLICATE", "REJECTED_OVERFILL",
                                                     "REJECTED_UNKNOWN_OR_CLOSED_REQUEST", "APPLIED"]
    assert res["summary"]["sold_quantity"] == 65
    conserved(res, 100)


def test_missing_or_halted_bar_is_not_hold_and_creates_no_request():
    sc = scenario([("2026-09-02", "9.00")])
    sc["bars"].append({"session": "2026-09-03", "close": None})
    sc["bars"].append({"session": "2026-09-04", "close": "9.00", "halted": True})
    res = simulate(sc, "A_FULL_AT_TARGET", [fill("X", "A_FULL_AT_TARGET-R1", "2026-09-07", 0, final=True)])
    evals = {t["session"]: t["evaluation"] for t in res["timeline"]}
    assert evals["2026-09-03"] == "VERI_EKSIK" and evals["2026-09-04"] == "VERI_EKSIK"
    assert [r["session"] for r in res["requests"]] == ["2026-09-02", "2026-09-07"]  # VERI_EKSIK günlerinde istek yok
    assert res["timeline"][3]["request_from_exit_intent"] == "A_FULL_AT_TARGET-R2"  # R1 gerçekleşmeden kapandı, niyet sürer


def test_max_hold_counts_trading_sessions_not_calendar_days():
    params = copy.deepcopy(PARAMS) | {"max_holding_sessions": 2}
    res = simulate(scenario([("2026-09-07", "10.00"), ("2026-09-08", "10.00")], params=params, session="2026-09-04"),
                   "A_FULL_AT_TARGET", [])
    assert res["requests"][0]["session"] == "2026-09-08" and res["requests"][0]["reasons"] == ["MAX_HOLD"]


def test_multiple_reasons_single_request_with_priority():
    params = copy.deepcopy(PARAMS) | {"max_holding_sessions": 1}
    res = simulate(scenario([("2026-09-02", "9.00")], params=params), "B_RECOVER_PRINCIPAL", [])
    assert len(res["requests"]) == 1
    assert res["requests"][0]["reasons"] == ["STOP_LOSS", "MAX_HOLD"] and res["requests"][0]["primary_reason"] == "STOP_LOSS"
    assert res["requests"][0]["quantity"] == 100


def test_c_half_rounds_down_to_whole_lot():
    res = simulate(scenario([("2026-09-02", "11.00")], qty=7), "C_HALF_THEN_TRAIL", [])
    assert res["requests"][0]["quantity"] == 3


def test_no_lookahead_future_bars_do_not_change_past_decisions():
    base = [("2026-09-02", "10.50"), ("2026-09-03", "11.00"), ("2026-09-04", "11.60")]
    short = simulate(scenario(base), "C_HALF_THEN_TRAIL", [])
    longer = simulate(scenario(base + [("2026-09-07", "5.00"), ("2026-09-08", "20.00")]), "C_HALF_THEN_TRAIL", [])
    assert longer["timeline"][:3] == short["timeline"]
    creation = ("request_id", "session", "quantity", "reasons", "reference_close")
    assert {k: longer["requests"][0][k] for k in creation} == {k: short["requests"][0][k] for k in creation}


def test_missing_parameters_are_not_invented():
    params = copy.deepcopy(PARAMS)
    del params["trailing_pct"]
    simulate(scenario([("2026-09-02", "10.00")], params=params), "A_FULL_AT_TARGET", [])  # A için gerekmez
    with pytest.raises(ScenarioError):
        simulate(scenario([("2026-09-02", "10.00")], params=params), "C_HALF_THEN_TRAIL", [])
    params = copy.deepcopy(PARAMS)
    del params["fees"]["min_commission"]
    with pytest.raises(ScenarioError):
        simulate(scenario([("2026-09-02", "10.00")], params=params), "A_FULL_AT_TARGET", [])
    sc = scenario([("2026-09-02", "10.00")])
    del sc["entry"]["fees_basis"]
    with pytest.raises(ScenarioError):
        simulate(sc, "A_FULL_AT_TARGET", [])


def test_inputs_not_mutated():
    sc = copy.deepcopy(BY_NAME["S6_NOT_FILLED_AND_PARTIAL"])
    before = json.dumps(sc, sort_keys=True)
    for run in sc["runs"]:
        simulate(sc, run["policy"], run["executions"])
    assert json.dumps(sc, sort_keys=True) == before


def test_real_input_is_blocked_by_position_review():
    sc = copy.deepcopy(BY_NAME["S1_1000_TL_TO_1100_TL"]) | {"name": "REAL", "data_origin": "GERCEK", "symbol": "ORNEK"}
    assert cli.run_file({"scenarios": [sc]})["scenarios"][0]["blocked"] == "POSITION_REVIEW_GIRDISI_YOK"
    sc["position_review_payload"] = {
        "evaluated_at": "2026-09-29T10:00:00+03:00",
        "positions": [{"user_id": "u", "asset": "ORNEK", "buy_price": 10.0, "buy_date": "2026-09-01T11:00:00+03:00",
                       "quantity": 100, "created_at": "2026-09-01T11:00:00+03:00"}],
        "price_records": [{"symbol": "ORNEK", "session": "2026-09-28", "close": 11.0, "price_basis": "RAW_UNADJUSTED",
                           "retrieved_at": "2026-09-29T09:00:00+03:00"}],
    }
    out = cli.run_file({"scenarios": [sc]})["scenarios"][0]
    assert out["blocked"] == "POSITION_REVIEW_ENGELI:CORPORATE_ACTIONS_UNVERIFIED" and out["runs"] == []


def test_cli_runs_on_sample(tmp_path, capsys):
    out = tmp_path / "out.json"
    src = Path(__file__).resolve().parents[1] / "app/research/position_exit/scenarios_TEMSILI.json"
    assert cli.main([str(src), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert all(not s["blocked"] for s in data["scenarios"]) and "TEMSILI" in data["label"]
    assert "S1_1000_TL_TO_1100_TL" in capsys.readouterr().out


# --- İstek yaşam döngüsü ve masraf sözleşmesi (POSITION-EXIT-1 düzeltmesi) ------------------------

R1, R2 = "C_HALF_THEN_TRAIL-R1", "C_HALF_THEN_TRAIL-R2"
LIFECYCLE_BARS = [("2026-09-02", "10.50"), ("2026-09-03", "11.00"), ("2026-09-04", "9.10"), ("2026-09-07", "9.00")]


def lifecycle_scenario():
    params = copy.deepcopy(PARAMS)
    params["fees"]["min_commission"] = "5"
    return scenario(LIFECYCLE_BARS, fees="5.00", params=params)


def test_s8_event_flow_quantity_cash_and_reasons_each_step():
    res = run_named("S8_PENDING_TARGET_THEN_STOP_CANCEL_LIFECYCLE", "C_HALF_THEN_TRAIL")
    steps = {t["session"]: t["state"] for t in res["timeline"]}
    expected = {  # kalan, aktif istek, açık miktar, net tahsilat, gerçekleşen
        "2026-09-03": (100, R1, 50, "0.00", "0.00"),
        "2026-09-04": (80, R1, 30, "215.00", "14.00"),
        "2026-09-07": (70, R2, 70, "305.00", "3.50"),
        "2026-09-08": (70, R2, 70, "305.00", "3.50"),
        "2026-09-09": (30, R2, 30, "652.00", "-51.50"),
    }
    for day, (rem, active, open_q, net, real) in expected.items():
        st = steps[day]
        assert (st["remaining_quantity"], st["active_request"], st["active_request_open_quantity"],
                st["cumulative_net_sale_proceeds"], st["realized_pnl"]) == (rem, active, open_q, net, real), day
    assert steps["2026-09-04"]["active_request_status"] == "PARTIALLY_FILLED_OPEN_CANCEL_REQUESTED"
    assert steps["2026-09-04"]["exit_intent_reasons"] == ["STOP_LOSS", "TRAILING_STOP"]
    assert [r["result"] for r in res["reports"]] == ["APPLIED", "APPLIED", "APPLIED_CANCEL_CONFIRMED", "IGNORED_DUPLICATE",
                                                     "REJECTED_CONFLICTING_DUPLICATE", "APPLIED", "APPLIED"]
    r1, r2 = res["requests"]
    assert (r1["status"], r1["filled_quantity"]) == ("PARTIALLY_FILLED_CANCELLED", 30)
    assert (r2["quantity"], r2["status"], r2["reasons"]) == (70, "PARTIALLY_FILLED_OPEN", ["STOP_LOSS", "TRAILING_STOP"])
    conserved(res, 100)


def test_cancel_request_is_not_cancel_confirmation_no_overlapping_request():
    reps = [fill("F1", R1, "2026-09-04", 20, "11.00", final=False)]
    res = simulate(lifecycle_scenario(), "C_HALF_THEN_TRAIL", reps)
    assert len(res["requests"]) == 1  # onay yok -> çakışan yeni istek yok
    assert res["requests"][0]["status"] == "PARTIALLY_FILLED_OPEN_CANCEL_REQUESTED"
    assert res["summary"]["exit_intent"]["reasons"] == ["STOP_LOSS", "TRAILING_STOP"]
    assert res["summary"]["remaining_quantity"] == 80


def test_stop_is_not_skipped_while_partial_target_pending_then_full_exit_for_current_remaining():
    reps = [fill("F1", R1, "2026-09-04", 20, "11.00", final=False),
            fill("F2", R1, "2026-09-07", 30, "9.00", final=False)]  # eski istek iptal onayından önce tamamen doldu
    sc = lifecycle_scenario()
    sc["bars"].append({"session": "2026-09-08", "close": "8.90"})
    res = simulate(sc, "C_HALF_THEN_TRAIL", reps)
    assert res["requests"][0]["status"] == "FILLED"
    new = res["requests"][1]
    assert (new["quantity"], new["session"], new["primary_reason"]) == (50, "2026-09-07", "STOP_LOSS")


def test_no_new_request_when_remaining_is_zero():
    params = copy.deepcopy(PARAMS)
    sc = scenario(LIFECYCLE_BARS, params=params)
    reps = [fill("F1", "A_FULL_AT_TARGET-R1", "2026-09-04", 60, "11.00", final=False),
            fill("F2", "A_FULL_AT_TARGET-R1", "2026-09-07", 40, "9.00")]
    res = simulate(sc, "A_FULL_AT_TARGET", reps)
    assert len(res["requests"]) == 1 and res["summary"]["remaining_quantity"] == 0
    assert res["timeline"][2]["request"] == "ACTIVE_FULL_EXIT_REASONS_ADDED:A_FULL_AT_TARGET-R1"


def test_fill_after_cancel_confirmed_rejected_and_unfilled_changes_nothing():
    reps = [{"report_id": "CX", "request_id": R1, "session": "2026-09-04", "type": "CANCEL_CONFIRMED"},
            fill("LATE", R1, "2026-09-07", 10, "9.00")]
    res = simulate(lifecycle_scenario(), "C_HALF_THEN_TRAIL", reps)
    assert [r["result"] for r in res["reports"]] == ["APPLIED_CANCEL_CONFIRMED", "REJECTED_UNKNOWN_OR_CLOSED_REQUEST"]
    assert res["requests"][0]["status"] == "CANCELLED"
    assert res["summary"]["remaining_quantity"] == 100 and res["summary"]["cumulative_net_sale_proceeds"] == "0.00"


def test_min_commission_charged_once_per_request_not_per_partial_fill():
    reps = [fill("F1", R1, "2026-09-04", 20, "11.00", final=False), fill("F2", R1, "2026-09-07", 10, "9.00", final=False)]
    res = simulate(lifecycle_scenario(), "C_HALF_THEN_TRAIL", reps)
    commissions = [r["commission"] for r in res["reports"] if r["result"] == "APPLIED"]
    assert commissions == ["5.00", "0.00"] and res["requests"][0]["commission_charged"] == "5.00"


def test_per_request_commission_tops_up_when_rate_exceeds_minimum():
    params = copy.deepcopy(PARAMS)
    params["fees"] |= {"commission_rate_pct": "1", "min_commission": "5"}
    reps = [fill("F1", "A_FULL_AT_TARGET-R1", "2026-09-03", 40, "11.00", final=False),   # brüt 440 -> 5.00 (asgari)
            fill("F2", "A_FULL_AT_TARGET-R1", "2026-09-04", 60, "11.00")]               # kümülatif 1100 -> 11.00 toplam
    res = simulate(scenario([("2026-09-02", "11.00"), ("2026-09-03", "11.00"), ("2026-09-04", "11.00")], params=params),
                   "A_FULL_AT_TARGET", reps)
    assert [r["commission"] for r in res["reports"]] == ["5.00", "6.00"]


def test_slippage_assumption_not_applied_to_reported_fill_price():
    params = copy.deepcopy(PARAMS)
    params["fees"]["slippage_pct_assumption"] = "2"
    res = simulate(scenario([("2026-09-02", "11.00")], params=params), "A_FULL_AT_TARGET",
                   [fill("F1", "A_FULL_AT_TARGET-R1", "2026-09-03", 100, "11.00")])
    rep = res["reports"][0]
    assert (rep["gross"], rep["commission"], rep["net_proceeds"]) == ("1100.00", "1.10", "1098.90")


def test_actual_commission_in_report_is_used_as_given():
    res = simulate(scenario([("2026-09-02", "11.00")]), "A_FULL_AT_TARGET",
                   [fill("F1", "A_FULL_AT_TARGET-R1", "2026-09-03", 100, "11.00", commission="3.21")])
    assert res["reports"][0]["commission"] == "3.21" and res["reports"][0]["commission_basis"] == "ACTUAL"
