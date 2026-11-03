"""Momentum PILOT geliştirme — bölme manifesti ve pilot analizi (YALNIZ araştırma; toplayıcıya/üretime dokunmaz).

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment split
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment analyze
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment mobile <momentum_shadow.db>

* split: toplayıcının FULL seans sınıflamasından (yalnız XU100 bar zaman meta verisi) pilot manifestini oluşturur /
  sona ekleyerek günceller. Fiyat/olay/alarm okunmaz.
* analyze: YALNIZ manifestteki pilot seansları (+ başlangıç öncesi ısınma seansları). Her metrik
  "PILOT / DEVELOPMENT ONLY"; PASS/FAIL, aday dondurma, BUY/SELL/HOLD yok.
* mobile: dışa aktarılmış MOBILE_SHADOW veritabanını pilot seanslarında Windows ile karşılaştırır (birleştirme yok).
* Arşiv salt okunur açılır (SQLite `mode=ro`); toplayıcı çalışmaya devam eder.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
import sys
import time as clock
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import storage as st
from app.research.momentum_final import candidate as cd
from app.research.momentum_final import experiment as mf
from app.research.momentum_pilot import analysis as an
from app.research.momentum_pilot import split as sp


class _ReadOnlyArchive:
    """`integrity.classify_sessions` için `.db` taşıyan salt okunur bağlantı."""

    def __init__(self, root: Path = st.PRIMARY_ROOT):
        self.db = sqlite3.connect(f"file:{(root / 'archive.sqlite').as_posix()}?mode=ro", uri=True)

    def close(self):
        self.db.close()


def session_classes(a) -> tuple[list[str], list[str]]:
    """(başlangıç ve sonrası FULL seanslar, başlangıç öncesi FULL ısınma seansları)."""
    m = mm.load()
    start = m["config"]["prospective_start_session"]
    sess = ig.classify_sessions(a, m["config"]["benchmark"])
    full = sp.observed_full_sessions(sess, start)
    warm = sorted(d for d, c in zip(sess["session_date"], sess["session_class"])
                  if c == "FULL" and d < start and not mm.in_consumed_final(date.fromisoformat(d)))
    return full, warm


def split_stage() -> dict:
    a = _ReadOnlyArchive()
    try:
        full, _ = session_classes(a)
    finally:
        a.close()
    m, changed = sp.refresh_manifest(full, mm.load(), datetime.now(timezone.utc))
    out = {"observed_full_sessions": full, "manifest_changed": changed, "sha256": m["sha256"], **m["manifest"]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def _write(name: str, payload) -> Path:
    sp.RUNS.mkdir(parents=True, exist_ok=True)
    path = sp.RUNS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def load_pilot_context(workers: int = 7, use_cache: bool = True) -> dict:
    """Pilot verisi + öznitelik paneli + V2 olayları + mevcut kural maskeleri (holdout koruması altında).
    Öznitelik satırları pilot manifest SHA'sına bağlı olarak `runs/` altında önbelleğe alınır."""
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    c = mm.load()["config"]
    pilot = list(manifest["manifest"]["pilot_sessions"])
    a = _ReadOnlyArchive()
    try:
        _, warm = session_classes(a)
        sessions = warm + pilot
        symbols = list(c["universe"]) + [c["benchmark"]]
        b5 = sp.load_primary_bars(a.db, guard, sessions, "5m", symbols)
        b1 = sp.load_primary_bars(a.db, guard, sessions, "1m", symbols)
        rev5 = sp.load_primary_revisions(a.db, guard, pilot, "5m")
        rev1 = sp.load_primary_revisions(a.db, guard, pilot, "1m")
    finally:
        a.close()
    assert set(b5["source"]) == {sp.PRIMARY_SOURCE} and set(b1["source"]) == {sp.PRIMARY_SOURCE}
    data = {s: an.to_asset_data(s, g) for s, g in b5.groupby("symbol")}
    bench = data.pop(c["benchmark"])
    days = [date.fromisoformat(d) for d in pilot]
    cache = sp.RUNS / f"pilot_rows_{manifest['sha256'][:16]}.pkl"
    if use_cache and cache.exists():
        with cache.open("rb") as f:
            rows = pickle.load(f)
    else:
        rows = an.build_rows(data, bench, days, workers)
        sp.RUNS.mkdir(parents=True, exist_ok=True)
        with cache.open("wb") as f:
            pickle.dump(rows, f)
    guard.check_sessions(sorted({str(r["day"]) for r in rows}))
    p = an.PilotPanel(rows, {s: d.bars for s, d in data.items()})
    for d in an.DELAYS:
        p.build_labels(d)
    events, gap = an.build_events(p)
    cand = cd.load_frozen(mf.MANIFEST)["candidate"]
    return {"manifest": manifest, "guard": guard, "config": c, "pilot": pilot, "warm": warm, "b5": b5, "b1": b1,
            "rev5": rev5, "rev1": rev1, "data": data, "bench": bench, "p": p, "events": events, "gap": gap,
            "cand": cand, "rules": an.rule_masks(p, cand)}


