"""Dondurulmuş momentum WATCH adayı + dokunulmamış final denetimi (yalnız araştırma)."""

import json

import numpy as np
import pytest

from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_final import candidate as cd
from app.research.momentum_final import experiment as mf


def _fold(i, thr, feat="rel_ret_z_3", passes=True, q=99.3):
    return {"fold": i, "feasible_on_train": True, "validate_passes_target": passes,
            "config": {"feature": feat, "quantile": q, "threshold": thr}}


FOLDS = [_fold(1, 5.002456964284509), _fold(2, 5.409213934790832, q=99.5), _fold(3, 5.094139728812382)]
SEL = {"assets": 50, "sessions": 2100, "folds": 3, "folds_passing": 3}


def _cand():
    return cd.build_candidate(FOLDS, SEL, "r1sha", "extsha")


def test_aggregation_is_median_of_fold_thresholds_and_order_independent():
    assert cd.aggregate_threshold(FOLDS) == ("rel_ret_z_3", 5.094139728812382)
    assert cd.aggregate_threshold(list(reversed(FOLDS))) == ("rel_ret_z_3", 5.094139728812382)


@pytest.mark.parametrize("folds", [
    FOLDS[:2],                                                    # walk-forward eksik
    [*FOLDS[:2], _fold(3, 5.0, feat="price_z")],                  # farklı aile
    [*FOLDS[:2], _fold(3, 5.0, passes=False)],                    # görülmemiş blokta geçmedi
    [*FOLDS[:2], {"fold": 3, "feasible_on_train": True, "validate_passes_target": True,
                  "config": {"price": 0.5, "confirm": (1, 1)}}],   # tek öznitelik değil
])
def test_aggregation_refuses_inconsistent_walk_forward(folds):
    with pytest.raises(cd.FrozenCandidateError):
        cd.aggregate_threshold(folds)


def test_candidate_serialization_deterministic_and_sha_stable():
    a, b = _cand(), _cand()
    assert cd.canonical_json(a) == cd.canonical_json(b)
    assert cd.canonical_json(a) == cd.canonical_json(dict(reversed(list(a.items()))))
    assert cd.sha256_of(a) == cd.sha256_of(b) and len(cd.sha256_of(a)) == 64
    assert cd.sha256_of({**a, "threshold": a["threshold"] + 1e-12}) != cd.sha256_of(a)
    with pytest.raises(ValueError):
        cd.canonical_json({"x": float("nan")})
    assert a["confirmation"] == [1, 1] and a["provider_delay_minutes"] == 15 and a["level"] == "WATCH"


def test_freeze_cannot_be_modified_afterwards(tmp_path):
    path = tmp_path / "frozen.json"
    m = cd.freeze(path, _cand())
    assert cd.freeze(path, _cand())["sha256"] == m["sha256"]  # aynı aday: idempotent
    with pytest.raises(cd.FrozenCandidateError):
        cd.freeze(path, {**_cand(), "threshold": 4.0})
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["candidate"]["threshold"] = 4.0  # elle kurcalama
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(cd.FrozenCandidateError, match="SHA"):
        cd.load_frozen(path)


def test_cannot_evaluate_final_before_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "MANIFEST", tmp_path / "none.json")
    monkeypatch.setattr(mf, "FINAL_LOCK", tmp_path / "lock")
    monkeypatch.setattr(mf, "FINAL_RESULT", tmp_path / "result.json")
    opened = []
    monkeypatch.setattr(mf.r2, "load_pkl", lambda name: opened.append(name))
    with pytest.raises(cd.FrozenCandidateError):
        mf.final_stage()
    assert opened == [] and not (tmp_path / "lock").exists()


def test_final_is_one_shot(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "FINAL_LOCK", tmp_path / "lock")
    monkeypatch.setattr(mf, "FINAL_RESULT", tmp_path / "result.json")
    (tmp_path / "lock").write_text("{}")
    opened = []
    monkeypatch.setattr(mf.r2, "load_pkl", lambda name: opened.append(name))
    with pytest.raises(SystemExit):
        mf.final_stage()
    assert opened == []


def test_freeze_uses_selection_only_and_guard_blocks_untouched():
    sel_days, final_days = fx.selection_scope()
    asked = []
    rows = fx.load_selection_rows(lambda n: asked.append(n) or [{"symbol": "AKBNK", "day": sel_days[0]}])
    assert asked == ["merged_ref_d15.pkl"] and rows
    for name in ("merged_new_d15.pkl", "ext_new_d15.pkl", "r1_new_F1_d15.pkl"):
        with pytest.raises(RuntimeError, match="Untouched final is forbidden"):
            fx.guarded_load(name, lambda n: pytest.fail("açılmamalı"))
    with pytest.raises(RuntimeError):
        fx.load_selection_rows(lambda n: [{"symbol": "ENKAI", "day": sel_days[0]}])
    assert not set(fx.ds2.REFERENCE_ASSETS) & set(fx.ds2.UNTOUCHED_ASSETS)
    assert max(sel_days) < min(final_days)


