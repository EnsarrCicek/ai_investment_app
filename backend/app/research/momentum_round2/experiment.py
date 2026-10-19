"""Momentum Round 2 — öznitelik yeniden tasarımı, walk-forward seçim, dokunulmamış final dilim.

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_round2.experiment <stage>

Aşamalar: ext → r1feat → xs → equivalence → diagnose → walkforward → final → ktlev

* Round 1 öznitelikleri üretim `compute_features` ile (Round 1 önbelleği; yeni varlıklar için aynı fonksiyon),
  yeni öznitelikler `extended_features.bar_features` (nedensel, üretim `extended_snapshot` ile aynı), kesitsel bağlam
  `cross_section` (aynı anın referans paneli, kendisi hariç), kurallar `two_stage.SessionTracker`.
* Seçim yalnız Round 1 evreni × seçim seansları (30.07–25.09) walk-forward katlarıyla. Round 1 holdout'u seçimde YOK.
* Final: Round 1'de hiç kullanılmamış varlıklar × en son seanslar, YALNIZ BİR KEZ (dondurulmuş hash).
* KTLEV hiçbir seçimde yok; dondurmadan sonra raporlanır.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import random
import sys
import time as clock
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_calibration import experiment as r1x
from app.research.momentum_calibration.metrics import base_rate
from app.research.momentum_round2 import dataset as ds
from app.research.momentum_round2.metrics import brief, lead_fraction, run_low, summarize2
from app.services.momentum import cross_section as xsec
from app.services.momentum import extended_features as xf
from app.services.momentum.early_momentum_engine import DEFAULT_CONFIG, FeatureSnapshot, classify_raw
from app.services.momentum.two_stage import SessionTracker, TwoStageConfig

PRIMARY_X, PRIMARY_E = r1x.PRIMARY_X, r1x.PRIMARY_E
# Round 1 FINAL_CANDIDATE (C5_PERSIST_3) — koda sabitlenmiş; hash Round 1 dondurma kaydıyla aynı olmalı.
ROUND1_FINAL = r1x.config_for("F1", {**r1x.CANDIDATES["C5_PERSIST_3"][1], "relvol_cap": 12.9})
ROUND1_FINAL_SHA = "00ae932221aa53ba7a94a6e258c30d3daeee855d153a6c0025cd6f7cad814fab"
assert r1x.config_hash(ROUND1_FINAL) == ROUND1_FINAL_SHA, "Round 1 dondurulmuş yapılandırması değişmiş"
XS_FIELDS = {"xs_ret": "ret_z_3", "xs_vol": "relvol_3", "xs_acc": "accel"}

# --- Seçim kuralı (sonuçlar görülmeden sabitlendi) ---
# Uygunluk: walk-forward doğrulama bloklarının BİRLEŞİMİNDE tümü + katların ≥2/3'ünde STRONG kesinlik > WATCH.
SELECTION_CONSTRAINTS = {"min_strong_alerts": 10, "strong_precision_gt_watch": True, "max_strong_fpr": 0.05,
                         "max_watch_fpr": 0.25, "min_watch_recall": 0.40, "min_strong_recall": 0.20,
                         "min_folds_strong_gt_watch": 2}
# Amaç: en düşük WATCH medyan lead_fraction; eşitlikte yüksek STRONG kesinlik. (Tek bileşik skor YOK.)
# --- Final dokunulmamış dilim geçme ölçütü (dondurmadan ÖNCE sabitlendi) ---
FINAL_CRITERIA = {"strong_min_alerts": 10, "strong_precision_vs_base": 2.0, "strong_max_fpr": 0.05,
                  "strong_min_recall": 0.25, "strong_precision_gt_watch": True, "strong_max_lead": 0.70,
                  "watch_min_recall": 0.40, "watch_max_fpr": 0.25, "watch_precision_vs_base": 1.5,
                  "watch_max_lead": 0.50}

_R1 = ("r1",)
_BASE = {"watch_k": 2, "watch_n": 3, "strong_k": 3, "strong_n": 3}
_ACC = {**_BASE, "use_accel": True}
_TWO = {**_ACC, "use_rel": True, "use_xs": True, "strong_confirm": True, "strong_k": 2}
CANDIDATES: dict[str, dict | tuple] = {
    "R2_C0_ROUND1_FINAL": _R1,
    "R2_C1_STAGED_W2OF3": _BASE,
    "R2_C2_ACCEL": _ACC,
    "R2_C3_REL": {**_BASE, "use_rel": True},
    "R2_C4_XS": {**_BASE, "use_xs": True},
    "R2_C5_ACCEL_REL": {**_ACC, "use_rel": True},
    "R2_C6_ACCEL_XS": {**_ACC, "use_xs": True},
    "R2_C7_ACCEL_REL_XS": {**_ACC, "use_rel": True, "use_xs": True},
    "R2_C8_TWO_STAGE": _TWO,
    "R2_C9_GAP": {**_TWO, "use_gap": True},
    "R2_C10_VOLACC": {**_TWO, "use_volacc": True},
    "R2_C11_STRUCT_QUALITY": {**_TWO, "strong_structure_quality": True},
    "R2_C12_REVERSAL": {**_TWO, "use_reversal": True},
    "R2_C13_REGIME": {**_TWO, "use_regime": True},
    "R2_C14_LOCKED_REGIME": {**_TWO, "use_locked_fallback": True},
    "R2_C15_ALL": {**_TWO, "use_gap": True, "use_volacc": True, "strong_structure_quality": True,
                   "use_reversal": True, "use_regime": True, "use_locked_fallback": True},
}


def two_stage_config(name: str) -> TwoStageConfig | None:
    spec = CANDIDATES[name]
    return None if spec == _R1 else TwoStageConfig(**spec)


def candidate_hash(name: str) -> str:
    cfg = two_stage_config(name)
    payload = {"name": name, "round1": json.loads(ROUND1_FINAL.model_dump_json()),
               "extended": json.loads(xf.EXT_DEFAULT.model_dump_json()),
               "two_stage": json.loads(cfg.model_dump_json()) if cfg else None,
               "cross_section": {"min_universe": xsec.MIN_UNIVERSE, "shock_median": xsec.SHOCK_MEDIAN_MOVE_PCT,
                                 "shock_rv": xsec.SHOCK_BENCH_RV_RATIO, "reference": list(ds.REFERENCE_ASSETS)}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- dosyalar
def write_json(name, payload):
    ds.RUNS.mkdir(parents=True, exist_ok=True)
    (ds.RUNS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def read_json(name):
    return json.loads((ds.RUNS / name).read_text(encoding="utf-8"))


def save_pkl(name, obj):
    ds.RUNS.mkdir(parents=True, exist_ok=True)
    with (ds.RUNS / name).open("wb") as f:
        pickle.dump(obj, f)


def load_pkl(name):
    with (ds.RUNS / name).open("rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------- genişletilmiş öznitelikler
def eval_cutoff(t: datetime, delay: int) -> pd.Timestamp:
    return pd.Timestamp(t - timedelta(minutes=delay + 5))


def ext_rows_for_day(data, bench, day: date, delay: int) -> list[dict]:
    end = datetime.combine(day, datetime.max.time(), tzinfo=ISTANBUL_TZ)
    day_bars, prior = xf.split_window(r1ds.window_for(data, day), end, day)
    if day_bars.empty:
        return []
    base = xf.build_baseline(prior)
    bday, bprior = xf.split_window(r1ds.window_for(bench, day), end, day)
    bprev = float(bprior["Close"].iloc[-1]) if not bprior.empty else None
    feats = xf.bar_features(day_bars, base, bday if bprev else None, bprev, xf.bench_sigma(bprior) if bprev else None)
    if feats.empty:  # önceki seans yok (ör. uzun işlem durdurması): öznitelik yok
        return []
    starts = day_bars.index
    out = []
    for t in r1x.eval_times(day, delay):
        k = int(np.searchsorted(starts, eval_cutoff(t, delay), side="right"))
        if k == 0:
            continue
        row = feats.iloc[k - 1].to_dict()
        out.append({"symbol": data.symbol, "day": day, "t": t, **row})
    return out


def _ext_worker(args):
    symbol, days, delay = args
    data, bench = r1ds.load(symbol), r1ds.load(ds.BENCHMARK)
    have = set(data.bars.index.date)
    rows = []
    for day in days:
        if day in have:
            rows.extend(ext_rows_for_day(data, bench, day, delay))
    return rows


def compute_ext(symbols, days, delay, workers=7) -> pd.DataFrame:
    started = clock.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(_ext_worker, [(s, days, delay) for s in symbols]):
            rows.extend(part)
    df = pd.DataFrame(rows)
    print(f"ext d{delay}: {len(symbols)} varlık, {len(df)} satır, {clock.perf_counter() - started:.0f} sn",
          flush=True)
    return df


# ---------------------------------------------------------------- Round 1 öznitelikleri (yeni varlıklar)
def compute_r1(symbols, variant, delay, days, workers=7):
    started = clock.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(r1x._asset_features, [(s, variant, delay, days) for s in symbols]):
            rows.extend(part)
    print(f"r1 {variant} d{delay}: {len(symbols)} varlık, {len(rows)} satır, "
          f"{clock.perf_counter() - started:.0f} sn", flush=True)
    return rows


# ---------------------------------------------------------------- kesitsel bağlam
def add_cross_section(ext: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    """Her satıra aynı t'deki referans paneline göre (kendisi hariç) yüzdelik + rejim ekler."""
    panel = {t: g for t, g in ref.groupby("t")}
    regimes = {}
    for t, g in panel.items():
        rv = g["bench_rv_ratio"].dropna()
        regimes[t] = xsec.market_regime(dict(zip(g["symbol"], g["session_ret_pct"])),
                                        float(rv.median()) if len(rv) else None)
    cols = {k: [] for k in XS_FIELDS}
    reg = {"regime": [], "breadth": [], "median_session_move_pct": []}
    for row in ext.itertuples(index=False):
        g = panel.get(row.t)
        for xs_name, src in XS_FIELDS.items():
            if g is None:
                cols[xs_name].append(None)
                continue
            vals = [None if pd.isna(v) else float(v) for s, v in zip(g["symbol"], g[src]) if s != row.symbol]
            val = getattr(row, src)
            cols[xs_name].append(xsec.percentile_against(None if pd.isna(val) else float(val), vals))
        rg = regimes.get(row.t, {})
        for k in reg:
            reg[k].append(rg.get(k))
    out = ext.copy()
    for k, v in {**cols, **reg}.items():
        out[k] = v
    return out