def analyze_stage(workers: int = 7) -> dict:
    started = clock.perf_counter()
    ctx = load_pilot_context(workers)
    manifest, guard, c, pilot, warm = ctx["manifest"], ctx["guard"], ctx["config"], ctx["pilot"], ctx["warm"]
    b5, b1, rev5, rev1, p = ctx["b5"], ctx["b1"], ctx["rev5"], ctx["rev1"], ctx["p"]
    events, gap, rules = ctx["events"], ctx["gap"], ctx["rules"]
    pb5, pb1 = b5[b5["session_date"].isin(pilot)], b1[b1["session_date"].isin(pilot)]
    latency = an.latency_stats(pd.concat([pb5, pb1]))
    table = an.event_table(p, events, gap, rules, an.latency_by_asset_session(pb5))
    ev_by_key = {(sym, str(day), k): ev for (sym, day), evs in zip(p.sessions, events) for k, ev in enumerate(evs)}
    present = {d: sorted(set(pb5.loc[pb5["session_date"] == d, "symbol"]) & set(c["universe"])) for d in pilot}
    out = {
        "label": sp.PILOT_LABEL, "never": "PROSPECTIVE FINAL",
        "pilot_manifest_sha256": manifest["sha256"], "pilot_status": manifest["manifest"]["status"],
        "pilot_sessions": pilot, "warmup_sessions": warm, "access_cutoff": guard.cutoff,
        "label_v2_sha256": sp.LABEL_V2_SHA256, "alert_unit": an.lv.FIRST_ALERT,
        "data_source": sp.PRIMARY_SOURCE, "bar_values": "FIRST_SEEN (revisions not applied)",
        "coverage": {"assets_per_pilot_session": {d: len(v) for d, v in present.items()},
                     "missing_primary_assets": {d: sorted(set(c["universe"]) - set(v)) for d, v in present.items()},
                     "panel_asset_sessions": len(p.sessions), "rows": len(p.rows),
                     "rows_status_ok": int(p.ok.sum()),
                     "pilot_5m_bars": int(len(pb5)), "pilot_1m_bars": int(len(pb1)),
                     "pilot_5m_null_volume_bars": int(pb5["volume"].isna().sum()),
                     "pilot_revisions_5m": int(len(rev5)), "pilot_revisions_1m": int(len(rev1))},
        "event_census": an.lx.event_census(events, gap),
        "rules": {name: {"description": an.RULE_NAMES[name],
                         **{f"d{d}": an.rule_metrics(p, events, mask, d) for d in an.DELAYS}}
                  for name, mask in rules.items()},
        "early_moves": an.early_summary(table),
        "false_positives_d15": {name: an.fp_analysis(p, events, mask, 15) for name, mask in rules.items()},
        "timing_1m_vs_5m": an.timing_comparison(table, ev_by_key, pb5, pb1),
        "provider_latency_probe": latency,
        "event_table": table,
        "elapsed_seconds": round(clock.perf_counter() - started, 1)}
    path = _write(f"pilot_analysis_{guard.cutoff}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("event_table",)}, ensure_ascii=False, indent=1,
                     default=str))
    print("WRITTEN", path)
    return out


