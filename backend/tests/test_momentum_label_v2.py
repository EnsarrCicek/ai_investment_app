"""MOMENTUM_EVENT_LABEL_V2 (yalnız araştırma): aynı swing üzerinde olay/tepe/lead, alarm↔olay eşlemesi, manifest."""

import json

import numpy as np
import pandas as pd
import pytest

from app.research.momentum_calibration.labels import session_outcome
from app.research.momentum_feasibility import audit as au
from app.research.momentum_final import experiment as mf
from app.research.momentum_final import postmortem as pm
from app.research.momentum_label_v2 import experiment as lx
from app.research.momentum_label_v2 import labels as lv

T0 = pd.Timestamp("2026-08-03 09:55", tz="Europe/Istanbul").value  # seansın ilk bar başlangıcı


def bar_ns(k: int) -> int:
    return T0 + k * lv.BAR_NS


def starts(n: int) -> np.ndarray:
    return np.array([bar_ns(k) for k in range(n)], dtype=np.int64)


def session(highs, lows):
    return lv.session_events(starts(len(highs)), np.array(highs, float), np.array(lows, float))


# Açılışta tepe (A: 100→103, %3), düşüş, sonra ayrı %10 swing (B: dip bar 4 = 95, tepe bar 7 = 104.5)
H_AB = [103, 101, 99, 97, 96, 99, 102, 104.5, 101]
L_AB = [100, 99, 97, 96, 95, 96, 99, 101, 99]


def test_same_swing_start_peak_and_lead():
    (ev,) = session(H_AB, L_AB)
    assert (ev.low_bar, ev.peak_bar, ev.low, ev.high) == (4, 7, 95.0, 104.5)
    assert ev.start_ns == bar_ns(4) and ev.peak_ns == bar_ns(7) and ev.primary and ev.evaluable
    # V1: tepe = seans en yükseği (bar 7 burada) ama taban bar 0..7'nin minimumu — burada aynı; lead aynı swing'den
    assert lv.lead_v2(95.0, ev) == 0.0 and lv.lead_v2(99.75, ev) == pytest.approx(0.5) and lv.lead_v2(104.5, ev) == 1.0


def test_lead_clipped_only_for_safety():
    (ev,) = session(H_AB, L_AB)
    assert lv.lead_v2(90.0, ev) == 0.0 and lv.lead_v2(110.0, ev) == 1.0 and lv.lead_v2(float("nan"), ev) is None


def test_v1_peak_on_other_swing_is_fixed():
    # Açılış tepesi seans en yükseği; olay ise sonraki dip→tepe swing'i (V1 tepeyi açılışa koyardı)
    h = [110, 104, 100, 97, 99, 103, 106, 102]
    lo = [108, 100, 97, 96, 97, 99, 103, 100]
    (ev,) = session(h, lo)
    assert ev.low_bar == 3 and ev.peak_bar == 6 and ev.evaluable
    assert int(np.argmax(h)) == 0  # V1 tepe = bar 0 → tanım gereği yakalanamaz olurdu


def test_opening_peak_classified_separately():
    # İlk bar içinde %6: tepe ilk gözlemden (ilk barın bitişi) önce
    (ev,) = session([106, 104, 103], [100, 102, 101])
    assert ev.event_class == lv.PRE_OBSERVATION and not ev.evaluable
    # Sınır: tepe barı ilk gözlem anında başlıyor (tepe > ilk gözlem değil) → gözlem öncesi
    (edge,) = session([101, 107, 105], [100, 100.5, 104])
    assert edge.peak_bar == 1 and edge.event_class == lv.PRE_OBSERVATION
    (ev2,) = session([101, 102, 107], [100, 100.5, 104])
    assert (ev2.low_bar, ev2.peak_bar) == (0, 2) and ev2.event_class == lv.INTRADAY_EVALUABLE
    # Dip ve tepe aynı barda → bar içi
    (ev3,) = session([101, 101, 106.5, 104], [100.5, 100.8, 100, 103])
    assert ev3.low_bar == ev3.peak_bar == 2 and ev3.event_class == lv.INTRABAR


