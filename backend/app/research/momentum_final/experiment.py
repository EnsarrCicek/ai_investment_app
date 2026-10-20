"""Erken momentum — dondurulmuş WATCH adayı + dokunulmamış final (TEK SEFER).

Kullanım (backend klasöründen, sırayla):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final.experiment freeze
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final.experiment final
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final.experiment ktlev

* freeze: YALNIZ seçim verisi (referans evren × seçim seansları). Dokunulmamış artefaktlar açılmaz.
* final: dondurulmuş aday + ön koşullar → 37 yeni varlık × final tarihleri, YALNIZ d15, bir kez. Kilit dosyası
  değerlendirmeden ÖNCE yazılır; varsa yeniden çalıştırma reddedilir.
* ktlev: final sonucu yazıldıktan sonra yalnız açıklayıcı vaka (karar dışında).
"""

from __future__ import annotations

import json
import sys
import time as clock
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_final import candidate as cd
from app.research.momentum_round2 import dataset as ds2
from app.research.momentum_round2 import experiment as r2
from app.services.momentum.extended_features import EXT_DEFAULT

HERE = Path(__file__).parent
MANIFEST = HERE / "frozen_candidate.json"
FINAL_LOCK = HERE / "untouched_final.lock"
FINAL_RESULT = HERE / "untouched_final_result.json"
KTLEV_RESULT = HERE / "ktlev_case_result.json"
FINAL_DELAY = 15


def ext_config_sha() -> str:
    return cd.sha256_of(json.loads(EXT_DEFAULT.model_dump_json()))


def candidate_alerts(p: fx.Panel, cand: dict) -> np.ndarray:
    """Dondurulmuş WATCH kuralı (1/1): durum OK ∧ öznitelik tanımlı ∧ öznitelik ≥ eşik."""
    assert cand["comparison"] == ">=" and cand["confirmation"] == [1, 1]
    vals = getattr(p, cand["feature"])
    return p.ok & np.isfinite(vals) & (vals >= cand["threshold"])


# ------------------------------------------------------------------ dondurma
def freeze_stage():
    if ds2.CONSUMED_FINAL or FINAL_RESULT.exists():
        raise SystemExit(au.CONSUMED_FINAL_ERROR + ": bu aday zaten finalde tüketildi; yeni aday yeni final ister")
    with au.candidate_selection():
        _freeze()


def _freeze():
    started = clock.perf_counter()
    rows = fx.load_selection_rows()  # koruma: dokunulmamış varlık/final tarihi → RuntimeError
    p = fx.Panel(rows)
    p.build_labels(FINAL_DELAY)
    wf = fx.walk_forward_feasibility(p, only=(cd.SCENARIO,))[cd.SCENARIO]
    sel_days, _ = fx.selection_scope()
    selection = {"artifact": "momentum_round2/runs/merged_ref_d15.pkl", "assets": len(ds2.REFERENCE_ASSETS),
                 "sessions": len(p.sessions), "days": [str(min(sel_days)), str(max(sel_days))],
                 "scenario": cd.SCENARIO, "folds": len(wf["folds"]), "folds_passing": wf["passes"]}
    cand = cd.build_candidate(wf["folds"], selection, r2.ROUND1_FINAL_SHA, ext_config_sha())
    manifest = cd.freeze(MANIFEST, cand)
    # Seçim dönemi (örneklem içi, yalnız referans) — dondurulmuş eşikle
    m = fr.metrics(candidate_alerts(p, cand), p.sess, p.labels[FINAL_DELAY], fx.X)
    print(json.dumps({"sha256": manifest["sha256"], "candidate": manifest["candidate"], "walk_forward": wf,
                      "selection_in_sample_d15": m, "seconds": round(clock.perf_counter() - started, 1)},
                     ensure_ascii=False, default=str))


