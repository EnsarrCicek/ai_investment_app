import copy
import json
import math

import pytest

from app.services.portfolio import position_review as pr

EVAL = "2026-09-28T12:00:00+03:00"  # Pazartesi seans içi -> beklenen seans 2026-09-25 (Cuma)
SESSION = "2026-09-25"


def lot(asset, qty, price, buy="2026-09-01T10:30:00+03:00"):
    return {"user_id": "u", "asset": asset, "buy_price": price, "buy_date": buy, "quantity": qty,
            "created_at": "2026-09-01T10:31:00+03:00"}


def price(symbol, close, session=SESSION, basis="RAW_UNADJUSTED", retrieved="2026-09-25T19:00:00+03:00", **extra):
    rec = {"symbol": symbol, "session": session, "close": close, "price_basis": basis, "source": "TEST", **extra}
    if retrieved is not None:
        rec["retrieved_at"] = retrieved
    return rec


def clean_check(frm="2026-01-01", thru="2026-09-27"):
    return {"checked_from": frm, "checked_through": thru, "split_or_bonus_dates": [], "source": "TEST"}


def payload(positions, prices, checks=None, limits=None, evaluated_at=EVAL):
    return {"evaluated_at": evaluated_at, "positions": positions, "price_records": prices,
            "corporate_action_checks": checks if checks is not None else {}, "limits": limits}


def rows(report):
    return {r["symbol"]: r for r in report["positions"]}


def test_valuation_session_uses_last_completed_expected_session():
    from datetime import datetime
    assert pr.valuation_session(datetime.fromisoformat("2026-09-28T12:00:00+03:00")).isoformat() == "2026-09-25"
    assert pr.valuation_session(datetime.fromisoformat("2026-09-28T18:29:00+03:00")).isoformat() == "2026-09-25"
    assert pr.valuation_session(datetime.fromisoformat("2026-09-28T18:30:00+03:00")).isoformat() == "2026-09-28"


def test_valued_position_pnl_and_complete_weights():
    rep = pr.review(payload([lot("AAA", 10, 100.0), lot("AAA", 10, 120.0), lot("BBB", 5, 40.0)],
                            [price("AAA", 99.0), price("BBB", 44.0)],
                            {"AAA": clean_check(), "BBB": clean_check()}))
    a, b = rows(rep)["AAA"], rows(rep)["BBB"]
    assert a["status"] == pr.VALUED and a["quantity"] == 20 and a["total_cost"] == 2200.0
    assert a["market_value"] == 1980.0 and a["unrealized_pnl"] == -220.0 and a["unrealized_pnl_pct"] == -10.0
    assert a["price_used"]["session"] == SESSION and a["price_used"]["retrieved_at"].startswith("2026-09-25T19:00")
    assert a["price_basis_status"] == "BEYANA_GORE_UYUMLU" and a["price_basis_evidence"] == pr.DECLARATION
    assert rep["open_stock_concentration"]["status"] == pr.WEIGHTS_COMPLETE
    assert a["weight_in_open_stock_positions_pct"] + b["weight_in_open_stock_positions_pct"] == pytest.approx(100)
    assert a["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_NOT_DEFINED


def test_incomplete_bar_captured_before_finalization_is_not_used():
    rep = pr.review(payload([lot("AAA", 1, 10.0)],
                            [price("AAA", 11.0, retrieved="2026-09-25T17:45:00+03:00"), price("AAA", 10.5, session="2026-09-24", retrieved="2026-09-24T19:00:00+03:00")],
                            {"AAA": clean_check()}))
    a = rows(rep)["AAA"]
    assert a["status"] == pr.INCOMPLETE_BAR and a["market_value"] is None and a["unrealized_pnl"] is None
    assert a["last_known_price_stale"]["session"] == "2026-09-24"
    assert a["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_NOT_DEFINED


def test_intraday_bar_of_evaluation_day_is_ignored_and_stale_not_used():
    rep = pr.review(payload([lot("AAA", 1, 10.0)],
                            [price("AAA", 12.0, session="2026-09-28", retrieved="2026-09-28T11:50:00+03:00"),
                             price("AAA", 10.5, session="2026-09-24", retrieved="2026-09-24T19:00:00+03:00")],
                            {"AAA": clean_check()}, limits={"max_loss_pct": 5}))
    a = rows(rep)["AAA"]
    assert a["status"] == pr.STALE_PRICE and a["price_used"] is None and a["market_value"] is None
    assert a["last_known_price_stale"]["close"] == 10.5
    assert any(n.startswith("FUTURE_OR_INCOMPLETE_SESSION_IGNORED:2026-09-28") for n in a["price_notes"])
    assert a["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_NOT_EVALUATED


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -3.0, None, "12"])
def test_invalid_price_is_not_counted_as_zero(bad):
    rep = pr.review(payload([lot("AAA", 1, 10.0)], [price("AAA", bad)], {"AAA": clean_check()}))
    a = rows(rep)["AAA"]
    assert a["status"] == pr.INVALID_PRICE and a["market_value"] is None
    assert rep["open_stock_concentration"]["known_market_value_subtotal"] == 0.0
    assert rep["open_stock_concentration"]["total_open_stock_market_value"] is None


def test_missing_price():
    a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [])))["AAA"]
    assert a["status"] == pr.MISSING_PRICE and a["last_known_price_stale"] is None