def test_opening_gap_is_a_separate_session_class():
    assert lv.opening_gap(105.0, 100.0) and not lv.opening_gap(104.9, 100.0) and not lv.opening_gap(105.0, None)


def test_multiple_swings_deterministic():
    h = [101, 106, 104, 101, 100, 103, 109, 105]
    lo = [100, 101, 102, 99, 98, 99, 103, 104]
    a = session(h, lo)
    b = session(list(h), list(lo))
    assert [e.as_dict() for e in a] == [e.as_dict() for e in b]
    assert [(e.low_bar, e.peak_bar) for e in a] == [(0, 1), (4, 6)]  # kronolojik, ayrık
    assert [e.primary for e in a] == [False, True]  # birincil = en büyük (98→109)
    assert a[0].peak_ns < a[1].start_ns


def test_primary_swing_equals_v1_event_definition():
    rng = np.random.default_rng(7)
    for _ in range(200):
        n = int(rng.integers(5, 97))
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        hi, lo = close * (1 + rng.uniform(0, 0.01, n)), close * (1 - rng.uniform(0, 0.01, n))
        df = pd.DataFrame({"Open": close, "High": hi, "Low": lo, "Close": close},
                          index=pd.DatetimeIndex(starts(n)).tz_localize("UTC"))
        v1 = session_outcome(df).max_runup
        evs = lv.session_events(starts(n), hi, lo)
        assert bool(evs) == (v1 >= lv.EVENT_THRESHOLD)
        if evs:
            assert next(e for e in evs if e.primary).runup == pytest.approx(v1)
        for e in evs:  # her swing kendi dip→tepe çifti
            assert e.runup == pytest.approx(hi[e.peak_bar] / lo[e.low_bar] - 1) and e.low_bar <= e.peak_bar


# ------------------------------------------------------------------ alarm ↔ olay
def _ev(start_bar, peak_bar):
    return lv.Swing(start_bar, peak_bar, 100.0, 106.0, bar_ns(start_bar), bar_ns(peak_bar), 0.06, True,
                    lv.INTRADAY_EVALUABLE)


def test_pre_in_post_alert_classes():
    ev = [_ev(10, 20)]
    cls, matched = lv.match_alerts([bar_ns(5)], ev)
    assert cls == [lv.PRE_EVENT] and matched == [None]  # sabah alarmı sonraki olayı yakalamış SAYILMAZ
    cls, matched = lv.match_alerts([bar_ns(21)], ev)
    assert cls == [lv.POST_PEAK] and matched == [None]
    cls, matched = lv.match_alerts([bar_ns(10)], ev)
    assert cls == [lv.IN_EVENT] and matched == [0]
    cls, matched = lv.match_alerts([bar_ns(20)], ev)
    assert cls == [lv.IN_EVENT] and matched == [0]  # tepe barı başlangıcı dahil
    assert lv.match_alerts([bar_ns(3)], [])[0] == [lv.NO_EVENT]


def test_chronological_one_to_one_matching():
    evs = [_ev(2, 6), _ev(10, 14)]
    cls, matched = lv.match_alerts([bar_ns(1), bar_ns(3), bar_ns(4), bar_ns(8), bar_ns(12), bar_ns(15)], evs)
    assert cls == [lv.PRE_EVENT, lv.IN_EVENT, lv.IN_EVENT_DUPLICATE, lv.PRE_EVENT, lv.IN_EVENT, lv.POST_PEAK]
    assert matched == [1, 4]
    # Örtüşen pencereler (savunma): tek alarm iki olayı yakalamaz
    cls, matched = lv.match_alerts([bar_ns(5)], [_ev(2, 8), _ev(4, 9)])
    assert cls == [lv.IN_EVENT] and matched == [0, None]