# ------------------------------------------------------------------ ön koşullar
def pre_final_assertions() -> dict:
    manifest = cd.load_frozen(MANIFEST)  # yok/bozuk → hata
    cand = manifest["candidate"]
    sel_days, final_days = fx.selection_scope()
    assert "KTLEV" not in ds2.REFERENCE_ASSETS and "KTLEV" not in ds2.UNTOUCHED_ASSETS, "KTLEV kümelerde"
    assert not set(ds2.REFERENCE_ASSETS) & set(ds2.UNTOUCHED_ASSETS), "dokunulmamış varlık seçimde"
    assert not set(sel_days) & final_days and max(sel_days) < min(final_days), "final tarihi seçimde"
    sel = cand["selection"]
    assert sel["folds"] == 3 and sel["folds_passing"] == 3, "walk-forward tamamlanmamış/geçmemiş"
    assert cand["pass_criteria"] == cd.PASS_CRITERIA, "ön-kayıtlı hedef değişmiş"
    assert cand["feasibility_verdict"] == cd.FEASIBILITY_VERDICT
    assert cand["provider_delay_minutes"] == FINAL_DELAY
    assert cand["round1_engine_config_sha256"] == r2.ROUND1_FINAL_SHA, "durum kapısı motor yapılandırması değişmiş"
    assert cand["extended_feature_config_sha256"] == ext_config_sha(), "öznitelik yapılandırması değişmiş"
    missing = [s for s in ds2.UNTOUCHED_ASSETS if not (r1ds.CACHE / f"{s}_5m_60d.pkl").exists()]
    assert not missing, f"önbellek eksik (ağ isteği yapılmaz): {missing}"
    assert not (ds2.RUNS / "final.json").exists()
    return manifest


# ------------------------------------------------------------------ final değerlendirme
def evaluate_final(p, cand: dict) -> dict:
    """YALNIZ d15 etiketleri kurulur (d0 karşılaştırması yok)."""
    assert cand["provider_delay_minutes"] == FINAL_DELAY
    p.build_labels(FINAL_DELAY)
    assert set(p.labels) == {FINAL_DELAY}
    lab = p.labels[FINAL_DELAY]
    base = fx.base_rate(p, FINAL_DELAY)
    watch = candidate_alerts(p, cand)
    strong = fr.confirm(p.strong_raw(fx.R1_FINAL_STRONG), p.seg_start, 3, 3)
    mw = fr.metrics(watch, p.sess, lab, fx.X)
    ms = fr.metrics(strong, p.sess, lab, fx.X)

    def ci(m):
        n_alert, n_ev = m["alert_sessions"], m["events"]
        n_non = len(lab.sess_event) - n_ev
        hits = round(m["precision"] * n_alert) if m["precision"] is not None else 0
        fps = round(m["false_positive_rate"] * n_non) if m["false_positive_rate"] is not None else 0
        return {"precision": cd.wilson(hits, n_alert), "recall": cd.wilson(m["caught_events"], n_ev),
                "false_positive_rate": cd.wilson(fps, n_non),
                "counts": {"precision_hits": hits, "alert_sessions": n_alert, "caught": m["caught_events"],
                           "events": n_ev, "false_positive_sessions": fps, "non_event_sessions": n_non}}
    table = cd.pass_table(mw, base)
    return {"watch": {**mw, "specificity": 1 - mw["false_positive_rate"],
                      "median_first_alert_clock": fx._hm(mw["median_first_alert_minute"])},
            "watch_ci95_wilson": ci(mw), "base_rate": base, "pass_table": table, "verdict": cd.verdict(table),
            "strong_reference": {**ms, "median_first_alert_clock": fx._hm(ms["median_first_alert_minute"])},
            "strong_ci95_wilson": ci(ms),
            "strong_precision_gt_watch": (ms["precision"] or 0) > (mw["precision"] or 0),
            "_watch": watch}


def distributions(p, watch: np.ndarray) -> dict:
    lab = p.labels[FINAL_DELAY]
    uniq, rows = fr.first_alert_rows(watch, p.sess)
    by_asset, by_day = Counter(), defaultdict(lambda: Counter())
    assets = sorted({s for s, _ in p.sessions})
    for s in range(len(p.sessions)):
        sym, day = p.sessions[s]
        by_day[day]["sessions"] += 1
        by_day[day]["events"] += int(lab.sess_event[s])
    for s, i in zip(uniq, rows):
        sym, day = p.sessions[s]
        by_asset[sym] += 1
        by_day[day]["alerts"] += 1
        ev = bool(lab.sess_event[s])
        by_day[day]["false_positives"] += int(not ev)
        by_day[day]["caught"] += int(ev and lab.t_ns[i] <= lab.sess_high_ns[s])
    # Şok günü: o günün değerlendirmelerinin ≥%50'si SHOCK rejiminde (final görülmeden önce sabitlendi)
    row_day = np.array([p.sessions[s][1] for s in p.sess])
    shock_days = {d for d in set(row_day) if p.regime_shock[row_day == d].mean() >= 0.5}
    total = sum(by_asset.values())
    top = by_asset.most_common(3)

    def fpr(days):
        fp = sum(by_day[d]["false_positives"] for d in days)
        non = sum(by_day[d]["sessions"] - by_day[d]["events"] for d in days)
        return {"days": len(days), "false_positives": fp, "non_event_sessions": non,
                "fpr": fp / non if non else None}
    days = sorted(by_day)
    alerts_by_day = {str(d): dict(by_day[d]) for d in days}
    top_day = max(days, key=lambda d: by_day[d]["alerts"])
    return {"assets": len(assets), "assets_with_alert": len(by_asset), "assets_without_alert": len(assets) -
            len(by_asset), "assets_without_alert_list": [a for a in assets if a not in by_asset],
            "top_assets": [{"asset": a, "alert_sessions": n, "share": n / total} for a, n in top],
            "alerts_per_asset": dict(by_asset.most_common()),
            "by_day": alerts_by_day, "top_day": {"day": str(top_day), "alerts": by_day[top_day]["alerts"],
                                                 "share": by_day[top_day]["alerts"] / total if total else None},
            "shock_days": sorted(str(d) for d in shock_days),
            "fpr_shock_days": fpr([d for d in days if d in shock_days]),
            "fpr_normal_days": fpr([d for d in days if d not in shock_days])}


