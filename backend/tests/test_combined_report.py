import pytest

from app.research.position_exit.combined_report import account

Q0 = 1 / (10.0 * 1.001)


def run(cash, frac, last_close, sales):
    fv = cash + frac * Q0 * last_close
    return {"cash": cash, "final_value": fv, "return": fv - 1, "remaining_fraction": frac, "sales": sales, "exit_reason": "X"}


def test_open_episode_equity_split_and_common_valuation_close():
    sale = {"net": 0.5 * Q0 * 11.0 * 0.999}
    ep = {"id": "ABC:1", "entry_price": 10.0, "end_kind": "OPEN_AT_END", "end_session": "2025-07-11",
          "runs": {"REF": run(0.0, 1.0, 12.0, []), "C": run(sale["net"], 0.5, 12.0, [sale])}}
    closes = {"2025-07-11": 12.0}
    ref, c = account(ep, "REF", closes), account(ep, "C", closes)
    assert ref["valuation"] == c["valuation"] == ("close", "2025-07-11")
    assert abs(c["realized_pnl"] - (sale["net"] - 0.5)) < 1e-12  # satılan yarının maliyeti 0,5 birim
    assert abs(c["unrealized_pnl"] - (0.5 * Q0 * 12.0 - 0.5)) < 1e-12  # kapanış satışı komisyonu eklenmez
    assert abs(c["realized_pnl"] + c["unrealized_pnl"] - c["total_change"]) < 1e-12 and ref["realized_pnl"] == 0.0


def test_recorded_value_must_match_official_close():
    ep = {"id": "ABC:1", "entry_price": 10.0, "end_kind": "OPEN_AT_END", "end_session": "2025-07-11",
          "runs": {"REF": run(0.0, 1.0, 12.0, [])}}
    with pytest.raises(ValueError):
        account(ep, "REF", {"2025-07-11": 11.0})