def test_onsets_and_first_alert_units():
    mask = np.array([1, 1, 0, 1, 1, 1, 0, 0], bool)
    sess = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    seg = np.array([0, 0, 0, 0, 4, 4, 4, 4])
    assert np.flatnonzero(lv.onsets(mask, seg)).tolist() == [0, 3, 4]  # yeni seansın ilk satırı yeni başlangıç
    assert np.flatnonzero(lv.first_only(mask, sess)).tolist() == [0, 4]
    for k in range(1, len(mask) + 1):  # nedensel: i'deki başlangıç yalnız ≤ i satırlarına bağlı
        assert lv.onsets(mask[:k], seg[:k]).tolist() == lv.onsets(mask, seg)[:k].tolist()


def _panel_eval(mask, t_ns, events, entry=None, unit=lv.ALERT_ONSET):
    n = len(mask)
    return lv.evaluate(np.array(mask, bool), np.zeros(n, int), np.zeros(n, int), np.array(t_ns, np.int64),
                       np.full(n, 103.0) if entry is None else np.array(entry, float), events, unit)


def test_provider_delay_changes_visibility_not_labels():
    h, lo = H_AB, L_AB
    ev_a = session(h, lo)
    ev_b = session(h, lo)  # olay kurucusu gecikme parametresi almaz
    assert [e.as_dict() for e in ev_a] == [e.as_dict() for e in ev_b]
    info = [bar_ns(k) for k in range(1, 10)]
    mask = [k == 5 for k in range(9)]  # bilgi zamanı bar 6 başlangıcı (pencere içi)
    d0 = _panel_eval(mask, info, [ev_a])
    d15 = _panel_eval(mask, [t + 15 * lv.MIN_NS for t in info], [ev_a])
    assert d0["event_count_raw"] == d15["event_count_raw"] == 1
    assert d0["alert_classes"][lv.IN_EVENT] == 1 and d0["recall_raw_v2"] == 1.0
    assert d15["alert_classes"][lv.POST_PEAK] == 1 and d15["recall_raw_v2"] == 0.0  # yalnız görünürlük değişti


def test_evaluable_denominator_and_both_recalls():
    ok_ev = _ev(10, 20)
    pre = lv.Swing(0, 0, 100.0, 106.0, bar_ns(0), bar_ns(0), 0.06, False, lv.PRE_OBSERVATION)
    m = _panel_eval([False, True], [bar_ns(1), bar_ns(12)], [[pre, ok_ev]])
    assert m["event_count_raw"] == 2 and m["event_count_evaluable"] == 1
    assert m["recall_raw_v2"] == 0.5 and m["recall_evaluable_v2"] == 1.0


def test_precision_fpr_and_first_alert_unit():
    evs = [[_ev(10, 20)], []]
    mask = np.array([1, 0, 1, 1, 0, 1], bool)
    sess = np.array([0, 0, 0, 1, 1, 1])
    seg = np.array([0, 0, 0, 3, 3, 3])
    t = np.array([bar_ns(5), bar_ns(9), bar_ns(12), bar_ns(5), bar_ns(6), bar_ns(7)])
    on = lv.evaluate(mask, sess, seg, t, np.full(6, 103.0), evs, lv.ALERT_ONSET)
    assert on["alerts"] == 4 and on["alert_classes"][lv.PRE_EVENT] == 1 and on["alert_classes"][lv.IN_EVENT] == 1
    assert on["precision_v2"] == 0.25 and on["FPR_v2"] == 1.0 and on["recall_raw_v2"] == 1.0
    assert on["pre_event_alert_rate"] == 0.25
    first = lv.evaluate(mask, sess, seg, t, np.full(6, 103.0), evs, lv.FIRST_ALERT)
    assert first["alerts"] == 2 and first["recall_raw_v2"] == 0.0  # ilk alarm olay öncesi → yakalanmadı