# ---------------------------------------------------------------- birleştirme ve sınıflandırma
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def merge_rows(r1_rows: list[dict], ext: pd.DataFrame) -> list[dict]:
    ext_map = {(r["symbol"], r["t"]): r for r in ext.to_dict("records")}
    merged = []
    for r in r1_rows:
        e = ext_map.get((r["symbol"], r["t"]), {})
        snap = FeatureSnapshot(r["status"], None, {}, r["components"], {"session_return_pct": r["session_return_pct"]},
                               r["persistent"], r["data_gap"])
        lvl = classify_raw(snap, ROUND1_FINAL)[0]
        f = {k: _clean(v) for k, v in e.items() if k not in ("symbol", "day", "t")}
        merged.append({**r, **f, "r1_level": lvl if r["status"] == ma.STATUS_OK else ma.LEVEL_NONE,
                       "r1_price_impulse": (r["components"] or {}).get("price_impulse")})
    return merged


def classify_two_stage(rows: list[dict], cfg: TwoStageConfig) -> list[dict]:
    out = []
    trackers: dict[tuple, SessionTracker] = {}
    for r in sorted(rows, key=lambda r: (r["symbol"], r["t"])):
        tr = trackers.setdefault((r["symbol"], r["day"]), SessionTracker(cfg))
        f = r if r["status"] == ma.STATUS_OK else {"r1_level": ma.LEVEL_NONE}
        level, _ = tr.step(f)
        out.append({**r, "final_level": level})
    return out


