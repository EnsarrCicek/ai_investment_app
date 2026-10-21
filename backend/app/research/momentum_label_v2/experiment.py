"""MOMENTUM_EVENT_LABEL_V2 — ölçüm yeniden tasarımı (YALNIZ araştırma; aday ayarı / yeni final YOK).

Kullanım (backend klasöründen, sırayla):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_label_v2.experiment selection
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_label_v2.experiment freeze
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_label_v2.experiment postmortem

* selection: tasarım ve V1↔V2 karşılaştırması YALNIZ referans evren × seçim seansları; `candidate_selection`
  bağlamında çalışır (tüketilmiş final açılamaz). Birincil birim: varlık-seans başına ilk WATCH; her aktivasyon
  yalnız ikincil duyarlılık.
* freeze: seçim sonuçları ve testler temizse FINAL manifest (kanonik JSON + SHA-256). Sonradan değiştirilemez;
  tanım değişirse yeni LABEL VERSION gerekir. Tek izinli geçiş: taslak (DRAFT_SHA256) → FINAL.
* postmortem: manifest dondurulduktan SONRA tüketilmiş finale yalnız açıklayıcı uygulama — "POSTMORTEM ONLY",
  PASS/FAIL üretilmez; eski karar (FAIL) değişmez.
* Eşikler değişmez: dondurulmuş aday (rel_ret_z_3 ≥ 5.0941…, 1/1, d15) ve Round 1 final WATCH/STRONG yalnız ölçüm
  karşılaştırması içindir.
"""

from __future__ import annotations

import json
import sys
import time as clock
from collections import Counter
from pathlib import Path

import numpy as np

from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_final import candidate as cd
from app.research.momentum_final import experiment as mf
from app.research.momentum_label_v2 import labels as lv

HERE = Path(__file__).parent
MANIFEST = HERE / "label_v2_manifest.json"
RUNS = HERE / "runs"
DELAYS = (0, 15)
POSTMORTEM_ONLY = "POSTMORTEM ONLY"
OLD_FINAL_VERDICT = "MOMENTUM UNTOUCHED FINAL: FAIL"


class LabelManifestError(RuntimeError):
    pass


# ------------------------------------------------------------------ manifest
def manifest_payload() -> dict:
    return {"config": lv.MANIFEST_CONFIG, "sha256": cd.sha256_of(lv.MANIFEST_CONFIG)}