def test_lead_on_matched_swing():
    ev = _ev(10, 20)  # 100 → 106
    for entry, lead in ((100.0, 0.0), (103.0, 0.5), (106.0, 1.0)):
        m = _panel_eval([True], [bar_ns(15)], [[ev]], entry=[entry])
        assert m["median_lead_v2"] == pytest.approx(lead)


def test_no_lookahead_into_detector_input():
    class P:
        ok = np.array([True, True, True])
        rel_ret_z_3 = np.array([6.0, 1.0, 7.0])
    cand = {"feature": "rel_ret_z_3", "comparison": ">=", "threshold": 5.0, "confirmation": [1, 1]}
    before = mf.candidate_alerts(P, cand).copy()
    mask = before.copy()
    session(H_AB, L_AB)
    session([h * 2 for h in H_AB], L_AB)  # farklı gelecek barları: alarm girdisi değişmez
    _panel_eval(mask, [bar_ns(1), bar_ns(2), bar_ns(3)], [session(H_AB, L_AB)])
    assert mf.candidate_alerts(P, cand).tolist() == before.tolist() == mask.tolist()


# ------------------------------------------------------------------ koruma ve manifest
def test_consumed_final_forbidden_during_label_design(monkeypatch):
    seen = []
    monkeypatch.setattr(lx, "_selection", lambda: seen.append(au.selection_active()))
    lx.selection_stage()
    assert seen == [True] and not au.selection_active()
    with au.candidate_selection():
        with pytest.raises(RuntimeError, match="Consumed final cannot be reused for candidate selection"):
            pm.open_consumed_final()
    with pytest.raises(RuntimeError, match="Consumed final"):
        lx.fx.guarded_load("merged_new_d15.pkl", lambda n: pytest.fail("açılmamalı"))


def test_manifest_canonical_hash_and_freeze(tmp_path):
    a, b = lx.manifest_payload(), lx.manifest_payload()
    assert a == b and len(a["sha256"]) == 64
    assert a["config"]["version"] == "MOMENTUM_EVENT_LABEL_V2" and a["config"]["provider_delay_independent"] is True
    for k in ("event_threshold", "swing_policy", "pre_event_alert_policy", "post_peak_policy",
              "evaluable_event_policy", "lead_definition"):
        assert k in a["config"]
    path = tmp_path / "m.json"
    assert lx.freeze_manifest(path)["sha256"] == a["sha256"]
    assert lx.freeze_manifest(path)["sha256"] == a["sha256"]  # aynı tanım: kabul
    data = json.loads(path.read_text(encoding="utf-8"))
    data["config"]["event_threshold"] = 0.04
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(lx.LabelManifestError):
        lx.load_manifest(path)


def test_committed_manifest_matches_code():
    m = lx.load_manifest()
    assert m["sha256"] == lx.manifest_payload()["sha256"]


# ------------------------------------------------------------------ birincil birim: varlık-seans başına ilk WATCH
FINAL_SHA = "9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09"


def _one_session(mask, bars, events, unit=lv.FIRST_ALERT, entry=103.0):
    n = len(mask)
    return lv.evaluate(np.array(mask, bool), np.zeros(n, int), np.zeros(n, int),
                       np.array([bar_ns(b) for b in bars], np.int64), np.full(n, entry), [events], unit)


def test_primary_unit_is_first_watch_per_asset_session():
    assert lv.MANIFEST_CONFIG["alert_unit"] == "first_watch_alert_per_asset_session" == lv.FIRST_ALERT
    assert lv.MANIFEST_CONFIG["sensitivity_alert_unit"] == "each_watch_activation" == lv.ALERT_ONSET
    # NONE → WATCH → NONE → WATCH: birincil yalnız ilk WATCH başlangıcı
    m = _one_session([0, 1, 0, 1, 1], [1, 2, 3, 4, 5], [])
    assert m["alerts"] == 1 and m["alert_unit"] == lv.FIRST_ALERT
    assert lv.evaluate.__defaults__[0] == lv.FIRST_ALERT  # varsayılan birim birincil