def classify(name: str, rows: list[dict]) -> list[dict]:
    cfg = two_stage_config(name)
    if cfg is None:
        return r1x.classify_rows(rows, ROUND1_FINAL)
    return classify_two_stage(rows, cfg)


_RUNLOW: dict = {}


def evaluate(name, rows, days, x=PRIMARY_X, e=PRIMARY_E):
    days = set(days)
    classified = classify(name, [r for r in rows if r["day"] in days])
    labeled, sessions = r1x.attach_labels(classified, days)
    for k in sessions:
        if k not in _RUNLOW:
            if k[0] not in r1x._BARS_CACHE:
                r1x._BARS_CACHE[k[0]] = r1ds.load(k[0]).bars
            _RUNLOW[k] = run_low(r1x._BARS_CACHE[k[0]], k[1])
    res = {"name": name, "base_rate": base_rate(labeled, x),
           "watch": summarize2(labeled, sessions, _RUNLOW, ma.LEVEL_WATCH, x, e),
           "strong": summarize2(labeled, sessions, _RUNLOW, ma.LEVEL_STRONG, x, e)}
    return res, labeled, sessions


def brief_res(res):
    return {"name": res["name"], "base_rate": res["base_rate"], "watch": brief(res["watch"]),
            "strong": brief(res["strong"])}


def eligible(pooled: dict, fold_results: list[dict], min_folds: int | None = None) -> tuple[bool, dict]:
    c = SELECTION_CONSTRAINTS
    w, s = pooled["watch"], pooled["strong"]
    checks = {"min_strong_alerts": s["alert_sessions"] >= c["min_strong_alerts"],
              "strong_precision_gt_watch": (s["precision"] or 0) > (w["precision"] or 0),
              "max_strong_fpr": (s["false_positive_rate"] if s["false_positive_rate"] is not None else 1)
              <= c["max_strong_fpr"],
              "max_watch_fpr": (w["false_positive_rate"] if w["false_positive_rate"] is not None else 1)
              <= c["max_watch_fpr"],
              "min_watch_recall": (w["recall"] or 0) >= c["min_watch_recall"],
              "min_strong_recall": (s["recall"] or 0) >= c["min_strong_recall"],
              "folds_strong_gt_watch": sum((f["strong"]["precision"] or 0) > (f["watch"]["precision"] or 0)
                                           for f in fold_results) >= (c["min_folds_strong_gt_watch"]
                                                                      if min_folds is None else min_folds)}
    return all(checks.values()), checks


def choose(table: dict[str, dict]) -> str | None:
    ok = [n for n, v in table.items() if v["eligible"]]
    ok.sort(key=lambda n: (table[n]["pooled"]["watch"]["lead_fraction_median"] or 1.0,
                           -(table[n]["pooled"]["strong"]["precision"] or 0)))
    return ok[0] if ok else None


# ---------------------------------------------------------------- teşhis
def _entry_lead(r, outcome, low):
    lab = r["label"]
    return lead_fraction(lab.entry, low, outcome.high) if lab.entry is not None else None