def fn_taxonomy_d15(p, watch: np.ndarray, cand: dict) -> dict:
    """Yalnız d15 bilgisiyle (d0 yok): erken (lead<0.5, tepe öncesi) yakalanmayan olaylar.
    PROVIDER_DELAY / CONFIRMATION_DELAY burada değerlendirilmez (d0 yasak; aday 1/1)."""
    lab = p.labels[FINAL_DELAY]
    lead, before = fx._session_arrays(p, FINAL_DELAY)
    info_ns = p.t15_ns - FINAL_DELAY * au.MIN_NS
    thr, rel, absz = cand["threshold"], p.rel_ret_z_3, p.ret_z_3
    seg = defaultdict(list)
    for i, s in enumerate(p.sess):
        seg[s].append(i)
    prim, anyf, late_alert = Counter(), Counter(), 0
    for s in np.flatnonzero(lab.sess_event):
        idx = np.array(seg[s])
        sym, day = p.sessions[s]
        ms, peak = fx._move_start_ns(sym, day), int(lab.sess_high_ns[s])
        mv = idx[info_ns[idx] > ms]
        early = mv[before[mv] & (lead[mv] < au.LEAD_TARGET)]
        if (watch[early]).any():
            continue
        late_alert += int((watch[mv] & before[mv]).any())
        okr = early[p.ok[early]]
        price_ev = okr[p.price_impulse[okr] >= fx.THR]
        win = mv[before[mv]]
        flags = {
            "BASELINE_UNAVAILABLE": len(win) > 0 and not (p.ok[win] & np.isfinite(rel[win])).any(),
            "ABRUPT_VERTICAL_JUMP": (peak - ms) / au.MIN_NS <= 15,
            "NO_EARLY_PRICE_EVIDENCE": len(price_ev) == 0,
            "BENCHMARK/CROSS_SECTION_GATE": bool((np.nan_to_num(absz[okr], nan=-9) >= thr).any()
                                                 and not (np.nan_to_num(rel[okr], nan=-9) >= thr).any()),
        }
        flags["FEATURE_THRESHOLD"] = len(price_ev) > 0 and not flags["BENCHMARK/CROSS_SECTION_GATE"]
        primary, secondary = au.classify_fn(flags)
        prim[primary] += 1
        for r in [primary, *secondary]:
            anyf[r] += 1
    n = sum(prim.values())
    return {"not_caught_early": n, "of_which_alert_after_lead_0.5_but_before_peak": late_alert,
            "primary": {k: {"count": v, "share": v / n} for k, v in prim.most_common()},
            "any_reason": {k: {"count": v, "share": v / n} for k, v in anyf.most_common()},
            "not_evaluated": ["PROVIDER_DELAY (d0 yasak)", "CONFIRMATION_DELAY (aday 1/1)",
                              "NO_VOLUME_CONFIRMATION (aday hacim şartı içermez)"]}


def prior_attempts(sha: str) -> list[dict]:
    """Kilit yoksa []. Varsa yeniden deneme YALNIZ tüm önceki denemeler aynı SHA ile ve METRİK ÜRETİLMEDEN
    çökmüş (`aborted_before_metrics`) ise mümkündür; aksi halde final tüketilmiş sayılır."""
    if not FINAL_LOCK.exists():
        return []
    try:
        attempts = json.loads(FINAL_LOCK.read_text(encoding="utf-8")).get("attempts", [])
    except ValueError:
        attempts = []
    if not attempts or not all(a.get("status") == "aborted_before_metrics" and a.get("sha256") == sha
                               for a in attempts):
        raise SystemExit("dokunulmamış final zaten tüketildi/başlatıldı; yeniden çalıştırma yasak")
    return attempts