def test_adjusted_or_undeclared_basis_is_unverified():
    for basis in ("ADJUSTED_SPLIT_DIVIDEND", None):
        a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [price("AAA", 9.0, basis=basis)], {"AAA": clean_check()})))["AAA"]
        assert a["status"] == pr.PRICE_BASIS_UNVERIFIED and a["unrealized_pnl"] is None
        assert a["price_used"]["close"] == 9.0  # gösterilir, kâr/zarar üretilmez


def test_split_or_bonus_in_holding_period_is_mismatch():
    check = clean_check() | {"split_or_bonus_dates": ["2026-09-10"]}
    a = rows(pr.review(payload([lot("AAA", 100, 50.0)], [price("AAA", 25.0)], {"AAA": check},
                               limits={"max_loss_pct": 10})))["AAA"]
    assert a["status"] == pr.CORPORATE_ACTION_IN_HOLDING_PERIOD and a["price_basis_status"] == "BEYANA_GORE_UYUMSUZ"
    assert a["unrealized_pnl_pct"] is None
    assert a["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_NOT_EVALUATED


def test_missing_or_short_corporate_action_check_is_unverified():
    for checks in ({}, {"AAA": clean_check(frm="2026-09-05")}, {"AAA": clean_check(thru="2026-09-20")}):
        a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [price("AAA", 9.0)], checks)))["AAA"]
        assert a["status"] == pr.CORPORATE_ACTIONS_UNVERIFIED and a["unrealized_pnl"] is None


def test_missing_position_price_makes_weights_undetermined_without_renormalizing():
    rep = pr.review(payload([lot("AAA", 10, 10.0), lot("BBB", 10, 10.0), lot("CCC", 10, 10.0)],
                            [price("AAA", 10.0), price("BBB", 30.0)],
                            {"AAA": clean_check(), "BBB": clean_check(), "CCC": clean_check()},
                            limits={"max_weight_pct": 50}))
    conc = rep["open_stock_concentration"]
    assert conc["status"] == pr.WEIGHTS_UNDETERMINED and conc["herfindahl_index"] is None
    assert conc["known_market_value_subtotal"] == 400.0 and conc["total_open_stock_market_value"] is None
    for r in rep["positions"]:
        assert r["weight_in_open_stock_positions_pct"] is None
        assert r["limit_checks"]["max_weight_pct"]["status"] == pr.LIMIT_NOT_EVALUATED


def test_limit_boundary_is_within_and_above_is_exceeded():
    checks = {"AAA": clean_check(), "BBB": clean_check()}
    rep = pr.review(payload([lot("AAA", 1, 100.0), lot("BBB", 1, 100.0)], [price("AAA", 92.0), price("BBB", 108.0)],
                            checks, limits={"max_loss_pct": 8, "max_weight_pct": 54}))
    a, b = rows(rep)["AAA"], rows(rep)["BBB"]
    assert a["limit_checks"]["max_loss_pct"] == {"limit": 8.0, "loss_pct_vs_cost": 8.0, "status": pr.LIMIT_WITHIN}
    assert b["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_WITHIN
    assert b["weight_in_open_stock_positions_pct"] == 54.0
    assert b["limit_checks"]["max_weight_pct"]["status"] == pr.LIMIT_WITHIN
    rep2 = pr.review(payload([lot("AAA", 1, 100.0), lot("BBB", 1, 100.0)], [price("AAA", 91.99), price("BBB", 108.0)],
                             checks, limits={"max_loss_pct": 8, "max_weight_pct": 53.99}))
    assert rows(rep2)["AAA"]["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_EXCEEDED
    assert rows(rep2)["BBB"]["limit_checks"]["max_weight_pct"]["status"] == pr.LIMIT_EXCEEDED


def test_limits_not_defined_and_invalid_limits():
    a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [price("AAA", 9.0)], {"AAA": clean_check()})))["AAA"]
    assert {c["status"] for c in a["limit_checks"].values()} == {pr.LIMIT_NOT_DEFINED}
    for bad in (0, -1, 101, float("nan"), True):
        with pytest.raises(pr.InputError):
            pr.review(payload([], [], limits={"max_loss_pct": bad}))


def test_unsupported_calendar_year_is_not_guessed():
    rep = pr.review(payload([lot("AAA", 1, 10.0)], [price("AAA", 9.0, session="2027-01-04")],
                            evaluated_at="2027-01-05T19:00:00+03:00"))
    assert rep["calendar_status"] == pr.CALENDAR_UNSUPPORTED and rep["expected_valuation_session"] is None
    assert rows(rep)["AAA"]["status"] == pr.CALENDAR_UNSUPPORTED