def diagnose(rows, sel_days):
    """Round 1 final (C5) için olay seanslarında bileşen bazlı gecikme analizi."""
    res, labeled, sessions = evaluate("R2_C0_ROUND1_FINAL", rows, sel_days)
    thr = ROUND1_FINAL.evidence_threshold
    by_session = defaultdict(list)
    for r in labeled:
        by_session[(r["symbol"], r["day"])].append(r)
    events = {k: o for k, o in sessions.items() if o.max_runup >= PRIMARY_E}
    reqs = {
        "price_impulse": lambda r, c: (c.get("price_impulse") or -1) >= thr,
        "price_impulse_strong": lambda r, c: (c.get("price_impulse") or -1) >= ROUND1_FINAL.strong_price_impulse,
        "volume": lambda r, c: (c.get("volume_anomaly") or -1) >= thr,
        "breakout": lambda r, c: (c.get("breakout") or -1) >= thr,
        "range": lambda r, c: (c.get("range_expansion") or -1) >= thr,
        "vwap": lambda r, c: (c.get("vwap") or -1) >= thr,
        "reversal": lambda r, c: (c.get("reversal") or -1) >= thr,
        "structure_any": lambda r, c: any((c.get(k) or -1) >= thr for k in ("breakout", "range_expansion", "vwap")),
        "persistent": lambda r, c: bool(r["persistent"]),
        "raw_watch": lambda r, c: r["r1_level"] in (ma.LEVEL_WATCH, ma.LEVEL_STRONG),
        "raw_strong": lambda r, c: r["r1_level"] == ma.LEVEL_STRONG,
        "confirmed_watch": lambda r, c: r["final_level"] in (ma.LEVEL_WATCH, ma.LEVEL_STRONG),
        "confirmed_strong": lambda r, c: r["final_level"] == ma.LEVEL_STRONG,
        "accel_trigger": lambda r, c: (r.get("accel") or -9) >= 0.5 and (r.get("accel_pos_3") or 0) >= 2,
        "rel_strength_z3_ge1": lambda r, c: (r.get("rel_ret_z_3") or -9) >= 1.0,
        "xs_ret_top10pct": lambda r, c: (r.get("xs_ret") or -1) >= 0.90,
        "vol_accel_pos": lambda r, c: (r.get("vol_accel") or -9) > 0 and (r.get("relvol_3") or 0) >= 1.0,
        "gap_follow_through": lambda r, c: (r.get("gap_pct") or -9) >= 1.0 and (r.get("gap_follow_z") or -9) >= 1.0,
        "vwap_reclaim": lambda r, c: r.get("vwap_reclaim") is True,
        "locked_regime": lambda r, c: bool(r.get("recent_locked_regime")),
        "baseline_unavailable": lambda r, c: r["status"] == ma.STATUS_OK and c.get("price_impulse") is None,
    }
    per_event = []
    for k, o in events.items():
        low = _RUNLOW[k]
        items = [r for r in by_session[k] if r["t"] <= o.high_time]
        first = {}
        for name, fn in reqs.items():
            hit = next((r for r in items if r["status"] == ma.STATUS_OK and fn(r, r["components"] or {})), None)
            lead = _entry_lead(hit, o, low) if hit else None
            first[name] = (hit["t"].strftime("%H:%M"), round(lead, 3) if lead is not None else None) if hit else None
        cw, cs = first["confirmed_watch"], first["confirmed_strong"]
        if cw is None:
            cat = "NO_ALERT_BEFORE_HIGH"
        elif (cw[1] if cw[1] is not None else 1) >= 0.5:
            cat = "LATE_WATCH"
        elif cs is None:
            cat = "WATCH_NO_STRONG"
        elif (cs[1] if cs[1] is not None else 1) >= 0.5:
            cat = "LATE_STRONG"
        else:
            cat = "EARLY_OK"
        # Darboğaz: ham WATCH koşullarından (fiyat, katılım|yapı, skor) en geç sağlanan; ham WATCH'tan sonra
        # doğrulama gelmediyse veya geç geldiyse süreklilik (3/3) gecikmesi.
        part = [first[n] for n in ("volume", "structure_any") if first[n]]
        part_first = min(part, key=lambda x: x[0]) if part else None
        if first["price_impulse"] is None:
            bottleneck = "never:price_impulse"
        elif part_first is None:
            bottleneck = "never:participation_or_structure"
        elif first["raw_watch"] is None:
            bottleneck = "score_below_watch"
        elif cw is None or cw[0] > first["raw_watch"][0]:
            bottleneck = "persistence_3of3"
        else:
            bottleneck = ("price_impulse" if first["price_impulse"][0] >= part_first[0]
                          else "participation_or_structure")
        per_event.append({"symbol": k[0], "day": str(k[1]), "max_runup_pct": round(o.max_runup * 100, 2),
                          "high_time": o.high_time.strftime("%H:%M"), "category": cat, "bottleneck": bottleneck,
                          "first": first})
    cats = defaultdict(int)
    bott = defaultdict(int)
    for p in per_event:
        cats[p["category"]] += 1
        if p["category"] != "EARLY_OK":
            bott[p["bottleneck"]] += 1
    comp_lead = {}
    for name in reqs:
        vals = [p["first"][name][1] for p in per_event if p["first"][name] and p["first"][name][1] is not None]
        comp_lead[name] = {"events_reached_before_high": len(vals),
                           "median_lead_at_first": round(float(np.median(vals)), 3) if vals else None}
    by_cat = {}
    for cat in cats:
        items = [p for p in per_event if p["category"] == cat]
        by_cat[cat] = {}
        for name in reqs:
            vals = [p["first"][name][1] for p in items if p["first"][name] and p["first"][name][1] is not None]
            by_cat[cat][name] = {"share_before_high": round(sum(1 for p in items if p["first"][name]) / len(items), 3),
                                 "median_lead_at_first": round(float(np.median(vals)), 3) if vals else None}
    missed = sorted([p for p in per_event if p["category"] in ("NO_ALERT_BEFORE_HIGH", "LATE_WATCH")],
                    key=lambda p: -p["max_runup_pct"])[:15]
    persist_delay = [(datetime.strptime(p["first"]["confirmed_watch"][0], "%H:%M")
                      - datetime.strptime(p["first"]["raw_watch"][0], "%H:%M")).seconds / 60
                     for p in per_event if p["first"]["raw_watch"] and p["first"]["confirmed_watch"]]
    return {"events": len(events), "categories": dict(cats), "bottlenecks_non_early": dict(bott),
            "component_first_lead": comp_lead, "component_by_category": by_cat,
            "persistence_delay_minutes_median": float(np.median(persist_delay)) if persist_delay else None,
            "top_missed": missed, "round1_on_selection": brief_res(res)}


