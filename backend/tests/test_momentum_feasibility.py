"""Momentum fizibilite denetimi (yalnız araştırma): Pareto, doğrulama maliyeti, gecikme simülasyonu, veri güvenliği."""

import random
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_calibration import experiment as r1x
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.services.momentum.early_momentum_engine import compute_features, confirm_level
from tests.test_momentum_engine import DAY, PROV, build, noise


def _pt(r, fpr, lead, p=0.1):
    return {"recall": r, "false_positive_rate": fpr, "lead_fraction_median": lead, "precision": p}


def test_dominated_points_removed_and_deterministic():
    pts = [_pt(0.6, 0.3, 0.5), _pt(0.5, 0.4, 0.6), _pt(0.7, 0.5, 0.4), _pt(0.6, 0.3, 0.5), _pt(0.2, 0.1, 0.7)]
    keep = fr.pareto_mask(pts)
    assert list(keep) == [True, False, True, True, True]  # (0.5,0.4,0.6) birinci tarafından baskın
    assert list(fr.pareto_mask(list(pts))) == list(keep)
    assert fr.pareto_mask([_pt(0.5, None, 0.5), _pt(0.5, 0.2, 0.5)]).tolist() == [False, True]  # eksik = en kötü


def test_best_under_constraints():
    pts = [_pt(0.6, 0.3, 0.5), _pt(0.4, 0.2, 0.6), _pt(0.3, 0.1, 0.35)]
    assert fr.best_under(pts, "recall", True, {"false_positive_rate": ("<=", 0.25)})["recall"] == 0.4
    assert fr.best_under(pts, "false_positive_rate", False, {"lead_fraction_median": ("<=", 0.40)})[
        "false_positive_rate"] == 0.1
    assert fr.best_under(pts, "recall", True, {"false_positive_rate": ("<=", 0.05)}) is None


@pytest.mark.parametrize("k,n", [(1, 1), (2, 3), (2, 2), (3, 3)])
def test_confirmation_matches_production_confirm_level(k, n):
    rng = random.Random(k * 10 + n)
    raw = np.array([rng.random() < 0.5 for _ in range(60)])
    seg_start = np.array([0] * 25 + [25] * 35)  # iki seans
    got = fr.confirm(raw, seg_start, k, n)
    cfg = ma.MomentumAlertConfig(confirm_k=k, confirm_n=n)
    for i in range(60):
        seq = [ma.LEVEL_WATCH if x else ma.LEVEL_NONE for x in raw[seg_start[i]:i + 1]]
        padded = [ma.LEVEL_NONE] * max(0, n - len(seq)) + seq
        assert got[i] == (confirm_level(padded, cfg) == ma.LEVEL_WATCH), i


def test_confirmation_cost_delays_first_alert():
    raw = np.array([False, True, True, True, True, False])
    seg = np.zeros(6, dtype=int)
    firsts = {f"{k}/{n}": int(np.flatnonzero(fr.confirm(raw, seg, k, n))[0]) for k, n in ((1, 1), (2, 3), (3, 3))}
    assert firsts == {"1/1": 1, "2/3": 2, "3/3": 3}


def _labels(t_ns, entry, mfe, events, high_ns, high, low):
    n = len(t_ns)
    return fr.LabelArrays(np.array(t_ns, dtype=np.int64), np.array(entry, float), np.array(mfe, float),
                          np.zeros(n), np.ones(n, bool), np.array(events), np.array(high_ns, dtype=np.int64),
                          np.array(high, float), np.array(low, float))


def test_metrics_event_ordering_alert_after_peak_not_caught():
    # seans 0: olay, tepe t=20; ilk alarm t=10 (yakalandı). seans 1: olay, tepe t=5; alarm t=10 (tepeden sonra).
    # seans 2: olaysız, alarm (yanlış pozitif). seans 3: olaysız, alarm yok.
    sess = np.array([0, 0, 1, 1, 2, 3])
    final = np.array([True, True, False, True, True, False])
    lab = _labels([10, 15, 0, 10, 10, 10], [101, 102, 100, 110, 100, 100], [0.05, 0.04, 0, 0.01, 0.0, 0],
                  [True, True, False, False], [20, 5, 0, 0], [110, 112, 100, 100], [100, 100, 100, 100])
    m = fr.metrics(final, sess, lab, 0.03)
    assert m["alert_sessions"] == 3 and m["events"] == 2 and m["caught_events"] == 1
    assert m["recall"] == 0.5 and m["false_positive_rate"] == 0.5
    assert m["precision"] == pytest.approx(1 / 3)
    assert m["lead_fraction_median"] == pytest.approx(0.1)


def test_delay_simulation_is_time_shift_without_lookahead():
    """d dk gecikme @T == 15 dk gecikme @T+(15−d): aynı görünür barlar; T'den sonraki barlar hiçbirinde yok."""
    bars = build(noise(40, 3) + [0.004] * 6 + noise(10, 4))
    config15 = r1x.config_for("F1", delay=15)
    for d in (0, 5, 10):
        cfg = r1x.config_for("F1", delay=d)
        for minute in (20, 35, 50):
            t = datetime.combine(DAY, datetime.min.time(), tzinfo=ISTANBUL_TZ) + timedelta(hours=10, minutes=minute
                                                                                         + 5 * 30)
            a = compute_features("SYN", bars, PROV, t, cfg)
            b = compute_features("SYN", bars, PROV, t + timedelta(minutes=15 - d), config15)
            assert a.status == b.status == ma.STATUS_OK
            assert a.components == b.components and a.persistent == b.persistent
            # gelecek barlar (T'den sonra başlayan) bozulsa bile sonuç değişmez
            future = bars.copy()
            future.loc[future.index > t, "Close"] *= 1.5
            assert compute_features("SYN", future, PROV, t, cfg).components == a.components


def test_selection_loader_never_reads_untouched_or_final():
    sel_days, final_days = fx.selection_scope()
    requested = []
    fake = [{"symbol": "AKBNK", "day": sel_days[0]}, {"symbol": "AKBNK", "day": sorted(final_days)[0]},
            {"symbol": "GARAN", "day": sel_days[-1]}]

    def loader(name):
        requested.append(name)
        return fake

    rows = fx.load_selection_rows(loader)
    assert requested == ["merged_ref_d15.pkl"]
    assert all(r["day"] not in final_days for r in rows) and len(rows) == 2
    bad = [{"symbol": "ENKAI", "day": sel_days[0]}]  # Round 2 dokunulmamış varlık
    with pytest.raises(AssertionError):
        fx.load_selection_rows(lambda name: bad)
    assert not (fx.RUNS / "final.json").exists()


def test_grid_is_deterministic_and_has_no_ktlev():
    a = list(fx.grid(fx.WATCH_GRID))
    assert a == list(fx.grid(fx.WATCH_GRID)) and len(a) == 6 * 2 * 4 * 4 * 4 * 2 * 4
    assert "KTLEV" not in fx.ds2.REFERENCE_ASSETS