class _StubPanel:
    def __init__(self):
        self.labels = {}
        self.built = []

    def build_labels(self, d):
        self.built.append(d)
        raise RuntimeError("stop")


def test_final_evaluation_uses_d15_only():
    p = _StubPanel()
    with pytest.raises(RuntimeError, match="stop"):
        mf.evaluate_final(p, _cand())
    assert p.built == [15]
    with pytest.raises(AssertionError):
        mf.evaluate_final(_StubPanel(), {**_cand(), "provider_delay_minutes": 0})


def test_pass_criteria_deterministic_and_separate():
    m = {"false_positive_rate": 0.2, "recall": 0.45, "lead_fraction_median": 0.51, "precision": 0.12}
    t = cd.pass_table(m, base_rate=0.07)
    assert {k: v["result"] for k, v in t.items()} == {"false_positive_rate": "PASS", "recall": "PASS",
                                                       "lead_fraction_median": "FAIL", "precision_vs_base": "PASS"}
    assert cd.verdict(t) == "MOMENTUM UNTOUCHED FINAL: FAIL"
    t2 = cd.pass_table({**m, "lead_fraction_median": 0.50}, 0.07)
    assert cd.verdict(t2) == "MOMENTUM UNTOUCHED FINAL: PASS" and cd.pass_table(m, 0.07) == t
    assert cd.pass_table({**m, "precision": None}, 0.07)["precision_vs_base"]["result"] == "FAIL"
    assert cd.pass_table({**m, "recall": None}, 0.07)["recall"]["result"] == "FAIL"


def test_wilson_interval():
    lo, hi = cd.wilson(10, 50)
    assert lo == pytest.approx(0.1124, abs=1e-3) and hi == pytest.approx(0.3304, abs=1e-3)
    assert cd.wilson(0, 10)[0] == 0.0 and cd.wilson(10, 10)[1] == pytest.approx(1.0)
    assert cd.wilson(0, 0) is None


def test_ktlev_excluded_from_verdict():
    assert "KTLEV" not in fx.ds2.UNTOUCHED_ASSETS and "KTLEV" not in fx.ds2.REFERENCE_ASSETS
    t = cd.pass_table({"false_positive_rate": 0.1, "recall": 0.5, "lead_fraction_median": 0.3, "precision": 0.2},
                      0.07)
    assert cd.verdict(t) == cd.verdict({**t})  # karar yalnız WATCH tablosundan; KTLEV girdisi yok


def test_retry_only_after_abort_before_metrics(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    monkeypatch.setattr(mf, "FINAL_LOCK", lock)
    assert mf.prior_attempts("s") == []
    lock.write_text(json.dumps({"attempts": [{"sha256": "s", "status": "aborted_before_metrics"}]}))
    assert len(mf.prior_attempts("s")) == 1
    with pytest.raises(SystemExit):
        mf.prior_attempts("other")  # farklı aday
    for status in ("running", "completed"):
        lock.write_text(json.dumps({"attempts": [{"sha256": "s", "status": status}]}))
        with pytest.raises(SystemExit):
            mf.prior_attempts("s")
    lock.write_text("{}")
    with pytest.raises(SystemExit):
        mf.prior_attempts("s")


def test_label_gap_matches_reference_definition():
    import pandas as pd
    from datetime import date, datetime, timedelta
    from app.engines.technical.session_timing import ISTANBUL_TZ
    from app.research.momentum_calibration.labels import label_at, labels_for_session
    d = date(2026, 10, 1)
    t0 = datetime(2026, 10, 1, 10, 0, tzinfo=ISTANBUL_TZ)
    idx = [t0 + timedelta(minutes=5 * i) for i in range(4)] + [t0 + timedelta(minutes=120 + 5 * i) for i in range(4)]
    bars = pd.DataFrame({"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.1, "Volume": 1}, index=pd.DatetimeIndex(idx))
    t = t0 + timedelta(minutes=50)  # sonraki bar 70 dk sonra (≥60 dk boşluk)
    _, (got,) = labels_for_session(bars, d, [t])
    ref = label_at(bars[bars.index.date == d], t)
    assert np.isnan(got.mfe_60) and np.isnan(ref.mfe_60)
    assert got.entry == ref.entry and got.mfe_close == pytest.approx(ref.mfe_close)


def test_candidate_alert_rule():
    class P:
        ok = np.array([True, True, True, False])
        rel_ret_z_3 = np.array([5.2, 5.0, np.nan, 9.0])
    got = mf.candidate_alerts(P, {**_cand(), "threshold": 5.094})
    assert got.tolist() == [True, False, False, False]