def correlation_report(rows):
    ok = [r for r in rows if r["status"] == ma.STATUS_OK and r["components"]]
    rng = random.Random(7)
    sample = rng.sample(ok, min(60000, len(ok)))
    comp_names = ("price_impulse", "volume_anomaly", "breakout", "range_expansion", "vwap", "reversal")
    comp = pd.DataFrame([{k: r["components"].get(k) for k in comp_names} for r in sample], dtype=float)
    cont_names = ("price_z", "ret_z_3", "ret_z_12", "breakout_dist_atr", "range_ratio", "vwap_dist_pct", "relvol_3",
                  "accel", "slope_6", "rel_ret_z_3", "xs_ret", "vol_accel", "session_ret_z", "gap_follow_z")
    cont = pd.DataFrame([{k: r.get(k) for k in cont_names} for r in sample], dtype=float)
    comp_corr = comp.corr(method="spearman").round(3)
    cont_corr = cont.corr(method="spearman").round(3)
    fire = comp >= ROUND1_FINAL.evidence_threshold
    cofire = {}
    for a in comp_names:
        for b in comp_names:
            if a < b:
                both, either = (fire[a] & fire[b]).sum(), (fire[a] | fire[b]).sum()
                cofire[f"{a}|{b}"] = {"jaccard": round(both / either, 3) if either else None,
                                      "p_b_given_a": round(both / fire[a].sum(), 3) if fire[a].sum() else None,
                                      "p_a_given_b": round(both / fire[b].sum(), 3) if fire[b].sum() else None}
    redundant = [(a, b, float(cont_corr.loc[a, b])) for i, a in enumerate(cont_names) for b in cont_names[i + 1:]
                 if abs(cont_corr.loc[a, b]) >= 0.6]
    redundant += [(a, b, float(comp_corr.loc[a, b])) for i, a in enumerate(comp_names) for b in comp_names[i + 1:]
                  if abs(comp_corr.loc[a, b]) >= 0.6]
    return {"n": len(sample), "component_spearman": comp_corr.to_dict(), "continuous_spearman": cont_corr.to_dict(),
            "component_cofire": cofire, "redundant_pairs_abs_rho_ge_0.6": redundant,
            "firing_rate": {k: round(float(fire[k].mean()), 4) for k in comp_names}}


def _same(a, b) -> bool:
    a = None if (a is None or (isinstance(a, float) and np.isnan(a))) else a
    b = None if (b is None or (isinstance(b, float) and np.isnan(b))) else b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
        return bool(a) == bool(b)
    return abs(float(a) - float(b)) < 1e-9