def test_second_watch_cannot_rescue_earlier_false_alert():
    ev = [_ev(10, 20)]
    mask, bars = [1, 0, 1], [5, 8, 12]  # sabah PRE_EVENT, öğleden sonra olay içinde yeniden WATCH
    prim = _one_session(mask, bars, ev)
    assert prim["alert_classes"][lv.PRE_EVENT] == 1 and prim["alert_classes"][lv.IN_EVENT] == 0
    assert prim["recall_raw_v2"] == 0.0 and prim["precision_v2"] == 0.0 and prim["pre_event_alert_rate"] == 1.0
    sens = _one_session(mask, bars, ev, unit=lv.ALERT_ONSET)  # yalnız teşhis
    assert sens["recall_raw_v2"] == 1.0 and sens["precision_v2"] == 0.5


def test_first_in_event_alert_is_primary_tp_and_post_peak_is_not():
    ev = [_ev(10, 20)]
    tp = _one_session([1, 1], [12, 13], ev)
    assert tp["recall_raw_v2"] == 1.0 and tp["precision_v2"] == 1.0 and tp["median_lead_v2"] == pytest.approx(0.5)
    post = _one_session([1, 0, 1], [21, 22, 23], ev)
    assert post["recall_raw_v2"] == 0.0 and post["precision_v2"] == 0.0 and post["post_peak_alert_rate"] == 1.0


def test_multiple_events_primary_alert_binds_only_its_window():
    evs = [_ev(2, 6), _ev(10, 14)]
    prim = _one_session([1, 0, 1], [4, 8, 12], evs)
    rec = prim["_events"]
    assert [e["caught"] for e in rec] == [True, False]  # ikinci olay birincil metrikte kaçırılmış kalır
    assert prim["recall_raw_v2"] == 0.5 and prim["alerts"] == 1
    assert _one_session([1, 0, 1], [4, 8, 12], evs) == prim  # deterministik
    sens = _one_session([1, 0, 1], [4, 8, 12], evs, unit=lv.ALERT_ONSET)
    assert [e["caught"] for e in sens["_events"]] == [True, True]


def test_sensitivity_mode_available_and_units_validated():
    ev = [_ev(10, 20)]
    a = _one_session([1, 0, 1, 1], [5, 8, 12, 13], ev, unit=lv.ALERT_ONSET)
    b = _one_session([1, 0, 1, 1], [5, 8, 12, 13], ev, unit=lv.FIRST_ALERT)
    assert a["alert_unit"] != b["alert_unit"] and a["alerts"] == 2 and b["alerts"] == 1
    with pytest.raises(ValueError):
        _one_session([1], [12], ev, unit="FIRST_ALERT_PER_SESSION")


def test_final_manifest_sha_stable_and_immutable(tmp_path):
    m = lx.manifest_payload()
    assert m["sha256"] == FINAL_SHA and m["config"]["manifest_status"] == "FINAL"
    assert m["config"]["supersedes_draft_sha256"] == lv.DRAFT_SHA256
    assert lx.cd.canonical_json(m["config"]) == lx.cd.canonical_json(json.loads(lx.cd.canonical_json(m["config"])))
    # taslak → FINAL tek seferlik geçiş; FINAL değiştirilemez (yeni LABEL VERSION gerekir)
    draft = {"config": {"version": lv.LABEL_VERSION}, "sha256": lv.DRAFT_SHA256}
    path = tmp_path / "m.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(lx.LabelManifestError):  # taslak bozuk (SHA uyuşmuyor) → reddedilir
        lx.freeze_manifest(path)
    path.unlink()
    assert lx.freeze_manifest(path)["sha256"] == FINAL_SHA
    other = {"config": {**m["config"], "event_threshold": 0.04}}
    other["sha256"] = lx.cd.sha256_of(other["config"])
    path.write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(lx.LabelManifestError, match="yeni LABEL VERSION"):
        lx.freeze_manifest(path)