def freeze_manifest(path: Path = MANIFEST) -> dict:
    """İlk çağrı yazar; sonraki çağrılar yalnız AYNI tanımı kabul eder. Yalnız FINAL olmayan taslak
    (`lv.DRAFT_SHA256`) bir kez FINAL ile değiştirilebilir."""
    m = manifest_payload()
    if path.exists():
        existing = load_manifest(path)
        if existing["sha256"] == m["sha256"]:
            return existing
        if existing["sha256"] != lv.DRAFT_SHA256 or existing["config"].get("manifest_status") == "FINAL":
            raise LabelManifestError(f"{lv.LABEL_VERSION} manifesti FINAL olarak dondurulmuş; tanım değişikliği "
                                     "yeni LABEL VERSION gerektirir")
    path.write_text(json.dumps(m, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")
    return m


def load_manifest(path: Path = MANIFEST) -> dict:
    if not path.exists():
        raise LabelManifestError("Label V2 manifesti yok")
    m = json.loads(path.read_text(encoding="utf-8"))
    if cd.sha256_of(m["config"]) != m.get("sha256"):
        raise LabelManifestError("Label V2 manifesti bozulmuş (SHA uyuşmuyor)")
    return m


# ------------------------------------------------------------------ olaylar (gecikmeden bağımsız)
def build_events(p: fx.Panel) -> tuple[list[list[lv.Swing]], np.ndarray]:
    """Seans başına V2 olayları + açılış boşluğu bayrağı. Yalnız bar verisi; alarm girdisi değil."""
    events, gap = [], np.zeros(len(p.sessions), dtype=bool)
    cache = {}
    for s, (sym, day) in enumerate(p.sessions):
        if sym not in cache:
            cache[sym] = r1ds.load(sym).bars.dropna()
        bars = cache[sym]
        d = bars[bars.index.date == day]
        prev = bars[bars.index.date < day]
        starts = d.index.as_unit("ns").asi8
        events.append(lv.session_events(starts, d["High"].to_numpy(), d["Low"].to_numpy()))
        gap[s] = lv.opening_gap(float(d["Open"].iloc[0]), float(prev["Close"].iloc[-1]) if len(prev) else None)
    return events, gap


def v1_v2_event_equivalence(p: fx.Panel, events) -> dict:
    """V2 olaylı seans kümesi = V1 olay seansı kümesi olmalı (birincil swing = V1 max_runup)."""
    lab = p.labels[15]
    v2 = np.array([bool(e) for e in events])
    mismatch = int((v2 != lab.sess_event).sum())
    peak_moved = sum(1 for s in np.flatnonzero(lab.sess_event)
                     if next(e for e in events[s] if e.primary).peak_ns != int(lab.sess_high_ns[s]))
    v1_swing_short = int(sum(lab.sess_event[s] and lab.sess_high[s] / lab.sess_run_low[s] - 1 < fx.E
                             for s in range(len(events))))
    return {"v1_event_sessions": int(lab.sess_event.sum()), "v2_event_sessions": int(v2.sum()),
            "session_set_mismatch": mismatch, "v1_peak_not_on_primary_swing": peak_moved,
            "v1_low_to_session_high_below_threshold": v1_swing_short}


def event_census(events, gap) -> dict:
    flat = [e for ev in events for e in ev]
    multi = sum(1 for ev in events if len(ev) > 1)
    by_cls = Counter(e.event_class for e in flat)
    prim = Counter(e.event_class for e in flat if e.primary)
    return {"v2_raw_events": len(flat), "v2_evaluable_events": by_cls[lv.INTRADAY_EVALUABLE],
            "by_class": dict(by_cls), "primary_by_class": dict(prim),
            "event_sessions": sum(1 for ev in events if ev), "multiple_swing_sessions": multi,
            "secondary_swings": len(flat) - sum(1 for ev in events if ev),
            "opening_gap_sessions": int(gap.sum()),
            "opening_gap_sessions_with_pre_observation_event": int(sum(
                gap[s] and any(e.event_class == lv.PRE_OBSERVATION for e in ev) for s, ev in enumerate(events))),
            "opening_gap_sessions_without_intraday_event": int(sum(gap[s] and not ev for s, ev in enumerate(events)))}


# ------------------------------------------------------------------ metrikler
def _brief(m: dict) -> dict:
    out = {k: v for k, v in m.items() if not k.startswith("_")}
    out["median_first_alert_clock"] = fx._hm(m["median_first_alert_minute"])
    return out


def v1_brief(m: dict, br: float) -> dict:
    return {**{k: m[k] for k in ("alert_sessions", "precision", "recall", "false_positive_rate",
                                 "lead_fraction_median", "caught_events", "events")},
            "specificity": 1 - m["false_positive_rate"] if m["false_positive_rate"] is not None else None,
            "median_first_alert_clock": fx._hm(m["median_first_alert_minute"]), "precision_vs_base": (
                m["precision"] / br if m["precision"] is not None and br else None)}


def evaluate(p: fx.Panel, events, mask: np.ndarray, delay: int, unit: str = lv.FIRST_ALERT) -> dict:
    lab = p.labels[delay]
    return lv.evaluate(mask, p.sess, p.seg_start, lab.t_ns, lab.entry, events, unit, lab.mfe_close, fx.X)


def decompose(p: fx.Panel, events, mask: np.ndarray, delay: int) -> dict:
    """V1 yakalananları / kaçırılanları V2 penceresine göre ayrıştırır (eşik aynı)."""
    lab = p.labels[delay]
    uniq, rows = fr.first_alert_rows(mask, p.sess)
    first = dict(zip(uniq.tolist(), rows.tolist()))
    v2_first = evaluate(p, events, mask, delay, lv.FIRST_ALERT)
    v2_on = evaluate(p, events, mask, delay, lv.ALERT_ONSET)
    caught_first = {e["sess"] for e in v2_first["_events"] if e["caught"]}
    caught_on = {e["sess"] for e in v2_on["_events"] if e["caught"]}
    tp, fn = Counter(), Counter()
    for s in np.flatnonzero(lab.sess_event):
        r = first.get(int(s))
        if r is not None and lab.t_ns[r] <= lab.sess_high_ns[s]:  # V1 "yakalandı"
            cls, _ = lv.match_alerts([int(lab.t_ns[r])], events[s])
            tp[{"IN_EVENT_ALERT": "IN_EVENT_TRUE_POSITIVE", "PRE_EVENT_ALERT": "PRE_EVENT_FALSE_ASSOCIATION",
                "POST_PEAK_ALERT": "POST_PEAK_FALSE_ASSOCIATION"}[cls[0]]] += 1
            continue
        if not any(e.evaluable for e in events[s]):
            fn["MEASUREMENT_ARTIFACT_NON_EVALUABLE"] += 1
        elif s in caught_first:
            fn["MEASUREMENT_ARTIFACT_PEAK_MISMATCH"] += 1
        elif s in caught_on:
            fn["SENSITIVITY_ONLY_LATER_ACTIVATION"] += 1
        else:
            fn["GENUINE_MISS"] += 1
    return {"v1_true_positive_split": dict(tp), "v1_true_positives": sum(tp.values()),
            "v1_false_negative_split": dict(fn), "v1_false_negatives": sum(fn.values()),
            "v2_primary_missed_evaluable_events_split": missed_split(lab, events, v2_first),
            "v2_sensitivity_missed_evaluable_events_split": missed_split(lab, events, v2_on)}


def missed_split(lab, events, v2: dict) -> dict:
    """Kaçırılan değerlendirilebilir olaylar, o birimin alarmlarına göre: tepe sonrası / olay öncesi / başka olayın
    penceresinde (birincil ilk alarm o güne harcanmış) / hiç alarm yok."""
    alerts_by_sess: dict[int, list[tuple[int, str]]] = {}
    for a in v2["_alerts"]:
        alerts_by_sess.setdefault(a["sess"], []).append((int(lab.t_ns[a["row"]]), a["class"]))
    miss = Counter()
    for e in v2["_events"]:
        if not e["evaluable"] or e["caught"]:
            continue
        ev = events[e["sess"]][e["k"]]
        nxt = [x.start_ns for x in events[e["sess"]] if x.start_ns > ev.peak_ns]
        end = min(nxt) if nxt else np.iinfo(np.int64).max
        got = alerts_by_sess.get(e["sess"], [])
        times = [t for t, _ in got]
        if any(ev.peak_ns < t < end for t in times):
            miss["POST_PEAK_ONLY"] += 1
        elif any(t < ev.start_ns and c == lv.PRE_EVENT for t, c in got):
            miss["PRE_EVENT_ONLY"] += 1
        elif any(c in (lv.IN_EVENT, lv.IN_EVENT_DUPLICATE) for _, c in got):
            miss["ALERT_USED_BY_OTHER_EVENT"] += 1
        else:
            miss["NO_ALERT_AROUND_EVENT"] += 1
    return dict(miss)


def masks(p: fx.Panel, cand: dict) -> dict[str, np.ndarray]:
    return {"frozen_candidate_watch_1of1": mf.candidate_alerts(p, cand),
            "round1_final_watch_3of3": fr.confirm(p.watch_raw(fx.R1_FINAL_WATCH), p.seg_start, 3, 3),
            "round1_final_strong_3of3": fr.confirm(p.strong_raw(fx.R1_FINAL_STRONG), p.seg_start, 3, 3)}


def compare(p: fx.Panel, events, rules: dict[str, np.ndarray]) -> dict:
    br = {d: fx.base_rate(p, d) for d in DELAYS}
    out = {}
    for name, mask in rules.items():
        out[name] = {}
        for d in DELAYS:
            out[name][f"d{d}"] = {
                "V1": v1_brief(fr.metrics(mask, p.sess, p.labels[d], fx.X), br[d]),
                "V2_primary_first_watch_per_asset_session": _brief(evaluate(p, events, mask, d, lv.FIRST_ALERT)),
                "V2_sensitivity_each_watch_activation": _brief(evaluate(p, events, mask, d, lv.ALERT_ONSET))}
    return out


def delay_independence(events_d0, events_d15) -> bool:
    return [[e.as_dict() for e in ev] for ev in events_d0] == [[e.as_dict() for e in ev] for ev in events_d15]


# ------------------------------------------------------------------ aşamalar
def selection_stage():
    with au.candidate_selection():  # tasarım: tüketilmiş final açılamaz
        _selection()


def _selection():
    started = clock.perf_counter()
    rows = fx.load_selection_rows()  # koruma: dokunulmamış varlık/final tarihi → RuntimeError
    p = fx.Panel(rows)
    for d in DELAYS:
        p.build_labels(d)
    events, gap = build_events(p)
    events_again, _ = build_events(p)
    cand = cd.load_frozen(mf.MANIFEST)["candidate"]
    rules = masks(p, cand)
    result = {
        "label_config_sha256": manifest_payload()["sha256"], "alert_unit": lv.FIRST_ALERT,
        "sensitivity_alert_unit": lv.ALERT_ONSET, "scope": {
            "assets": len({s for s, _ in p.sessions}), "sessions": len(p.sessions), "rows": len(p.rows),
            "days": [str(min(d for _, d in p.sessions)), str(max(d for _, d in p.sessions))],
            "consumed_final_read": False},
        "v1_v2_event_equivalence": v1_v2_event_equivalence(p, events),
        "event_census": event_census(events, gap),
        "labels_deterministic_rebuild": delay_independence(events, events_again),
        "labels_take_delay_input": False,  # d0 ve d15 aynı `events` nesnesini kullanır
        "comparison": compare(p, events, rules),
        "frozen_candidate_decomposition": {f"d{d}": decompose(p, events, rules["frozen_candidate_watch_1of1"], d)
                                           for d in DELAYS},
        "round1_watch_decomposition_d15": decompose(p, events, rules["round1_final_watch_3of3"], 15),
        "elapsed_seconds": None}
    result["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    write_json("selection_v1_v2.json", result)
    print(json.dumps(result, ensure_ascii=False, default=str))


def freeze_stage():
    m = freeze_manifest()
    print(json.dumps({"version": m["config"]["version"], "status": m["config"]["manifest_status"],
                      "alert_unit": m["config"]["alert_unit"], "sha256": m["sha256"]}, ensure_ascii=False))


def postmortem_stage():
    """Tüketilmiş final — YALNIZ açıklayıcı. Manifest önceden dondurulmuş olmalı; PASS/FAIL yok."""
    from app.research.momentum_final import postmortem as pm
    manifest = load_manifest()
    assert manifest["sha256"] == manifest_payload()["sha256"], "etiket tanımı manifestten sonra değişmiş"
    rows = pm.open_consumed_final()  # aday seçimi bağlamında RuntimeError
    p = fx.Panel(rows)
    p.build_labels(mf.FINAL_DELAY)
    events, gap = build_events(p)
    cand = cd.load_frozen(mf.MANIFEST)["candidate"]
    mask = mf.candidate_alerts(p, cand)
    d = mf.FINAL_DELAY
    br = fx.base_rate(p, d)
    out = {"status": POSTMORTEM_ONLY, "old_verdict_unchanged": OLD_FINAL_VERDICT, "pass_fail_recomputed": False,
           "label_manifest_sha256": manifest["sha256"], "candidate_sha256": cd.sha256_of(cand), "delay_minutes": d,
           "v1_v2_event_equivalence": {k: v for k, v in v1_v2_event_equivalence(p, events).items()},
           "event_census": event_census(events, gap),
           "V1": v1_brief(fr.metrics(mask, p.sess, p.labels[d], fx.X), br),
           "V2_primary_first_watch_per_asset_session": _brief(evaluate(p, events, mask, d, lv.FIRST_ALERT)),
           "V2_sensitivity_each_watch_activation": _brief(evaluate(p, events, mask, d, lv.ALERT_ONSET)),
           "decomposition": decompose(p, events, mask, d)}
    write_json("postmortem_label_v2_final.json", out)
    print(json.dumps(out, ensure_ascii=False, default=str))


def write_json(name, payload):
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main(stage: str):
    {"selection": selection_stage, "freeze": freeze_stage, "postmortem": postmortem_stage}[stage]()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