def equivalence(sel_days, n_ext=300, n_xs=300, n_sessions=150) -> dict:
    """Nedensellik/eşdeğerlik denetimi (yalnız SEÇİM seansları; final dilime bakılmaz).

    A) araştırma satırı (tam gün hesaplanıp T'ye eşlenen) == üretim `extended_snapshot` tam pencereyle
    B) == üretim `extended_snapshot` FİZİKSEL olarak T'deki kesimde kırpılmış varlık + benchmark verisiyle
    C) kesitsel yüzdelik == aynı t'deki panelden yeniden hesap (kendisi hariç; başka t'nin satırı yok)
    D) iki aşamalı durum makinesi: seansın ilk j değerlendirmesiyle çalıştırılan düzey == tam seanstaki j. düzey
    """
    rng = random.Random(20261019)
    sel = set(sel_days)
    ext = load_pkl("ext_ref_d15.pkl")
    ext = ext[ext["day"].isin(sel)].reset_index(drop=True)
    bench = r1ds.load(ds.BENCHMARK)
    out = {}
    mism_a = mism_b = 0
    for i in rng.sample(range(len(ext)), n_ext):
        row = ext.iloc[i]
        data = r1ds.load(row["symbol"])
        t = row["t"].to_pydatetime()
        win, bwin = r1ds.window_for(data, row["day"]), r1ds.window_for(bench, row["day"])
        cut = eval_cutoff(t, 15)
        snap_a = xf.extended_snapshot(win, t, benchmark_bars=bwin)
        snap_b = xf.extended_snapshot(win[win.index <= cut], t, benchmark_bars=bwin[bwin.index <= cut])
        for col, fv in snap_a.items():
            if not _same(row[col], fv.value):
                mism_a += 1
                print("MISMATCH_A", row["symbol"], row["t"], col, row[col], fv.value)
            if not _same(fv.value, snap_b[col].value):
                mism_b += 1
                print("MISMATCH_B", row["symbol"], row["t"], col, fv.value, snap_b[col].value)
    out["A_research_vs_production"] = {"checked": n_ext, "mismatches": mism_a}
    out["B_full_vs_physically_truncated"] = {"checked": n_ext, "mismatches": mism_b}
    rel_cols = [c for c in ext.columns if c.startswith("rel_") and not c.endswith("__n")]
    out["benchmark_relative_columns_checked"] = rel_cols
    merged = [r for r in _rows("ref") if r["day"] in sel]
    by_t = defaultdict(list)
    for r in ext.itertuples(index=False):
        by_t[r.t].append(r)
    mism_c = 0
    for r in rng.sample(merged, n_xs):
        panel = by_t[r["t"]]
        if any(p.t != r["t"] for p in panel):
            mism_c += 1
        for xs_name, src in XS_FIELDS.items():
            vals = [None if pd.isna(getattr(p, src)) else float(getattr(p, src)) for p in panel
                    if p.symbol != r["symbol"]]
            expect = xsec.percentile_against(r.get(src), vals)
            if not _same(expect, r.get(xs_name)):
                mism_c += 1
                print("MISMATCH_C", r["symbol"], r["t"], xs_name, expect, r.get(xs_name))
    out["C_cross_section_same_timestamp"] = {"checked": n_xs, "mismatches": mism_c}
    sessions = defaultdict(list)
    for r in merged:
        sessions[(r["symbol"], r["day"])].append(r)
    keys = rng.sample(sorted(sessions), n_sessions)
    mism_d = checked_d = 0
    for name in ("R2_C8_TWO_STAGE", "R2_C15_ALL"):
        cfg = two_stage_config(name)
        for k in keys:
            items = sorted(sessions[k], key=lambda r: r["t"])
            full = [r["final_level"] for r in classify_two_stage(items, cfg)]
            for j in rng.sample(range(1, len(items) + 1), min(5, len(items))):
                checked_d += 1
                if classify_two_stage(items[:j], cfg)[-1]["final_level"] != full[j - 1]:
                    mism_d += 1
                    print("MISMATCH_D", name, k, j)
    out["D_two_stage_prefix"] = {"checked": checked_d, "mismatches": mism_d}
    out["total_mismatches"] = mism_a + mism_b + mism_c + mism_d
    print(json.dumps(out, ensure_ascii=False))
    return out


# ---------------------------------------------------------------- aşamalar
def _rows(group: str, delay: int = 15) -> list[dict]:
    return load_pkl(f"merged_{group}_d{delay}.pkl")