def mobile_stage(db_path: str | None) -> dict:
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    pilot = list(manifest["manifest"]["pilot_sessions"])
    if not db_path or not Path(db_path).exists():
        out = {"status": "NO_MOBILE_EXPORT_AVAILABLE", "label": sp.PILOT_LABEL}
        print(json.dumps(out))
        return out
    a = _ReadOnlyArchive()
    mob = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        out = {"label": sp.PILOT_LABEL, "pilot_sessions": pilot}
        for iv in ("5m", "1m"):
            w = sp.load_primary_bars(a.db, guard, pilot, iv)
            m = sp.load_mobile_bars(mob, guard, pilot, iv)
            out[iv] = an.compare_sources(w, m, sp.load_primary_revisions(a.db, guard, pilot, iv),
                                         sp.load_mobile_revisions(mob, guard, pilot, iv))
    finally:
        a.close()
        mob.close()
    _write(f"mobile_vs_windows_{guard.cutoff}.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def deep_stage(workers: int = 7) -> dict:
    """Pilot derin analizi + önceden sabit kurallarla aday kararı. Holdout okunmaz; ML otomatik seçilemez."""
    from app.research.momentum_pilot import deep as dp
    started = clock.perf_counter()
    ctx = load_pilot_context(workers)
    p, events, gap, rules, pilot = ctx["p"], ctx["events"], ctx["gap"], ctx["rules"], ctx["pilot"]
    pb5, pb1 = ctx["b5"][ctx["b5"]["session_date"].isin(pilot)], ctx["b1"][ctx["b1"]["session_date"].isin(pilot)]
    vis = dp.measured_visibility(p, pb5)
    table = an.event_table(p, events, gap, rules, an.latency_by_asset_session(pb5))
    ev_by_key = {(sym, str(day), k): ev for (sym, day), evs in zip(p.sessions, events) for k, ev in enumerate(evs)}
    days = sorted({d for _, d in p.sessions})
    masks = {**dp.grid_masks(p, ctx["cand"], "C"), **dp.grid_masks(p, ctx["cand"], "A")}
    fam = {f: {k: v for k, v in masks.items() if dp.GRID[k]["base"] == f} for f in ("C", "A")}
    lodo = dp.lodo_grid(p, events, masks, days)
    pooled = {k: dp.evaluate_subset(p, events, m, dp.SCENARIO) for k, m in masks.items()}
    selection = dp.select_candidate(pooled, lodo)
    ml = dp.ml_baseline(p, events, days)
    one_min = dp.one_minute_study(table, ev_by_key, pb5, pb1, ctx["config"]["benchmark"])
    cases = dp.pick_cases(table, p, events, rules["frozen_candidate_watch_1of1"])
    frozen = None
    if selection["selected"]:
        payload = dp.candidate_payload(selection["selected"], ctx["cand"], ctx["manifest"],
                                       datetime.now(timezone.utc).isoformat())
        frozen = dp.freeze_candidate(payload)
    out = {
        "label": sp.PILOT_LABEL, "experimental": dp.EXPERIMENTAL,
        "pilot_manifest_sha256": ctx["manifest"]["sha256"], "pilot_status": ctx["manifest"]["manifest"]["status"],
        "pilot_sessions": pilot, "access_cutoff": ctx["guard"].cutoff,
        "label_v2_sha256": sp.LABEL_V2_SHA256, "alert_unit": an.lv.FIRST_ALERT, "data_source": sp.PRIMARY_SOURCE,
        "sample": {"asset_sessions": len(p.sessions), "rows": len(p.rows), "rows_status_ok": int(p.ok.sum()),
                   "raw_events": sum(len(ev) for ev in events),
                   "evaluable_events": sum(e.evaluable for ev in events for e in ev),
                   "event_sessions": sum(bool(ev) for ev in events),
                   "non_event_sessions": sum(not ev for ev in events),
                   "bar_coverage": dp.coverage(pb5, pb1, list(ctx["config"]["universe"]), pilot)},
        "visibility": {k: v for k, v in vis.items() if k != "measured_mask"},
        "baseline_rules": {name: {"d0_information_time": dp.evaluate_subset(p, events, m, 0),
                                  "measured_visibility": dp.evaluate_subset(p, events, m, "measured"),
                                  "assumed_d15": dp.evaluate_subset(p, events, m, 15)} for name, m in rules.items()},
        "feature_separability": dp.separability(p, events, rules["round1_final_watch_3of3"]),
        "grid": dp.GRID, "gates": dp.GATES,
        "fp_ablation_C": dp.variant_table(p, events, fam["C"]),
        "round1_watch_ablation_A": dp.variant_table(p, events, fam["A"]),
        "one_minute_vs_five_minute": one_min,
        "provider_latency": dp.latency_table(pb5, pb1),
        "latency_aware_existing_rules": dp.latency_view(p, events, rules, vis["measured_mask"]),
        "leave_one_day_out": lodo,
        "selection": selection,
        "frozen_candidate": frozen,
        "ml_baseline": {k: v for k, v in ml.items() if not k.startswith("_")},
        "leakage_audit": {"static": dp.static_leakage_check(), "truncation": dp.truncation_audit(ctx)},
        "case_studies": dp.case_studies(cases, p, events, table, one_min, rules, ml, vis["measured_mask"]),
        "elapsed_seconds": None}
    out["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    path = _write(f"pilot_deep_{ctx['guard'].cutoff}.json", out)
    print("WRITTEN", path, out["elapsed_seconds"], "s", "DECISION", selection["decision"], selection["selected"])
    return out


def redesign_stage(workers: int = 7) -> dict:
    """Pilot sonrası aday yeniden tasarımı (deneysel; dondurma yok). Tarihsel seçim + 5 pilot seansı; holdout yok."""
    from app.research.momentum_pilot import deep as dp
    from app.research.momentum_pilot import redesign as rd
    from app.research.momentum_round2 import dataset as ds2
    started = clock.perf_counter()
    audit_before = rd.holdout_audit("before")
    ctx = load_pilot_context(workers)
    p = ctx["p"]
    pb5 = ctx["b5"][ctx["b5"]["session_date"].isin(ctx["pilot"])]
    dp.measured_visibility(p, pb5)
    neck = rd.bottleneck(p, ctx["events"])
    pilot_panel, pilot_days, access = rd.load_pilot(None)
    vis_fn, med_ns = rd.pilot_visibility(access["probe_bars"])
    pilot = rd.Grid(pilot_panel, pilot_days, vis_fn, "PILOT")
    hist_panel, hist_days = rd.load_historical(list(ds2.REFERENCE_ASSETS))
    hist = rd.Grid(hist_panel, hist_days, rd.estimated_visibility(med_ns), "HISTORICAL_DEVELOPMENT")
    print("grids", len(hist.rows), len(pilot.rows), f"{clock.perf_counter() - started:.0f}s", flush=True)
    arch = {}
    for kind in rd.ARCHITECTURES:
        arch[kind] = rd.run_architecture(kind, hist, pilot, hist_days)
        print(kind, "done", f"{clock.perf_counter() - started:.0f}s", flush=True)
    out = {
        "label": sp.PILOT_LABEL, "experimental": rd.EXPERIMENTAL, "candidate_status": "NOT FROZEN",
        "pilot_manifest_sha256": ctx["manifest"]["sha256"], "label_v2_sha256": sp.LABEL_V2_SHA256,
        "data": {"historical_development": {"assets": len(ds2.REFERENCE_ASSETS), "days": [str(hist_days[0]),
                                                                                           str(hist_days[-1])],
                                            "n_days": len(hist_days), "rows": len(hist.rows),
                                            "asset_sessions": len(hist.sessions),
                                            "evaluable_events": sum(e.evaluable for ev in hist.events for e in ev),
                                            "early_label_rows": int(hist.y.sum()),
                                            "visibility": f"ESTIMATED: info + measured pilot 5m median "
                                                          f"{med_ns / 60e9:.2f} min"},
                 "pilot": {"days": [str(d) for d in pilot_days], "rows": len(pilot.rows),
                           "asset_sessions": len(pilot.sessions),
                           "evaluable_events": sum(e.evaluable for ev in pilot.events for e in ev),
                           "early_label_rows": int(pilot.y.sum()), "rows_live_measured": int(pilot.measured.sum())}},
        "lead_bottleneck_pilot": neck,
        "pre_event_study": {"historical": rd.pre_event_study(hist), "pilot": rd.pre_event_study(pilot)},
        "shock_normalization": rd.shock_normalization(pilot, hist),
        "architectures": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in arch.items()},
        "holdout_access_audit": {"before": audit_before, "pilot_sessions_read": access["sessions_read"],
                                 "max_pilot_session_read": max(access["sessions_read"]),
                                 "historical_last_day": str(hist_days[-1]),
                                 "consumed_final_first_day": "2026-09-28", "after": rd.holdout_audit("after")},
        "elapsed_seconds": None}
    assert out["holdout_access_audit"]["max_pilot_session_read"] <= ctx["guard"].cutoff
    out["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    path = _write(f"pilot_redesign_{ctx['guard'].cutoff}.json", out)
    print("WRITTEN", path, out["elapsed_seconds"], "s")
    return out


def ranking_stage() -> dict:
    """Kesitsel lider sıralaması (deneysel; dondurma yok). Tarihsel seçim + 5 pilot seansı; holdout yok."""
    import json as _json
    from app.research.momentum_pilot import ranking as rk
    from app.research.momentum_pilot import redesign as rd
    from app.research.momentum_round2 import dataset as ds2
    started = clock.perf_counter()
    audit_before = rd.holdout_audit("before")
    sel, final = ds2.selection_and_final()
    assert str(max(sel)) == "2026-09-25" and max(sel) < min(final)
    pilot_panel, pilot_days, access = rd.load_pilot(None)
    vis_fn, med_ns = rd.pilot_visibility(access["probe_bars"])
    pilot = rd.Grid(rk.add_ranks(rk.add_percentiles(pilot_panel)), pilot_days, vis_fn, "PILOT")
    hist_panel, hist_days = rd.load_historical(list(ds2.REFERENCE_ASSETS))
    hist = rd.Grid(rk.add_ranks(rk.add_percentiles(hist_panel)), hist_days, rd.estimated_visibility(med_ns),
                   "HISTORICAL_DEVELOPMENT_ESTIMATED_LATENCY")
    print("grids", len(hist.rows), len(pilot.rows), f"{clock.perf_counter() - started:.0f}s", flush=True)
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    c = mm.load()["config"]
    pilot_s = list(manifest["manifest"]["pilot_sessions"])
    a = _ReadOnlyArchive()
    try:
        b5 = sp.load_primary_bars(a.db, guard, pilot_s, "5m", list(c["universe"]) + [c["benchmark"]])
        b1 = sp.load_primary_bars(a.db, guard, pilot_s, "1m", list(c["universe"]) + [c["benchmark"]])
    finally:
        a.close()
    events_study = {g.source: {s: rk.event_rank_study(g, s) for s in rk.SCORE_NAMES} for g in (hist, pilot)}
    feature_lift = {g.source: rk.single_feature_lift(g) for g in (hist, pilot)}
    pol = rk.evaluate_policies(hist, pilot)
    top3 = rk.rank_top3(pol)
    print("policies", f"{clock.perf_counter() - started:.0f}s", flush=True)
    oct23 = {name: pilot.both(pol[name]["_pilot_mask"], {date(2026, 10, 23)})
             for name in pol if pol[name]["spec"]["persistence"] == 1 and pol[name]["spec"]["floor"] is None}
    ltr = rk.ltr(hist, pilot)
    one_min = rk.one_minute_ranking(pilot, b5, b1, c["benchmark"])
    deep = _json.loads((sp.RUNS / "pilot_deep_2026-10-30.json").read_text(encoding="utf-8"))
    red = _json.loads((sp.RUNS / "pilot_redesign_2026-10-30.json").read_text(encoding="utf-8"))

    def fold23(name):
        return next(f for f in deep["leave_one_day_out"][name]["folds"] if f["validation_day"] == "2026-10-23")
    baselines = {
        "Round1_WATCH (A0, pilot measured)": {"pilot": deep["round1_watch_ablation_A"]["A0_round1_watch"]["measured"],
                                              "oct23": fold23("A0_round1_watch")},
        "A5d weak_volume+relative (pilot measured)": {
            "pilot": deep["round1_watch_ablation_A"]["A5d_weak_volume+relative"]["measured"],
            "oct23": fold23("A5d_weak_volume+relative")},
        "redesign two_stage": {k: red["architectures"]["two_stage"][k] for k in ("historical_cv_pooled",
                                                                                  "pilot_pooled")}
        | {"oct23": red["architectures"]["two_stage"]["pilot_by_day"]["2026-10-23"]},
        "redesign logistic": {k: red["architectures"]["logistic"][k] for k in ("historical_cv_pooled", "pilot_pooled")}
        | {"oct23": red["architectures"]["logistic"]["pilot_by_day"]["2026-10-23"]}}
    top = {}
    for name in top3:
        r = pol[name]
        top[name] = {"spec": r["spec"], "historical": r["historical"], "pilot": r["pilot"],
                     "historical_stability": rk.day_stability(hist, r["_hist_mask"]),
                     "pilot_stability": rk.day_stability(pilot, r["_pilot_mask"]),
                     "pilot_by_day": {str(d): pilot.both(r["_pilot_mask"], {d}) for d in pilot_days},
                     "rank_quality_historical": rk.ranking_quality(hist, f"rank_{r['spec']['score']}"),
                     "rank_quality_pilot": rk.ranking_quality(pilot, f"rank_{r['spec']['score']}")}
    out = {
        "label": sp.PILOT_LABEL, "experimental": rk.EXPERIMENTAL, "candidate": "NOT FROZEN",
        "pilot_manifest_sha256": manifest["sha256"], "label_v2_sha256": sp.LABEL_V2_SHA256,
        "grid": {"scores": {**{k: list(v) for k, v in rk.SCORES.items()},
                            rk.CONFIRMED: "(EARLY_LEADER_RANK + pct(ret_z_3) + mean(pct(breakout_distance), "
                                          "pct(vwap_persistence))) / 3"},
                 "k": rk.KS, "floor": rk.FLOOR, "floor_k": rk.FLOOR_KS, "persistence": rk.PERSISTENCE,
                 "n_policies": len(rk.POLICIES), "rank_features": rk.RANK_FEATURES},
        "sample": {"historical": {"rows": len(hist.rows), "asset_sessions": len(hist.sessions),
                                  "evaluable_events": sum(e.evaluable for ev in hist.events for e in ev),
                                  "universe": len(ds2.REFERENCE_ASSETS)},
                   "pilot": {"rows": len(pilot.rows), "asset_sessions": len(pilot.sessions),
                             "evaluable_events": sum(e.evaluable for ev in pilot.events for e in ev),
                             "universe": len(c["universe"]), "rows_live_measured": int(pilot.measured.sum())}},
        "event_rank_study": events_study, "single_feature_top5_lift": feature_lift,
        "policies": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in pol.items()},
        "top3": top, "oct23_topk": oct23, "learning_to_rank": ltr, "one_minute_ranking": one_min,
        "baselines": baselines,
        "access_audit": {"before": audit_before, "historical_last_day": str(max(sel)),
                         "consumed_final": [str(min(final)), str(max(final))],
                         "pilot_sessions_read": access["sessions_read"],
                         "pilot_1m_5m_sessions_read": sorted(set(b5["session_date"]) | set(b1["session_date"])),
                         "after": rd.holdout_audit("after")},
        "elapsed_seconds": None}
    assert max(out["access_audit"]["pilot_sessions_read"]) <= guard.cutoff
    assert max(out["access_audit"]["pilot_1m_5m_sessions_read"]) <= guard.cutoff
    out["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    path = _write(f"pilot_ranking_{guard.cutoff}.json", out)
    print("WRITTEN", path, out["elapsed_seconds"], "s", "TOP3", top3)
    return out


def datagap_stage(workers: int = 7) -> dict:
    """Veri açığı analizi: olumsuz sonucu dondur, pilot taksonomisi, düşük gecikme karşı-olgusu, kaynak matrisi."""
    from app.research.momentum_pilot import datagap as dg
    from app.research.momentum_pilot import deep as dp
    from app.research.momentum_pilot import redesign as rd
    from app.research.momentum_pilot import sources as src
    from app.research.momentum_round2 import dataset as ds2
    started = clock.perf_counter()
    audit_before = rd.holdout_audit("before")
    sel, final = ds2.selection_and_final()
    assert str(max(sel)) == "2026-09-25" and max(sel) < min(final)
    ctx = load_pilot_context(workers)
    p, events, pilot_s = ctx["p"], ctx["events"], ctx["pilot"]
    pb5 = ctx["b5"][ctx["b5"]["session_date"].isin(pilot_s)]
    pb1 = ctx["b1"][ctx["b1"]["session_date"].isin(pilot_s)]
    dp.measured_visibility(p, pb5)
    latency = dp.latency_table(pb5, pb1)
    neck = rd.bottleneck(p, events)
    tax = dg.taxonomy(neck, news_available=False)
    pilot_panel, pilot_days, access = rd.load_pilot(None)
    vis_fn, med_ns = rd.pilot_visibility(access["probe_bars"])
    pilot = rd.Grid(pilot_panel, pilot_days, vis_fn, "PILOT")
    hist_panel, hist_days = rd.load_historical(list(ds2.REFERENCE_ASSETS))
    hist = rd.Grid(hist_panel, hist_days, rd.estimated_visibility(med_ns), "HISTORICAL_DEVELOPMENT")
    cf = dg.latency_counterfactual(p, events, ctx["cand"], pilot, dg.frozen_redesign_masks(hist, pilot))
    evidence = {n: dg.file_sha(sp.RUNS / n) for n in ("pilot_deep_2026-10-30.json", "pilot_redesign_2026-10-30.json",
                                                      "pilot_ranking_2026-10-30.json")}
    frozen = dg.freeze_manifest(dg.manifest_body(ctx["manifest"]["sha256"], latency, evidence,
                                                 datetime.now(timezone.utc).isoformat()))
    coverage = int(pb5.loc[pb5["identity_check"] == "MATCH", "symbol"].isin(ctx["config"]["universe"]).groupby(
        pb5["symbol"]).any().sum())
    out = {
        "label": sp.PILOT_LABEL, "candidate": "NONE", "pilot_manifest_sha256": ctx["manifest"]["sha256"],
        "data_gap_manifest": frozen, "measured_latency": latency,
        "pilot_failure_taxonomy": tax, "addressable": dg.addressable(tax),
        "lead_bottleneck_counts": neck["counts"],
        "low_latency_counterfactual": cf,
        "news_kap_audit": {"status": "NO_LOCAL_ARCHIVE_FOR_PILOT_SESSIONS",
                           "searched": ["repo files (news/kap json/jsonl/sqlite/csv/pkl)",
                                        "news providers are live fetchers (Foreks RSS, Google News RSS, Yahoo news)",
                                        "news analyses live in Firestore -> not accessed by policy"],
                           "events": [], "fabricated": False},
        "source_spec": src.spec(),
        "provider_matrix": dg.provider_matrix(latency, coverage, len(ctx["config"]["universe"])),
        "decision": dg.decide(cf, tax),
        "access_audit": {"before": audit_before, "historical_last_day": str(max(sel)),
                         "consumed_final": [str(min(final)), str(max(final))],
                         "pilot_sessions_read": access["sessions_read"], "after": rd.holdout_audit("after")},
        "elapsed_seconds": None}
    assert max(out["access_audit"]["pilot_sessions_read"]) <= ctx["guard"].cutoff
    out["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    path = _write(f"pilot_datagap_{ctx['guard'].cutoff}.json", out)
    print("WRITTEN", path, out["elapsed_seconds"], "s", out["decision"])
    return out


def main(argv: list[str]):
    stage = argv[0] if argv else ""
    if stage == "datagap":
        datagap_stage()
        return
    if stage == "ranking":
        ranking_stage()
        return
    if stage == "redesign":
        redesign_stage()
        return
    if stage == "split":
        split_stage()
    elif stage == "analyze":
        analyze_stage()
    elif stage == "deep":
        deep_stage()
    elif stage == "mobile":
        mobile_stage(argv[1] if len(argv) > 1 else None)
    else:
        raise SystemExit("aşama: split | analyze | deep | mobile <db>")


if __name__ == "__main__":
    main(sys.argv[1:])
