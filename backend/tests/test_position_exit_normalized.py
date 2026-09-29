import copy
import math

import pytest

from app.research.position_exit import normalized as nz
from app.research.position_exit.normalized import Bar, evaluate, reference_episodes, run_policy
from app.services.market_data.trading_calendar import expected_trading_sessions
from datetime import date

SESS = expected_trading_sessions(date(2024, 1, 1), date(2024, 3, 29))  # sentetik ufuk
C = nz.C


def bar(o, c=None, v=1000.0, h=None, low=None):
    c = o if c is None else c
    return Bar(o, h if h is not None else max(o, c) + 0.5, low if low is not None else min(o, c) - 0.5, c, v)


def flat_data(n=None, price=10.0):
    n = n or len(SESS)
    bars = {d: bar(price) for d in SESS[:n]}
    classes = {d: "HOLD" for d in SESS[:n]}
    return bars, classes


def episode(bars, classes, sessions=SESS):
    eps = reference_episodes("X", sessions, bars, classes)["episodes"]
    assert len(eps) == 1 and eps[0]["status"] == "OK", eps
    return eps[0]


def setup_path(closes, opens=None, sell_at=None):
    """Seans 0: AL sinyali; seans 1: giriş (açılış 10). closes: seans1'den itibaren kapanışlar."""
    bars, classes = flat_data()
    classes[SESS[0]] = "BUY"
    for i, c in enumerate(closes):
        d = SESS[1 + i]
        o = (opens or {}).get(i, 10.0 if i == 0 else closes[i - 1])
        bars[d] = bar(o, c)
    if sell_at is not None:
        classes[SESS[1 + sell_at]] = "SELL"
    return bars, classes


def test_fees_applied_once_and_value_identity():
    bars, classes = setup_path([10.0, 10.5, 10.8], sell_at=2)  # SELL kapanış 3. seans -> çıkış 4. seans açılışı
    bars[SESS[4]] = bar(11.0)
    ep = episode(bars, classes)
    r = run_policy("REF", ep, SESS, bars)
    assert r["return"] == pytest.approx((11.0 / 10.0) * (1 - C) / (1 + C) - 1, rel=1e-12)
    assert len(r["sales"]) == 1 and r["remaining_fraction"] == 0
    assert r["final_value"] == pytest.approx(r["cash"])


def test_open_at_end_value_is_cash_plus_remaining_and_loss_reported():
    bars, classes = flat_data(n=6)
    classes[SESS[0]] = "BUY"
    for i, c in enumerate([9.8, 9.6, 9.5, 9.4], start=1):
        bars[SESS[i]] = bar(10.0 if i == 1 else 9.8, c)
    sess = SESS[:5]
    ep = reference_episodes("X", sess, bars, classes)["episodes"][0]
    assert ep["end_kind"] == "OPEN_AT_END"
    r = run_policy("A", ep, sess, bars)
    assert r["open_at_end"] and r["unrealized"] < 0
    q0 = 1 / (10.0 * (1 + C))
    assert r["final_value"] == pytest.approx(r["cash"] + r["remaining_fraction"] * q0 * 9.4)
    assert r["return"] == pytest.approx(q0 * 9.4 - 1)


def test_b_quantity_planned_from_close_not_future_open():
    closes = [10.2, 11.0, 11.0, 11.0]
    b1, c1 = setup_path(closes, opens={2: 11.2})
    b2, c2 = setup_path(closes, opens={2: 9.0})  # sonraki açılış çok farklı
    r1 = run_policy("B", episode(b1, c1), SESS, b1)
    r2 = run_policy("B", episode(b2, c2), SESS, b2)
    q1, q2 = r1["sales"][0]["qty_fraction"], r2["sales"][0]["qty_fraction"]
    assert q1 == pytest.approx(q2)  # miktar yalnızca T kapanışı + masraf varsayımından
    assert r1["recovered"] and not r2["recovered"]  # tahsilat hedefi karşılamazsa geri alınmadı
    assert r2["sales"][0]["net"] < 1