def main(stage: str):
    ds.RUNS.mkdir(parents=True, exist_ok=True)
    ref = list(ds.REFERENCE_ASSETS)
    new = list(ds.UNTOUCHED_ASSETS)
    assert ds.HOLDOUT_CASE not in ref and ds.HOLDOUT_CASE not in new and not set(ref) & set(new)
    split = ds.round1_split()
    sel_days, final_days = ds.selection_and_final(split)
    all_days = sel_days + final_days
    ktlev_days = [d for d in final_days if date(2026, 10, 1) <= d <= date(2026, 10, 12)]
    if stage == "ext":
        save_pkl("ext_ref_d15.pkl", compute_ext(ref, all_days, 15))
        save_pkl("ext_new_d15.pkl", compute_ext(new, final_days, 15))
        save_pkl("ext_ktlev_d15.pkl", compute_ext([ds.HOLDOUT_CASE], ktlev_days, 15, workers=1))
        save_pkl("ext_ref_d0.pkl", compute_ext(ref, ktlev_days, 0))
        save_pkl("ext_ktlev_d0.pkl", compute_ext([ds.HOLDOUT_CASE], ktlev_days, 0, workers=1))
        return
    if stage == "r1feat":
        save_pkl("r1_new_F1_d15.pkl", compute_r1(new, "F1", 15, final_days))
        save_pkl("r1_new_F0_d15.pkl", compute_r1(new, "F0", 15, final_days))
        for variant in ("F1", "F0"):
            save_pkl(f"r1_ktlev_{variant}_d15.pkl", compute_r1([ds.HOLDOUT_CASE], variant, 15, ktlev_days, 1))
        save_pkl("r1_ktlev_F1_d0.pkl", compute_r1([ds.HOLDOUT_CASE], "F1", 0, ktlev_days, 1))
        return
    if stage == "xs":
        started = clock.perf_counter()
        ref15 = load_pkl("ext_ref_d15.pkl")
        ref0 = load_pkl("ext_ref_d0.pkl")
        r1_ref = r1x.load_features("F1", 15)
        for group, ext, panel, r1rows in (
                ("ref", ref15, ref15, r1_ref),
                ("new", load_pkl("ext_new_d15.pkl"), ref15, load_pkl("r1_new_F1_d15.pkl")),
                ("ktlev", load_pkl("ext_ktlev_d15.pkl"), ref15, load_pkl("r1_ktlev_F1_d15.pkl"))):
            save_pkl(f"merged_{group}_d15.pkl", merge_rows(r1rows, add_cross_section(ext, panel)))
            print(group, "birleştirildi", f"{clock.perf_counter() - started:.0f} sn", flush=True)
        save_pkl("merged_ktlev_d0.pkl", merge_rows(load_pkl("r1_ktlev_F1_d0.pkl"),
                                                   add_cross_section(load_pkl("ext_ktlev_d0.pkl"), ref0)))
        return
    if stage == "equivalence":
        write_json("equivalence.json", equivalence(sel_days))
        return
    rows = _rows("ref")
    sel_rows = [r for r in rows if r["day"] in set(sel_days)]
    if stage == "diagnose":
        d = diagnose(sel_rows, sel_days)
        c = correlation_report(sel_rows)
        write_json("diagnosis.json", d)
        write_json("correlation.json", c)
        print(json.dumps({k: v for k, v in d.items() if k != "top_missed"}, ensure_ascii=False, indent=1))
        for p in d["top_missed"]:
            print(p["symbol"], p["day"], p["max_runup_pct"], p["high_time"], p["category"], p["bottleneck"],
                  {k: v for k, v in p["first"].items() if v})
        print("REDUNDANT", c["redundant_pairs_abs_rho_ge_0.6"])
        print("FIRING", c["firing_rate"])
        print("COFIRE", json.dumps(c["component_cofire"]))
        return
    if stage in ("walkforward", "final", "ktlev"):
        eq = read_json("equivalence.json") if (ds.RUNS / "equivalence.json").exists() else None
        if not eq or eq.get("total_mismatches") != 0:
            raise SystemExit("eşdeğerlik/nedensellik denetimi temiz değil: sonraki aşamalara geçilmez")
    if stage == "walkforward":
        if (ds.RUNS / "final.json").exists():
            raise SystemExit("final zaten çalıştırıldı; seçim yeniden yapılamaz")
        folds = ds.walk_forward_folds(sel_days)
        val_days = sorted({d for f in folds for d in f["validate"]})
        table = {}
        for name in CANDIDATES:
            fold_res = []
            for f in folds:
                fold_res.append({**brief_res(evaluate(name, sel_rows, f["validate"])[0]), "fold": f["fold"]})
            pooled = brief_res(evaluate(name, sel_rows, val_days)[0])
            train_first = brief_res(evaluate(name, sel_rows, folds[0]["train"])[0])
            ok, checks = eligible(pooled, fold_res)
            table[name] = {"pooled": pooled, "folds": fold_res, "first_train_block": train_first,
                           "eligible": ok, "checks": checks}
            print(name, "uygun" if ok else "uygun değil", json.dumps(pooled, ensure_ascii=False), flush=True)
        # Katlar içinde seçim prosedürünün kendisi: eğitimde seç → sonraki blokta ölç (iyimserlik denetimi)
        procedure = []
        for f in folds:
            train_tab = {}
            for name in CANDIDATES:
                tr = brief_res(evaluate(name, sel_rows, f["train"])[0])
                train_tab[name] = {"pooled": tr, "eligible": eligible(tr, [tr], min_folds=1)[0]}
            pick = choose(train_tab)
            procedure.append({"fold": f["fold"], "picked_on_train": pick,
                              "validate": next((x for x in table[pick]["folds"] if x["fold"] == f["fold"]), None)
                              if pick else None})
        final = choose(table)
        payload = {"folds": [{"fold": f["fold"], "train": [str(f["train"][0]), str(f["train"][-1]), len(f["train"])],
                              "validate": [str(f["validate"][0]), str(f["validate"][-1]), len(f["validate"])]}
                             for f in folds],
                   "selection_constraints": SELECTION_CONSTRAINTS, "final_criteria": FINAL_CRITERIA,
                   "table": table, "procedure": procedure, "final_candidate": final}
        if final:
            cfg = two_stage_config(final)
            payload.update({"frozen_at": str(datetime.now(ISTANBUL_TZ)), "sha256": candidate_hash(final),
                            "two_stage": json.loads(cfg.model_dump_json()) if cfg else None})
        write_json("walkforward.json", payload)
        print("PROCEDURE", json.dumps(procedure, ensure_ascii=False))
        print("FINAL_CANDIDATE", final, payload.get("sha256"))
        return
    if stage == "final":
        if (ds.RUNS / "final.json").exists():
            raise SystemExit("final dilim zaten çalıştırıldı; yeniden çalıştırma/optimizasyon yasak")
        wf = read_json("walkforward.json")
        name = wf["final_candidate"]
        if not name:
            raise SystemExit("dondurulmuş aday yok")
        assert candidate_hash(name) == wf["sha256"], "dondurulmuş aday değişmiş"
        new_rows = _rows("new")
        res, labeled, sessions = evaluate(name, new_rows, final_days)
        w, s = res["watch"], res["strong"]
        c = FINAL_CRITERIA
        br = res["base_rate"] or 1
        checks = {"strong_min_alerts": s["alert_sessions"] >= c["strong_min_alerts"],
                  "strong_precision_vs_base": (s["precision"] or 0) >= c["strong_precision_vs_base"] * br,
                  "strong_max_fpr": (s["false_positive_rate"] if s["false_positive_rate"] is not None else 1)
                  <= c["strong_max_fpr"],
                  "strong_min_recall": (s["recall"] or 0) >= c["strong_min_recall"],
                  "strong_precision_gt_watch": (s["precision"] or 0) > (w["precision"] or 0),
                  "strong_max_lead": (s["lead_fraction_median"] if s["lead_fraction_median"] is not None else 1)
                  <= c["strong_max_lead"],
                  "watch_min_recall": (w["recall"] or 0) >= c["watch_min_recall"],
                  "watch_max_fpr": (w["false_positive_rate"] if w["false_positive_rate"] is not None else 1)
                  <= c["watch_max_fpr"],
                  "watch_precision_vs_base": (w["precision"] or 0) >= c["watch_precision_vs_base"] * br,
                  "watch_max_lead": (w["lead_fraction_median"] if w["lead_fraction_median"] is not None else 1)
                  <= c["watch_max_lead"]}
        out = {"name": name, "sha256": wf["sha256"], "sessions": len(sessions), "result": brief_res(res),
               "checks": checks, "verdict": "FINAL PASS" if all(checks.values()) else "FINAL FAIL"}
        # Karşılaştırma (seçimde KULLANILMAZ): aynı dokunulmamış dilimde Old (C0) ve Round 1 final
        old_rows = r1x.classify_rows([r for r in load_pkl("r1_new_F0_d15.pkl") if r["day"] in set(final_days)],
                                     DEFAULT_CONFIG)
        lab, sess = r1x.attach_labels(old_rows, set(final_days))
        for k in sess:
            if k not in _RUNLOW:
                _RUNLOW[k] = run_low(r1x._BARS_CACHE[k[0]], k[1])
        out["old_C0"] = {"base_rate": base_rate(lab, PRIMARY_X),
                         "watch": brief(summarize2(lab, sess, _RUNLOW, ma.LEVEL_WATCH, PRIMARY_X, PRIMARY_E)),
                         "strong": brief(summarize2(lab, sess, _RUNLOW, ma.LEVEL_STRONG, PRIMARY_X, PRIMARY_E))}
        out["round1_final"] = brief_res(evaluate("R2_C0_ROUND1_FINAL", new_rows, final_days)[0])
        # Rejim sağlamlığı ve duyarlılık (yalnız rapor)
        regime_split = {}
        for reg in (xsec.REGIME_NORMAL, xsec.REGIME_SHOCK):
            reg_days = sorted({r["day"] for r in new_rows if r.get("regime") == reg and r["t"].hour == 12
                               and r["t"].minute == 0})
            if reg_days:
                regime_split[reg] = {"days": [str(d) for d in reg_days],
                                     **brief_res(evaluate(name, new_rows, reg_days)[0])}
        out["regime_split_by_noon_regime"] = regime_split
        out["sensitivity"] = {f"x{x}_e{e}": {lvl: {k: summarize2(labeled, sessions, _RUNLOW, lvl, x, e)[k]
                                                   for k in ("precision", "recall", "false_positive_rate",
                                                             "lead_fraction_median")}
                                             for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG)}
                              for x in (0.02, 0.03, 0.05) for e in (0.03, 0.05, 0.08)}
        # İkincil (görülmüş Round 1 holdout'u, research feedback): referans evren × final tarihleri
        out["seen_round1_holdout_feedback"] = {n: brief_res(evaluate(n, rows, final_days)[0])
                                               for n in ("R2_C0_ROUND1_FINAL", name)}
        write_json("final.json", out)
        print(json.dumps({k: v for k, v in out.items() if k != "sensitivity"}, ensure_ascii=False, indent=1))
        return
    if stage == "ktlev":
        wf = read_json("walkforward.json")
        name = wf["final_candidate"]
        assert name and candidate_hash(name) == wf["sha256"]
        data = r1ds.load(ds.HOLDOUT_CASE)
        report = {}
        for label, group, cand in (("FINAL_d15", "ktlev_d15", name), ("FINAL_d0", "ktlev_d0", name),
                                   ("ROUND1_d15", "ktlev_d15", "R2_C0_ROUND1_FINAL")):
            g, delay = group.rsplit("_d", 1)
            rws = classify(cand, load_pkl(f"merged_{g}_d{delay}.pkl"))
            per_day = {}
            for day in ktlev_days:
                items = [r for r in rws if r["day"] == day]
                prev = float(data.bars[data.bars.index.date < day]["Close"].iloc[-1])
                firsts = {}
                for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG):
                    hit = next((r for r in items if r["final_level"] == lvl
                                or (lvl == ma.LEVEL_WATCH and r["final_level"] == ma.LEVEL_STRONG)), None)
                    if hit:
                        price = hit["last_close"]
                        firsts[lvl] = {"eval": hit["t"].strftime("%H:%M"), "price": round(price, 2),
                                       "vs_prev_close_pct": round((price / prev - 1) * 100, 2),
                                       "total_move_done_pct": round((price - 6.62) / (8.80 - 6.62) * 100, 1),
                                       "xs_ret": hit.get("xs_ret"), "accel": hit.get("accel")}
                per_day[str(day)] = firsts
            report[label] = per_day
        old = r1x.classify_rows(load_pkl("r1_ktlev_F0_d15.pkl"), DEFAULT_CONFIG)
        report["OLD_C0_d15"] = {str(day): {lvl: next((r["t"].strftime("%H:%M") for r in old if r["day"] == day and
                                                      (r["final_level"] == lvl or (lvl == ma.LEVEL_WATCH and
                                                       r["final_level"] == ma.LEVEL_STRONG))), None)
                                           for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG)} for day in ktlev_days}
        write_json("ktlev_case.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    raise SystemExit(f"bilinmeyen aşama: {stage}")


if __name__ == "__main__":
    main(sys.argv[1])