def final_stage():
    if FINAL_RESULT.exists():
        raise SystemExit("dokunulmamış final zaten tüketildi; yeniden çalıştırma yasak")
    if FINAL_LOCK.exists() and not MANIFEST.exists():
        raise SystemExit("kilit var, dondurulmuş aday yok; yeniden çalıştırma yasak")
    manifest = pre_final_assertions()
    cand = manifest["candidate"]
    prior = prior_attempts(manifest["sha256"])
    attempt = {"sha256": manifest["sha256"], "started_at": str(datetime.now(ISTANBUL_TZ)), "status": "running"}
    FINAL_LOCK.write_text(json.dumps({"attempts": [*prior, attempt]}, ensure_ascii=False), encoding="utf-8")
    started = clock.perf_counter()
    _, final_days = fx.selection_scope()
    rows = [r for r in r2.load_pkl("merged_new_d15.pkl") if r["day"] in final_days]  # İLK ve TEK açılış
    syms = {r["symbol"] for r in rows}
    assert syms <= set(ds2.UNTOUCHED_ASSETS) and "KTLEV" not in syms, syms
    p = fx.Panel(rows)
    res = evaluate_final(p, cand)
    watch = res.pop("_watch")
    out = {"sha256": manifest["sha256"], "candidate": cand, "delay_minutes": FINAL_DELAY,
           "scope": {"assets": len(syms), "assets_missing_from_artifact": sorted(set(ds2.UNTOUCHED_ASSETS) - syms),
                     "sessions": len(p.sessions), "rows": len(p.rows),
                     "days": [str(min(final_days)), str(max(final_days))], "n_days": len(final_days),
                     "events": int(p.labels[FINAL_DELAY].sess_event.sum())},
           **res,
           "distribution": distributions(p, watch),
           "fp_taxonomy": fx.fp_taxonomy_v2(p, watch, FINAL_DELAY),
           "fn_taxonomy": fn_taxonomy_d15(p, watch, cand),
           "finished_at": str(datetime.now(ISTANBUL_TZ)), "seconds": round(clock.perf_counter() - started, 1),
           "prior_aborted_attempts": prior}
    FINAL_LOCK.write_text(json.dumps({"attempts": [*prior, {**attempt, "status": "completed"}]}, ensure_ascii=False),
                          encoding="utf-8")
    FINAL_RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("candidate",)}, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ KTLEV (açıklayıcı, karar dışı)
def ktlev_stage():
    if not FINAL_RESULT.exists():
        raise SystemExit("KTLEV vakası yalnız final sonucu yazıldıktan sonra")
    cand = cd.load_frozen(MANIFEST)["candidate"]
    rows = r2.load_pkl("merged_ktlev_d15.pkl")
    p = fx.Panel(rows)
    p.build_labels(FINAL_DELAY)
    lab = p.labels[FINAL_DELAY]
    watch = candidate_alerts(p, cand)
    lead, before = fx._session_arrays(p, FINAL_DELAY)
    per_day = []
    for s, (sym, day) in enumerate(p.sessions):
        idx = np.flatnonzero((p.sess == s) & watch)
        first = int(idx[0]) if len(idx) else None
        per_day.append({"day": str(day), "event": bool(lab.sess_event[s]),
                        "runup_pct": round((lab.sess_high[s] / lab.sess_run_low[s] - 1) * 100, 2),
                        "peak": fx._hhmm(lab.sess_high_ns[s]),
                        "first_watch_visible": fx._hhmm(lab.t_ns[first]) if first is not None else None,
                        "first_watch_value": round(float(p.rel_ret_z_3[first]), 2) if first is not None else None,
                        "lead_fraction": (round(float(lead[first]), 3) if first is not None and before[first]
                                          and np.isfinite(lead[first]) else None),
                        "before_peak": bool(before[first]) if first is not None else None,
                        "alert_rows": int(len(idx))})
    out = {"used_in_verdict": False, "sha256": cd.sha256_of(cand), "days": per_day}
    KTLEV_RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


def main(stage: str):
    {"freeze": freeze_stage, "final": final_stage, "ktlev": ktlev_stage}[stage]()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