def test_naive_evaluation_time_rejected():
    with pytest.raises(pr.InputError):
        pr.review(payload([], [], evaluated_at="2026-09-28T12:00:00"))


def test_invalid_position_and_conflicting_prices_and_buy_after_session():
    rep = pr.review(payload([lot("AAA", 0, 10.0), lot("BBB", 1, 10.0), lot("CCC", 1, 10.0, buy="2026-09-28T10:30:00+03:00")],
                            [price("BBB", 9.0), price("BBB", 9.5), price("CCC", 9.0)],
                            {"BBB": clean_check(), "CCC": clean_check()}))
    r = rows(rep)
    assert r["AAA"]["status"] == pr.INVALID_POSITION
    assert r["BBB"]["status"] == pr.CONFLICTING_PRICE_RECORDS
    assert r["CCC"]["status"] == pr.BUY_AFTER_VALUATION_SESSION and r["CCC"]["unrealized_pnl"] is None


def test_inputs_are_not_mutated():
    p = payload([lot("AAA", 10, 100.0), lot("BBB", 5, 40.0)],
                [price("AAA", 99.0), price("BBB", float("nan")), price("AAA", 98.0, session="2026-09-24")],
                {"AAA": clean_check()}, limits={"max_loss_pct": 5, "max_weight_pct": 30})
    before = copy.deepcopy(p)
    pr.review(p)
    assert json.dumps(p, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_cli_runs_on_local_json(tmp_path, capsys):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(payload([lot("AAA", 1, 10.0)], [price("AAA", 9.0)], {"AAA": clean_check()}) | {"label": "TEMSILI"}),
                   encoding="utf-8")
    out = tmp_path / "out.json"
    assert pr.main([str(src), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["input_label"] == "TEMSILI" and result["positions"][0]["status"] == pr.VALUED
    assert pr.main([str(src), "--bad"]) == 2


def test_midnight_daily_label_in_source_timestamp_does_not_reject_completed_session():
    rec = price("AAA", 9.0, retrieved=None, source_timestamp="2026-09-25T00:00:00+03:00")
    a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [rec], {"AAA": clean_check()})))["AAA"]
    assert a["status"] == pr.VALUED and a["price_used"]["close"] == 9.0
    assert a["price_used"]["bar_completion_evidence"] == "YALNIZCA_TAKVIM_SOZLESMESI_ALINMA_ZAMANI_YOK"
    assert "SOURCE_TIMESTAMP_MEANING_UNKNOWN_NOT_USED:2026-09-25" in a["price_notes"]
    assert "RETRIEVAL_TIME_MISSING_COMPLETION_BY_CALENDAR_ONLY:2026-09-25" in a["price_notes"]


def test_truly_incomplete_session_by_evaluation_time_not_used_even_with_late_retrieval_label():
    # 25.09 18:10'da değerlendirme: beklenen seans 24.09; 25.09 barı henüz kesinleşmedi.
    rec = price("AAA", 9.0, source_timestamp="2026-09-25T00:00:00+03:00", retrieved="2026-09-25T18:05:00+03:00")
    a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [rec], {"AAA": clean_check()},
                               evaluated_at="2026-09-25T18:10:00+03:00")))["AAA"]
    assert a["expected_session"] == "2026-09-24" and a["status"] == pr.MISSING_PRICE and a["market_value"] is None


def test_observation_after_evaluation_time_not_used():
    for field in ("retrieved_at", "source_updated_at"):
        rec = price("AAA", 9.0, retrieved=None) | {field: "2026-09-28T12:00:01+03:00"}
        a = rows(pr.review(payload([lot("AAA", 1, 10.0)], [rec, price("AAA", 9.5, session="2026-09-24", retrieved="2026-09-24T19:00:00+03:00")],
                                   {"AAA": clean_check()}, limits={"max_loss_pct": 5})))["AAA"]
        assert a["status"] == pr.OBSERVED_AFTER_EVALUATION and a["market_value"] is None
        assert a["limit_checks"]["max_loss_pct"]["status"] == pr.LIMIT_NOT_EVALUATED


def test_corporate_action_coverage_must_span_earliest_lot():
    lots = [lot("AAA", 1, 10.0, buy="2026-03-02T11:00:00+03:00"), lot("AAA", 1, 10.0, buy="2026-09-01T11:00:00+03:00")]
    a = rows(pr.review(payload(lots, [price("AAA", 9.0)], {"AAA": clean_check(frm="2026-06-01")})))["AAA"]
    assert a["status"] == pr.CORPORATE_ACTIONS_UNVERIFIED and a["unrealized_pnl"] is None
    assert a["corporate_action_check"]["required_from"] == "2026-03-02"
    assert a["corporate_action_check"]["evidence"] == pr.DECLARATION