def test_c_partial_once_and_trailing_never_loosens():
    closes = [10.3, 11.0, 11.6, 12.5, 12.0, 11.9, 11.8]
    bars, classes = setup_path(closes)
    r = run_policy("C", episode(bars, classes), SESS, bars)
    targets = [s for s in r["sales"] if s["reasons"] == ["TARGET"]]
    assert len(targets) == 1 and targets[0]["qty_fraction"] == pytest.approx(0.5)
    assert r["exit_reason"] == "TRAILING_STOP"  # 11.8 <= 12.5*0.95 = 11.875
    trail_sale = [s for s in r["sales"] if "TRAILING_STOP" in s["reasons"]][0]
    assert trail_sale["session"] == SESS[1 + 7].isoformat()


def test_common_entries_and_horizons_reference_exit_forces_all():
    bars, classes = setup_path([10.2, 10.4, 10.3], sell_at=2)
    bars[SESS[4]] = bar(10.1)
    ep = episode(bars, classes)
    runs = {p: run_policy(p, ep, SESS, bars) for p in nz.POLICIES}
    for r in runs.values():
        assert r["exit_reason"] == "REFERENCE_EXIT" and r["full_exit_sessions"] == 3
        assert r["return"] == pytest.approx(runs["REF"]["return"])


def test_stop_and_max_hold_and_priority():
    bars, classes = setup_path([10.0, 9.1, 9.0])
    r = run_policy("A", episode(bars, classes), SESS, bars)
    assert r["exit_reason"] == "STOP_LOSS" and r["full_exit_sessions"] == 2
    bars, classes = setup_path([10.0] * 25)
    r = run_policy("C", episode(bars, classes), SESS, bars)
    assert r["exit_reason"] == "MAX_HOLD" and r["full_exit_sessions"] == 20


def test_missing_signal_while_holding_makes_episode_undetermined_and_state_unknown():
    bars, classes = setup_path([10.1, 10.2, 10.3])
    classes[SESS[2]] = None
    classes[SESS[5]] = "BUY"  # bilinmeyen durumda AL -> giriş SAYILMAZ
    out = reference_episodes("X", SESS, bars, classes)
    assert [e["status"] for e in out["episodes"]] == ["UNDETERMINED"]
    assert out["episodes"][0]["reason"] == "SIGNAL_MISSING_WHILE_HOLDING"
    assert out["unknown_state_buy_days"] == [f"X:{SESS[5].isoformat()}"]


def test_resync_after_observed_sell_with_executable_next_open():
    bars, classes = flat_data()
    classes[SESS[1]] = None           # düzken eksik -> BİLİNMİYOR
    classes[SESS[3]] = "SELL"         # SESS[4] açılışı geçerli -> DÜZ
    classes[SESS[6]] = "BUY"          # artık giriş
    eps = reference_episodes("X", SESS, bars, classes)["episodes"]
    assert eps[0]["signal_session"] == SESS[6].isoformat() and eps[0]["status"] == "OK"


def test_missing_next_open_not_skipped_to_next_bar():
    bars, classes = flat_data()
    classes[SESS[0]] = "BUY"
    bars[SESS[1]] = bar(10.0, v=0.0)  # hacim 0 -> dolum koşulu yok
    out = reference_episodes("X", SESS, bars, classes)
    assert out["episodes"][0]["reason"] == "ENTRY_EXECUTION_UNDETERMINED"
    del bars[SESS[1]]
    out = reference_episodes("X", SESS, bars, classes)
    assert out["episodes"][0]["reason"] == "ENTRY_EXECUTION_UNDETERMINED"


def test_policy_execution_undetermined_excludes_episode_for_all_and_is_listed():
    bars, classes = setup_path([10.2, 11.0, 11.2, 11.3])
    bars[SESS[3]] = bar(11.0, 11.2, v=0.0)  # A'nın hedef çıkışı SESS[3] açılışında dolamaz
    res = evaluate({"X": (bars, classes)}, SESS)
    y = res["years"]["2024"]
    assert y["evaluable_common_episodes"] == 0 and y["policy_execution_undetermined_episodes"] == 1
    assert {x["policy"] for x in res["excluded"]} >= {"A", "B", "C"}


def test_inputs_not_mutated_and_no_silent_fill():
    bars, classes = setup_path([10.2, 11.0, 11.2, 11.3])
    b0, c0 = copy.deepcopy(bars), copy.deepcopy(classes)
    evaluate({"X": (bars, classes)}, SESS)
    assert bars == b0 and classes == c0
