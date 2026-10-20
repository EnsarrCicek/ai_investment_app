"""Erken momentum — fizibilite / Pareto denetimi (YALNIZ seçim verisi; yeni model/öznitelik YOK).

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_feasibility.experiment run

Veri güvenliği:
* Yalnız Round 1 evreni (50 varlık) × seçim seansları (30.07–25.09). Round 2 dokunulmamış varlıkları
  (`merged_new_*`) ve final tarih dilimi OKUNMAZ; `final.json` oluşturulmaz.
* KTLEV yalnız açıklayıcı vaka; hiçbir eşik/ızgara noktası KTLEV ile seçilmez.
* Izgara bir üretim yapılandırması SEÇMEZ: yalnız erişilebilir kesinlik/duyarlılık/YPO/erkenlik yüzeyini ölçer
  (gelecek etiketleri yalnız değerlendirmede, girdi olarak ASLA).
"""

from __future__ import annotations

import itertools
import json
import sys
import time as clock
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_calibration.labels import labels_for_session
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_round2 import dataset as ds2
from app.research.momentum_round2 import experiment as r2

RUNS = ds2.RUNS.parent.parent / "momentum_feasibility" / "runs"
X, E = 0.03, 0.05
DELAYS = (0, 5, 10, 15)
THR = 0.5  # Round 1 kanıt eşiği
WATCH_GRID = {"price": (0.25, 0.375, 0.5, 0.625, 0.75, 1.0), "need_ps": (False, True), "score": (0, 30, 40, 50),
              "accel": (None, 0.0, 0.5, 1.0), "xs": (None, 0.8, 0.9, 0.95), "rel": (None, 1.0),
              "confirm": ((1, 1), (2, 3), (2, 2), (3, 3))}
STRONG_GRID = {"price": (0.5, 0.625, 0.75, 0.875, 1.0), "score": (50, 60, 70), "xs": (None, 0.9),
               "confirm": ((1, 1), (2, 3), (2, 2), (3, 3))}
SINGLE_FEATURES = ("price_z", "ret_z_3", "ret_z_12", "accel", "rel_ret_z_3", "xs_ret", "relvol_3", "session_ret_z",
                   "score")
QUANTILES = (50, 60, 70, 75, 80, 85, 90, 92.5, 95, 96, 97, 98, 98.5, 99, 99.3, 99.5, 99.7, 99.8, 99.9)
R1_FINAL_WATCH = {"price": 0.5, "need_ps": True, "score": 40, "accel": None, "xs": None, "rel": None,
                  "confirm": (3, 3)}


# ------------------------------------------------------------------ veri (yalnız seçim)
def selection_scope() -> tuple[list, set]:
    sel_days, final_days = ds2.selection_and_final()
    assert max(sel_days) < min(final_days)
    return sel_days, set(final_days)


def guarded_load(name: str, loader=None):
    """Round 2 artefakt okuyucusu; dokunulmamış final artefaktları istenirse RuntimeError."""
    return (loader or r2.load_pkl)(au.guard_artifact(name))


def load_selection_rows(loader=None) -> list[dict]:
    """Yalnız referans evren × seçim seansları. Final tarihleri elenir; dokunulmamış varlık görülürse durulur."""
    sel_days, final_days = selection_scope()
    sel = set(sel_days)
    raw = guarded_load("merged_ref_d15.pkl", loader)
    au.guard_rows(raw, ds2.UNTOUCHED_ASSETS, ())  # dokunulmamış varlık: süzme değil, hata
    rows = [r for r in raw if r["day"] in sel]
    au.guard_rows(rows, ds2.UNTOUCHED_ASSETS, final_days)
    assert {r["symbol"] for r in rows} <= set(ds2.REFERENCE_ASSETS)
    return rows


def _f(rows, key, sub=None):
    out = np.full(len(rows), np.nan)
    for i, r in enumerate(rows):
        v = (r.get(sub) or {}).get(key) if sub else r.get(key)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            out[i] = float(v)
    return out


class Panel:
    """Satır dizileri (seans, zaman sıralı) + gecikme senaryosu başına etiketler."""

    def __init__(self, rows: list[dict]):
        rows = sorted(rows, key=lambda r: (r["symbol"], r["t"]))
        self.rows = rows
        keys = [(r["symbol"], r["day"]) for r in rows]
        self.sessions = list(dict.fromkeys(keys))
        sid = {k: i for i, k in enumerate(self.sessions)}
        self.sess = np.array([sid[k] for k in keys])
        first = {}
        for i, s in enumerate(self.sess):
            first.setdefault(s, i)
        self.seg_start = np.array([first[s] for s in self.sess])
        self.ok = np.array([r["status"] == "OK" for r in rows])
        for k in ("price_impulse", "volume_anomaly", "breakout", "range_expansion", "vwap", "reversal"):
            setattr(self, k, _f(rows, k, "components"))
        self.persistent = np.array([bool(r["persistent"]) for r in rows])
        self.data_gap = np.array([bool(r["data_gap"]) for r in rows])
        for k in ("price_z", "ret_z_3", "ret_z_12", "accel", "accel_pos_3", "rel_ret_z_3", "xs_ret", "relvol_3",
                  "session_ret_z", "gap_pct", "breakout_dist_atr", "vol_accel", "vwap_reclaim",
                  "median_session_move_pct"):
            setattr(self, k, _f(rows, k))
        self.regime_shock = np.array([r.get("regime") == "SHOCK" for r in rows])
        self.locked = np.array([bool(r.get("recent_locked_regime")) for r in rows])
        self.score = 100 * sum(w * np.nan_to_num(getattr(self, k)) for k, w in fr.R1_WEIGHTS.items())
        self.t15_ns = np.array([pd.Timestamp(r["t"]).value for r in rows], dtype=np.int64)
        self.labels: dict[int, fr.LabelArrays] = {}

    def build_labels(self, delay: int):
        shift = timedelta(minutes=15 - delay)
        by_sess = defaultdict(list)
        for i, s in enumerate(self.sess):
            by_sess[s].append(i)
        n = len(self.rows)
        entry, mfe, retc = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        ev, hi_ns, hi, low = (np.zeros(len(self.sessions), dtype=bool), np.zeros(len(self.sessions), dtype=np.int64),
                              np.zeros(len(self.sessions)), np.zeros(len(self.sessions)))
        bars_cache = {}
        for s, idx in by_sess.items():
            sym, day = self.sessions[s]
            if sym not in bars_cache:
                bars_cache[sym] = r1ds.load(sym).bars
            times = [self.rows[i]["t"] - shift for i in idx]
            outcome, labs = labels_for_session(bars_cache[sym], day, times)
            for i, lab in zip(idx, labs):
                entry[i] = np.nan if lab.entry is None else lab.entry
                mfe[i] = np.nan if lab.mfe_close is None else lab.mfe_close
                retc[i] = np.nan if lab.ret_close is None else lab.ret_close
            ev[s] = outcome.max_runup >= E
            hi_ns[s] = pd.Timestamp(outcome.high_time).value
            hi[s] = outcome.high
            low[s] = run_low_cached(sym, day, bars_cache[sym])
        self.labels[delay] = fr.LabelArrays(self.t15_ns - int(shift.total_seconds() * 1e9), entry, mfe, retc, self.ok,
                                            ev, hi_ns, hi, low)

    # ---- kurallar (eşik yüzeyi; üretimle aynı Round 1 bileşen anlamı)
    def part_or_struct(self):
        part = self.volume_anomaly >= THR
        struct = (self.breakout >= THR) | (self.range_expansion >= THR) | (self.vwap >= THR)
        return part, struct

    def watch_raw(self, cfg: dict) -> np.ndarray:
        part, struct = self.part_or_struct()
        raw = self.ok & (self.price_impulse >= cfg["price"]) & (self.score >= cfg["score"])
        if cfg["need_ps"]:
            raw &= part | struct
        if cfg["accel"] is not None:
            raw &= (self.accel >= cfg["accel"]) & (self.accel_pos_3 >= 2)
        if cfg["xs"] is not None:
            raw &= np.isnan(self.xs_ret) | (self.xs_ret >= cfg["xs"])  # bağlam yoksa kapı uygulanmaz
        if cfg["rel"] is not None:
            raw &= np.isnan(self.rel_ret_z_3) | (self.rel_ret_z_3 >= cfg["rel"])
        return raw

    def strong_raw(self, cfg: dict) -> np.ndarray:
        part, struct = self.part_or_struct()
        raw = (self.ok & (self.price_impulse >= max(cfg["price"], THR)) & part & struct & (self.score >= cfg["score"])
               & self.persistent & ~self.data_gap)
        if cfg["xs"] is not None:
            raw &= np.isnan(self.xs_ret) | (self.xs_ret >= cfg["xs"])
        return raw


_RUNLOW: dict = {}


def run_low_cached(symbol, day, bars):
    key = (symbol, day)  # nesne kimliği (id) DEĞİL: serbest kalan DataFrame kimlikleri yeniden kullanılabilir
    if key not in _RUNLOW:
        from app.research.momentum_round2.metrics import run_low
        _RUNLOW[key] = run_low(bars, day)
    return _RUNLOW[key]


def grid(spec: dict):
    keys = list(spec)
    for combo in itertools.product(*(spec[k] for k in keys)):
        yield dict(zip(keys, combo))


def base_rate(p: Panel, delay: int) -> float:
    lab = p.labels[delay]
    m = p.ok & np.isfinite(lab.mfe_close)
    return float((lab.mfe_close[m] >= X).mean())


def sweep(p: Panel, kind: str) -> list[dict]:
    points = []
    spec = WATCH_GRID if kind == "WATCH" else STRONG_GRID
    raw_cache = {}
    for cfg in grid(spec):
        rkey = tuple((k, v) for k, v in cfg.items() if k != "confirm")
        if rkey not in raw_cache:
            raw_cache[rkey] = p.watch_raw(cfg) if kind == "WATCH" else p.strong_raw(cfg)
        final = fr.confirm(raw_cache[rkey], p.seg_start, *cfg["confirm"])
        for d in DELAYS:
            points.append({"kind": kind, "delay": d, "config": cfg, **fr.metrics(final, p.sess, p.labels[d], X)})
    return points


def single_feature_sweep(p: Panel) -> list[dict]:
    """Senaryo C: tek öznitelik eşiği (1/1), eşik = OK satırlarının yüzdelikleri (etiket değil, dağılım)."""
    points = []
    for feat in SINGLE_FEATURES:
        vals = getattr(p, feat)
        finite = vals[p.ok & np.isfinite(vals)]
        for q in QUANTILES:
            thr = float(np.percentile(finite, q))
            final = p.ok & np.isfinite(vals) & (vals >= thr)
            for d in DELAYS:
                points.append({"kind": "SINGLE", "delay": d, "config": {"feature": feat, "quantile": q,
                                                                       "threshold": round(thr, 4)},
                               **fr.metrics(final, p.sess, p.labels[d], X)})
    return points


# ------------------------------------------------------------------ olay zamanlaması ve sınıflamalar
def _hhmm(ns):
    return pd.Timestamp(int(ns), tz="UTC").tz_convert(ISTANBUL_TZ).strftime("%H:%M") if ns is not None else None


def event_timing(p: Panel, r1_final: np.ndarray, r1_raw: np.ndarray) -> dict:
    """Bilgi zamanı = verinin oluştuğu an (bar bitişi = 15 dk gecikmeli değerlendirme zamanı − 15 dk)."""
    lab0 = p.labels[0]  # bilgi zamanında (gecikmesiz) giriş fiyatı
    info_ns = lab0.t_ns
    part, struct = p.part_or_struct()
    conds = {"price_impulse": p.ok & (p.price_impulse >= THR),
             "acceleration": p.ok & (p.accel >= 0.5) & (p.accel_pos_3 >= 2),
             "volume_anomaly": p.ok & (p.volume_anomaly >= THR),
             "relative_strength": p.ok & (p.rel_ret_z_3 >= 1.0),
             "xs_top_decile": p.ok & (p.xs_ret >= 0.9),
             "raw_watch": r1_raw, "confirmed_watch_info_time": r1_final}
    events = np.flatnonzero(lab0.sess_event)
    seg_rows = defaultdict(list)
    for i, s in enumerate(p.sess):
        seg_rows[s].append(i)
    per, start_ns = [], {}
    for s in events:
        sym, day = p.sessions[s]
        bars = r1ds.load(sym).bars
        dbar = bars[bars.index.date == day].dropna()
        j = int(np.argmax(dbar["High"].to_numpy()))
        lo_pos = int(np.argmin(dbar["Low"].to_numpy()[: j + 1]))
        start_ns[s] = dbar.index[lo_pos].value
        rec = {"move_start": start_ns[s], "peak": int(lab0.sess_high_ns[s])}
        idx = np.array(seg_rows[s])
        span = lab0.sess_high[s] - lab0.sess_run_low[s]
        for name, c in conds.items():
            hit = idx[c[idx] & (info_ns[idx] <= lab0.sess_high_ns[s])]
            if len(hit):
                i = hit[0]
                lf = max(0.0, (lab0.entry[i] - lab0.sess_run_low[s]) / span) if span > 0 else None
                rec[name] = (int(info_ns[i]), lf)
            else:
                rec[name] = None
        per.append((s, rec))
    summary = {}
    for name in conds:
        mins = [(rec[name][0] - rec["move_start"]) / 6e10 for _, rec in per if rec[name]]
        leads = [rec[name][1] for _, rec in per if rec[name] and rec[name][1] is not None]
        summary[name] = {"share_events_before_peak": round(len(mins) / len(per), 3),
                         "median_minutes_after_move_start": round(float(np.median(mins)), 1) if mins else None,
                         "median_lead_fraction": round(float(np.median(leads)), 3) if leads else None,
                         "share_lead_le_0.33": round(sum(lf <= 1 / 3 for lf in leads) / len(per), 3)}
    peak_min = [(rec["peak"] - rec["move_start"]) / 6e10 for _, rec in per]
    summary["session_peak"] = {"median_minutes_after_move_start": round(float(np.median(peak_min)), 1),
                               "share_peak_within_15min_of_start": round(sum(m <= 15 for m in peak_min) / len(per), 3),
                               "share_peak_within_30min_of_start": round(sum(m <= 30 for m in peak_min) / len(per), 3)}
    # A: veri geç oluşuyor (ilk fiyat kanıtı lead ≥ 0.5 veya hiç) / B: motor geç yorumluyor (kanıt erken, alarm geç)
    lab15 = p.labels[15]
    split = Counter()
    for s, rec in per:
        pe = rec["price_impulse"]
        cw_rows = [i for i in seg_rows[s] if r1_final[i]]
        cw_lead = None
        if cw_rows and lab15.t_ns[cw_rows[0]] <= lab15.sess_high_ns[s]:
            span = lab15.sess_high[s] - lab15.sess_run_low[s]
            cw_lead = max(0.0, (lab15.entry[cw_rows[0]] - lab15.sess_run_low[s]) / span) if span > 0 else None
        if pe is None or (pe[1] is not None and pe[1] >= 0.5):
            split["A_DATA_LATE_or_ABSENT"] += 1
        elif cw_lead is None or cw_lead >= 0.5:
            split["B_ENGINE_LATE (evidence early, alert late/none)"] += 1
        else:
            split["EARLY_OK"] += 1
    examples = []
    for s, rec in sorted(per, key=lambda x: -(lab0.sess_high[x[0]] / lab0.sess_run_low[x[0]]))[:10]:
        examples.append({"symbol": p.sessions[s][0], "day": str(p.sessions[s][1]),
                         "runup_pct": round((lab0.sess_high[s] / lab0.sess_run_low[s] - 1) * 100, 1),
                         **{k: (_hhmm(v[0]) if isinstance(v, tuple) else _hhmm(v)) for k, v in rec.items()}})
    return {"events": len(per), "summary": summary, "data_vs_engine": dict(split), "top_examples": examples}


def fp_taxonomy(p: Panel, final: np.ndarray, delay: int = 15) -> dict:
    lab = p.labels[delay]
    uniq, rows = fr.first_alert_rows(final, p.sess)
    cats = Counter()
    for s, i in zip(uniq, rows):
        if lab.sess_event[s]:
            continue
        hour_min = (lab.t_ns[i] // 60_000_000_000) % 1440 + 180  # UTC→TR (+3)
        part, _ = (p.volume_anomaly[i] >= THR), None
        if p.locked[i] or np.isnan(p.volume_anomaly[i]):
            c = "locked_or_illiquid_regime"
        elif p.regime_shock[i]:
            c = "benchmark_shock"
        elif np.isfinite(p.rel_ret_z_3[i]) and p.rel_ret_z_3[i] < 1.0:
            c = "broad_market_move"
        elif np.nan_to_num(p.gap_pct[i]) >= 1.0 and np.nan_to_num(lab.ret_close[i]) < 0:
            c = "gap_then_fade"
        elif hour_min >= 17 * 60:
            c = "late_day_noise"
        elif not part:
            c = "price_spike_without_participation"
        elif np.nan_to_num(p.breakout_dist_atr[i], nan=-1) > 0 and np.nan_to_num(lab.ret_close[i]) < 0:
            c = "breakout_failure"
        elif np.nan_to_num(p.relvol_3[i]) >= 2.0 and np.nan_to_num(lab.mfe_close[i]) < 0.01:
            c = "volume_spike_without_continuation"
        else:
            c = "other"
        cats[c] += 1
    total = sum(cats.values())
    return {"fp_sessions": total, "share": {k: round(v / total, 3) for k, v in cats.most_common()},
            "counts": dict(cats)}


def fn_taxonomy(p: Panel, final: np.ndarray, raw: np.ndarray, xs_raw: np.ndarray) -> dict:
    """Kaçırılan olay = 15 dk gecikmeyle seans tepesinden önce doğrulanmış WATCH yok."""
    lab15, lab0 = p.labels[15], p.labels[0]
    part, struct = p.part_or_struct()
    seg_rows = defaultdict(list)
    for i, s in enumerate(p.sess):
        seg_rows[s].append(i)
    cats, xs_fail, xs_base = Counter(), 0, 0
    for s in np.flatnonzero(lab15.sess_event):
        idx = np.array(seg_rows[s])
        hi = lab15.sess_high_ns[s]
        before15 = idx[lab15.t_ns[idx] <= hi]
        before_info = idx[lab0.t_ns[idx] <= hi]
        if final[before15].any():
            continue
        sym, day = p.sessions[s]
        bars = r1ds.load(sym).bars
        dbar = bars[bars.index.date == day].dropna()
        j = int(np.argmax(dbar["High"].to_numpy()))
        lo_pos = int(np.argmin(dbar["Low"].to_numpy()[: j + 1]))
        rise_min = (dbar.index[j] - dbar.index[lo_pos]).total_seconds() / 60
        ok_before = before_info[p.ok[before_info]]
        if len(ok_before) and np.all(np.isnan(p.price_impulse[ok_before])):
            c = "baseline_unavailable"
        elif rise_min <= 15:
            c = "abrupt_vertical_jump"
        elif not (p.price_impulse[before_info] >= THR).any():
            c = "no_early_price_evidence"
        elif not ((p.price_impulse[before_info] >= THR) & (part | struct)[before_info]).any():
            c = "no_volume_or_structure_evidence"
        elif raw[before_info].any() and not raw[before15].any():
            c = "provider_delay"
        elif raw[before15].any():
            c = "confirmation_delay"
        else:
            c = "score_below_threshold"
        cats[c] += 1
        if raw[before15].any():
            xs_base += 1
            xs_fail += int(not xs_raw[before15].any())
    total = sum(cats.values())
    return {"missed_events": total, "share": {k: round(v / total, 3) for k, v in cats.most_common()},
            "counts": dict(cats),
            "cross_sectional_gate_failure_if_xs0.9": {"events_with_raw_watch_before_peak": xs_base,
                                                      "blocked_by_xs_gate": xs_fail}}


def confirmation_cost(p: Panel, base_cfg: dict) -> list[dict]:
    raw = p.watch_raw(base_cfg)
    _, first_raw = fr.first_alert_rows(raw, p.sess)
    first_raw_t = dict(zip(*fr.first_alert_rows(raw, p.sess)))
    out = []
    for k, n in ((1, 1), (2, 3), (2, 2), (3, 3)):
        final = fr.confirm(raw, p.seg_start, k, n)
        uniq, rows = fr.first_alert_rows(final, p.sess)
        delays = [(p.t15_ns[r] - p.t15_ns[first_raw_t[s]]) / 6e10 for s, r in zip(uniq, rows)]
        m = fr.metrics(final, p.sess, p.labels[15], X)
        out.append({"confirm": f"{k}/{n}", **{kk: m[kk] for kk in ("precision", "recall", "false_positive_rate",
                                                                    "lead_fraction_median", "alert_day_ratio")},
                    "median_delay_after_first_raw_min": float(np.median(delays)) if delays else None,
                    "sessions_lost_vs_raw": int(len(first_raw) - len(uniq))})
    return out


def summarize_frontier(points: list[dict], br: dict) -> dict:
    out = {}
    for d in DELAYS:
        pts = [q for q in points if q["delay"] == d]
        keep = fr.pareto_mask(pts)
        front = [q for q, k in zip(pts, keep) if k]
        two_x = 2 * br[d]
        def brief(q):
            if q is None:
                return None
            return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in q.items() if k not in ("kind",)}
        out[d] = {"points": len(pts), "frontier_size": len(front),
                  "A_max_recall_fpr_le_0.25": brief(fr.best_under(pts, "recall", True,
                                                                  {"false_positive_rate": ("<=", 0.25)})),
                  "B_max_recall_fpr_le_0.15": brief(fr.best_under(pts, "recall", True,
                                                                  {"false_positive_rate": ("<=", 0.15)})),
                  "C_min_fpr_lead_le_0.40": brief(fr.best_under(pts, "false_positive_rate", False,
                                                                {"lead_fraction_median": ("<=", 0.40)})),
                  "D_min_fpr_lead_le_0.30": brief(fr.best_under(pts, "false_positive_rate", False,
                                                                {"lead_fraction_median": ("<=", 0.30)})),
                  "E_min_lead_precision_ge_2x_base": brief(fr.best_under(pts, "lead_fraction_median", False,
                                                                         {"precision": (">=", two_x)})),
                  "min_lead_fpr_le_0.25": brief(fr.best_under(pts, "lead_fraction_median", False,
                                                              {"false_positive_rate": ("<=", 0.25)})),
                  "min_lead_fpr_le_0.25_recall_ge_0.40": brief(fr.best_under(
                      pts, "lead_fraction_median", False, {"false_positive_rate": ("<=", 0.25),
                                                           "recall": (">=", 0.40)})),
                  "max_recall_fpr_le_0.25_lead_le_0.50": brief(fr.best_under(
                      pts, "recall", True, {"false_positive_rate": ("<=", 0.25), "lead_fraction_median": ("<=", 0.5)})),
                  "frontier_sample": [brief(q) for q in sorted(front, key=lambda q: q["false_positive_rate"] or 1)
                                      [:: max(1, len(front) // 25)]]}
    return out


# ------------------------------------------------------------------ genişletilmiş denetim (aşama "audit")
R1_FINAL_STRONG = {"price": 0.75, "score": 60, "xs": None}  # üretim GROUPS STRONG kuralı (Round 1 final)
FPR_LIMITS = (0.25, 0.20, 0.15, 0.10)
LEAD_LIMITS = (0.50, 0.40, 0.30)
METRIC_KEYS = ("precision", "recall", "false_positive_rate", "specificity", "alert_day_ratio", "lead_fraction_median",
               "median_first_alert_minute", "caught_events", "alert_sessions")


def _hm(minute):
    return None if minute is None else f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"


def brief_point(q: dict | None) -> dict | None:
    if q is None:
        return None
    out = {"delay": q.get("delay"), "config": q.get("config")}
    for k in METRIC_KEYS:
        v = (1 - q["false_positive_rate"] if q.get("false_positive_rate") is not None else None) \
            if k == "specificity" else q.get(k)
        out[k] = round(v, 4) if isinstance(v, float) else v
    out["median_first_alert_clock"] = _hm(q.get("median_first_alert_minute"))
    return out


def frontier_answers(points: list[dict], base: float) -> dict:
    out = {}
    for f in FPR_LIMITS:
        out[f"max_recall_fpr_le_{f}"] = brief_point(fr.best_under(points, "recall", True,
                                                                  {"false_positive_rate": ("<=", f)}))
    for lead in LEAD_LIMITS:
        out[f"min_fpr_lead_le_{lead}"] = brief_point(fr.best_under(points, "false_positive_rate", False,
                                                                   {"lead_fraction_median": ("<=", lead)}))
    for m in (2, 3):
        out[f"min_lead_precision_ge_{m}x_base"] = brief_point(fr.best_under(
            points, "lead_fraction_median", False, {"precision": (">=", m * base)}))
    out["max_recall_fpr_le_0.25_lead_le_0.50"] = brief_point(fr.best_under(
        points, "recall", True, {"false_positive_rate": ("<=", 0.25), "lead_fraction_median": ("<=", 0.5)}))
    out["min_lead_fpr_le_0.25"] = brief_point(fr.best_under(points, "lead_fraction_median", False,
                                                            {"false_positive_rate": ("<=", 0.25)}))
    return out


def frontier3(points: list[dict]) -> list[dict]:
    """Görevdeki baskınlık tanımı: daha yüksek YPO + daha düşük duyarlılık + daha geç lead → çıkar."""
    keep = fr.pareto_mask(points, maximize=("recall",), minimize=("false_positive_rate", "lead_fraction_median"))
    return sorted([q for q, k in zip(points, keep) if k], key=lambda q: (q["false_positive_rate"], -q["recall"]))


def frontier_block(points: list[dict], br: dict) -> dict:
    out = {}
    for d in DELAYS:
        pts = [q for q in points if q["delay"] == d]
        front = frontier3(pts)
        out[d] = {"points": len(pts), "frontier3_size": len(front),
                  "frontier4_size": int(fr.pareto_mask(pts).sum()), **frontier_answers(pts, br[d]),
                  "frontier": [brief_point(q) for q in front[:: max(1, len(front) // 30)]]}
    return out


def strong_vs_watch(watch: list[dict], strong: list[dict], r1_watch_by_delay: dict) -> dict:
    out = {}
    for d in DELAYS:
        wf = frontier3([q for q in watch if q["delay"] == d])
        sf = frontier3([q for q in strong if q["delay"] == d])
        rows, beats_same_recall, beats_r1 = [], 0, 0
        for q in sf:
            if q["precision"] is None:
                continue
            comp = [w["precision"] for w in wf if w["precision"] is not None and w["recall"] >= q["recall"]]
            best_w = max(comp) if comp else None
            a = best_w is None or q["precision"] > best_w
            b = q["precision"] > (r1_watch_by_delay[d]["precision"] or 0)
            beats_same_recall += a
            beats_r1 += b
            rows.append({**brief_point(q), "best_watch_precision_at_ge_recall": best_w,
                         "strong_gt_watch_same_recall": a, "strong_gt_round1_watch": b})
        out[d] = {"strong_frontier_points": len(rows), "strong_precision_gt_watch_at_same_or_higher_recall":
                  beats_same_recall, "strong_precision_gt_round1_watch": beats_r1,
                  "round1_watch_precision": r1_watch_by_delay[d]["precision"],
                  "points": rows[:: max(1, len(rows) // 20)]}
    return out


def confirm_cost(p: Panel, raw: np.ndarray) -> list[dict]:
    first_raw = dict(zip(*fr.first_alert_rows(raw, p.sess)))
    out = []
    for k, n in ((1, 1), (2, 3), (2, 2), (3, 3)):
        final = fr.confirm(raw, p.seg_start, k, n)
        uniq, rows = fr.first_alert_rows(final, p.sess)
        added = [(p.t15_ns[r] - p.t15_ns[first_raw[s]]) / 6e10 for s, r in zip(uniq, rows)]
        m15, m0 = fr.metrics(final, p.sess, p.labels[15], X), fr.metrics(final, p.sess, p.labels[0], X)
        out.append({"confirm": f"{k}/{n}", **{kk: brief_point(m15)[kk] for kk in METRIC_KEYS},
                    "lead_fraction_median_d0": m0["lead_fraction_median"],
                    "added_delay_min_median": float(np.median(added)) if added else None,
                    "added_delay_min_mean": round(float(np.mean(added)), 2) if added else None,
                    "sessions_lost_vs_raw": len(first_raw) - len(uniq)})
    return out


def _session_arrays(p: Panel, delay: int):
    lab = p.labels[delay]
    span = lab.sess_high - lab.sess_run_low
    lead = (lab.entry - lab.sess_run_low[p.sess]) / np.where(span > 0, span, np.nan)[p.sess]
    before = lab.t_ns <= lab.sess_high_ns[p.sess]
    return np.maximum(lead, 0.0), before


def _move_start_ns(sym, day) -> int:
    bars = r1ds.load(sym).bars
    dbar = bars[bars.index.date == day].dropna()
    j = int(np.argmax(dbar["High"].to_numpy()))
    return int(dbar.index[int(np.argmin(dbar["Low"].to_numpy()[: j + 1]))].value)


def evidence_masks(p: Panel, w_raw, w_final, s_final) -> dict[str, np.ndarray]:
    part, struct = p.part_or_struct()
    return {"price_evidence": p.ok & (p.price_impulse >= THR),
            "positive_acceleration": p.ok & (p.accel > 0),
            "strong_acceleration": p.ok & (p.accel >= 1.0) & (p.accel_pos_3 >= 2),
            "volume_anomaly": p.ok & (p.volume_anomaly >= THR),
            "relative_strength": p.ok & (p.rel_ret_z_3 >= 1.0),
            "xs_top_decile": p.ok & (p.xs_ret >= 0.9),
            "breakout": p.ok & (p.breakout >= THR),
            "vwap_reclaim": p.ok & (p.vwap_reclaim == 1),
            "raw_watch": w_raw, "confirmed_watch": w_final, "strong": s_final,
            "_price_and_participation": p.ok & (p.price_impulse >= THR) & (part | struct)}


def event_analysis(p: Panel, w_raw, w_final, s_final, gated_raw, sessions=None) -> dict:
    lab0, lab15 = p.labels[0], p.labels[15]
    lead0, before0 = _session_arrays(p, 0)
    lead15, before15 = _session_arrays(p, 15)
    masks = evidence_masks(p, w_raw, w_final, s_final)
    seg_rows = defaultdict(list)
    for i, s in enumerate(p.sess):
        seg_rows[s].append(i)
    targets = sessions if sessions is not None else np.flatnonzero(lab0.sess_event)
    per = []
    for s in targets:
        sym, day = p.sessions[s]
        idx = np.array(seg_rows[s])
        ms, peak = _move_start_ns(sym, day), int(lab0.sess_high_ns[s])
        info = lab0.t_ns[idx]
        after = info > ms
        tl = au.event_timeline(info, {k: m[idx] & after for k, m in masks.items() if not k.startswith("_")}, ms, peak)

        def first_lead(mask, lead, before):
            hit = idx[mask[idx] & before[idx] & after]
            return (float(lead[hit[0]]) if np.isfinite(lead[hit[0]]) else None) if len(hit) else None
        ev_lead = first_lead(masks["price_evidence"], lead0, before0)
        d0_raw = first_lead(w_raw, lead0, before0)
        d15_raw = first_lead(w_raw, lead15, before15)
        d0_lead = first_lead(w_final, lead0, before0)
        d15_lead = first_lead(w_final, lead15, before15)
        cls = au.classify_timing(ev_lead, d0_raw, d15_raw, d15_lead)
        sub = None
        if cls == "MIXED":
            sub = "provider_only" if d0_lead is not None and d0_lead < au.LEAD_TARGET else "provider_and_confirmation"
        elif cls == "ENGINE_LATE":
            sub = "threshold_gating" if not (d0_raw is not None and d0_raw < au.LEAD_TARGET) else "confirmation"
        # Gecikme ayrıştırması: hareket başlangıcından sonraki ilk oluşumlar (tepe kısıtı yok)
        firsts = {}
        for k in ("price_evidence", "raw_watch", "confirmed_watch"):
            hit = idx[masks[k][idx] & after]
            firsts[k] = int(lab0.t_ns[hit[0]]) if len(hit) else None
        dec = au.decompose_delay(ms, firsts["price_evidence"], firsts["raw_watch"], firsts["confirmed_watch"], 15)
        # Yanlış negatif bayrakları (yeterince erken yakalanmayan)
        early0 = before0 & (lead0 < au.LEAD_TARGET)
        early15 = before15 & (lead15 < au.LEAD_TARGET)
        win = idx[after & before0[idx]]
        mv = idx[after]  # hareket başlangıcından önceki satırlar (sabah) olaya sayılmaz
        fn = None
        if cls != "EARLY_OK":
            flags = {
                # boş pencere (tepe açılış barında) taban eksikliği DEĞİL; ani sıçrama olarak sayılır
                "BASELINE_UNAVAILABLE": len(win) > 0 and not (p.ok[win] & np.isfinite(p.price_impulse[win])).any(),
                "ABRUPT_VERTICAL_JUMP": (peak - ms) / au.MIN_NS <= 15,
                "NO_EARLY_PRICE_EVIDENCE": not (masks["price_evidence"][win] & early0[win]).any(),
                "NO_VOLUME_CONFIRMATION": (masks["price_evidence"][win] & early0[win]).any()
                and not (masks["_price_and_participation"][win] & early0[win]).any(),
                "FEATURE_THRESHOLD": (masks["_price_and_participation"][win] & early0[win]).any()
                and not (w_raw[win] & early0[win]).any(),
                "PROVIDER_DELAY": (w_raw[win] & early0[win]).any() and not (w_raw[mv] & early15[mv]).any(),
                "CONFIRMATION_DELAY": (w_raw[mv] & early15[mv]).any() and not (w_final[mv] & early15[mv]).any(),
                "BENCHMARK/CROSS_SECTION_GATE": (w_raw[mv] & early15[mv]).any()
                and not (gated_raw[mv] & early15[mv]).any(),
            }
            primary, secondary = au.classify_fn(flags)
            fn = {"primary": primary, "secondary": secondary}
        per.append({"symbol": sym, "day": str(day), "session": int(s),
                    "runup_pct": round((lab0.sess_high[s] / lab0.sess_run_low[s] - 1) * 100, 2),
                    "rise_minutes": (peak - ms) / au.MIN_NS, "timeline_ns": tl, "evidence_lead": ev_lead,
                    "d0_raw_lead": d0_raw, "d15_raw_lead": d15_raw, "d0_alert_lead": d0_lead,
                    "d15_alert_lead": d15_lead, "class": cls, "subclass": sub, "decomposition": dec,
                    "fn": fn, "rows_before_peak": int(len(win)), "firsts_ns": firsts})
    return {"events": per}


def summarize_events(per: list[dict]) -> dict:
    names = [k for k in per[0]["timeline_ns"] if k not in ("move_start", "peak")] if per else []
    timeline = {}
    for k in names:
        mins = [(e["timeline_ns"][k] - e["timeline_ns"]["move_start"]) / au.MIN_NS for e in per
                if e["timeline_ns"][k] is not None]
        timeline[k] = {"share_before_peak": round(len(mins) / len(per), 3),
                       "median_min_after_move_start_info_time": float(np.median(mins)) if mins else None,
                       "median_min_after_move_start_visible_d15": float(np.median(mins)) + 15 if mins else None}
    peak = [e["rise_minutes"] for e in per]
    timeline["session_peak"] = {"median_min_after_move_start": float(np.median(peak)),
                                "share_rise_le_15min": round(sum(m <= 15 for m in peak) / len(per), 3),
                                "share_rise_le_30min": round(sum(m <= 30 for m in peak) / len(per), 3),
                                "share_rise_le_60min": round(sum(m <= 60 for m in peak) / len(per), 3)}
    timeline["session_peak"]["share_no_evaluation_before_peak"] = round(
        sum(e["rows_before_peak"] == 0 for e in per) / len(per), 3)
    classes = Counter(e["class"] for e in per)
    subclasses = Counter(f"{e['class']}:{e['subclass']}" for e in per if e["subclass"])
    decs = [e["decomposition"] for e in per if e["decomposition"]]
    dec = {k: {"median": float(np.median([d[k] for d in decs])), "p25": float(np.percentile([d[k] for d in decs], 25)),
               "p75": float(np.percentile([d[k] for d in decs], 75))} for k in (decs[0] if decs else {})}
    late_vs_peak = sum(1 for e in per if e["decomposition"] and
                       e["timeline_ns"]["move_start"] + e["decomposition"]["total"] * au.MIN_NS > e["timeline_ns"]["peak"])
    fn = [e["fn"] for e in per if e["fn"]]
    prim = Counter(f["primary"] for f in fn)
    anyf = Counter(r for f in fn for r in [f["primary"], *f["secondary"]])
    return {
        "events": len(per), "timeline": timeline,
        "classification": {k: {"count": v, "share": round(v / len(per), 3)} for k, v in classes.most_common()},
        "subclassification": dict(subclasses.most_common()),
        "delay_decomposition_minutes": {"events_with_confirmed_watch": len(decs), **dec,
                                        "share_visible_alert_after_peak": round(late_vs_peak / len(decs), 3)
                                        if decs else None},
        "fn_taxonomy": {"not_caught_early": len(fn),
                        "primary": {k: {"count": v, "share": round(v / len(fn), 3)} for k, v in prim.most_common()},
                        "any_reason": {k: {"count": v, "share": round(v / len(fn), 3)} for k, v in anyf.most_common()}},
    }


def fp_taxonomy_v2(p: Panel, final: np.ndarray, delay: int = 15) -> dict:
    lab = p.labels[delay]
    uniq, rows = fr.first_alert_rows(final, p.sess)
    prim, anyf, profiles = Counter(), Counter(), defaultdict(list)
    for s, i in zip(uniq, rows):
        if lab.sess_event[s]:
            continue
        nxt = [j for j in range(i + 1, min(i + 4, len(p.sess))) if p.sess[j] == s]
        nxt_acc = np.nanmin(p.accel[nxt]) if nxt and np.isfinite(p.accel[nxt]).any() else np.nan
        minute = float((lab.t_ns[i] // au.MIN_NS + 180) % 1440)
        flags = au.fp_flags(locked=bool(p.locked[i]), volume_missing=bool(np.isnan(p.volume_anomaly[i])),
                            regime_shock=bool(p.regime_shock[i]), rel_ret_z_3=p.rel_ret_z_3[i], gap_pct=p.gap_pct[i],
                            ret_close=lab.ret_close[i], breakout=p.breakout[i], volume_anomaly=p.volume_anomaly[i],
                            relvol_3=p.relvol_3[i], mfe_close=lab.mfe_close[i], accel=p.accel[i],
                            accel_next_min=nxt_acc, visible_minute=minute, evidence_threshold=THR, x=X)
        primary, secondary = au.classify_fp(flags)
        prim[primary] += 1
        for r in [primary, *secondary]:
            anyf[r] += 1
        profiles[primary].append({"price_z": p.price_z[i], "ret_z_3": p.ret_z_3[i], "accel": p.accel[i],
                                  "rel_ret_z_3": p.rel_ret_z_3[i], "xs_ret": p.xs_ret[i], "relvol_3": p.relvol_3[i],
                                  "gap_pct": p.gap_pct[i], "score": p.score[i], "mfe_close": lab.mfe_close[i],
                                  "ret_close": lab.ret_close[i], "visible_minute": minute})
    total = sum(prim.values())

    def med(rows):
        return {k: (round(float(np.nanmedian([r[k] for r in rows])), 3)
                    if np.isfinite([r[k] for r in rows]).any() else None) for k in rows[0]}
    return {"fp_sessions": total,
            "primary": {k: {"count": v, "share": round(v / total, 3), "median_profile": med(profiles[k])}
                        for k, v in prim.most_common()},
            "any_reason": {k: {"count": v, "share": round(v / total, 3)} for k, v in anyf.most_common()}}


def _clock(ns):
    return None if ns is None else _hhmm(ns)


def ktlev_case(day=None) -> dict:
    """Yalnız açıklama: KTLEV 8 Ekim. Hiçbir eşik/ızgara noktası buradan seçilmez."""
    from datetime import date as _date
    day = day or _date(2026, 10, 8)
    rows = [r for r in guarded_load("merged_ktlev_d15.pkl") if r["day"] == day]
    k = Panel(rows)
    for d in (0, 15):
        k.build_labels(d)
    w_raw = k.watch_raw(R1_FINAL_WATCH)
    w_final = fr.confirm(w_raw, k.seg_start, 3, 3)
    s_final = fr.confirm(k.strong_raw(R1_FINAL_STRONG), k.seg_start, 3, 3)
    gated = k.watch_raw({**R1_FINAL_WATCH, "xs": 0.9, "rel": 1.0})
    w_23 = fr.confirm(w_raw, k.seg_start, 2, 3)
    ev = event_analysis(k, w_raw, w_final, s_final, gated, sessions=[0])["events"][0]
    tl = ev["timeline_ns"]
    lab0, lab15 = k.labels[0], k.labels[15]

    def first(mask, lab):
        hit = np.flatnonzero(mask & (lab0.t_ns > tl["move_start"]))
        return None if not len(hit) else {"info_time": _clock(lab0.t_ns[hit[0]]),
                                          "visible_time": _clock(lab.t_ns[hit[0]]),
                                          "lead_fraction": au.lead_fraction(lab.entry[hit[0]], lab.sess_run_low[0],
                                                                            lab.sess_high[0]),
                                          "entry": round(float(lab.entry[hit[0]]), 3)}
    bars = r1ds.load("KTLEV").bars
    dbar = bars[bars.index.date == day].dropna()
    leg = dbar[(dbar.index.time >= datetime.strptime("15:50", "%H:%M").time())
               & (dbar.index.time <= datetime.strptime("16:45", "%H:%M").time())]
    return {"symbol": "KTLEV", "day": str(day), "used_for_tuning": False,
            "bars_15_50_16_45": [{"start": t.strftime("%H:%M"), "close": round(float(b["Close"]), 3),
                                  "high": round(float(b["High"]), 3), "volume": int(b["Volume"])}
                                 for t, b in leg.iterrows()],
            "session_high": round(float(lab0.sess_high[0]), 3), "run_low": round(float(lab0.sess_run_low[0]), 3),
            "runup_pct": ev["runup_pct"], "move_start": _clock(tl["move_start"]), "peak": _clock(tl["peak"]),
            "rise_minutes": ev["rise_minutes"],
            "timeline_info_time": {kk: _clock(v) for kk, v in tl.items()},
            "theoretical_d0": {"raw_1of1": first(w_raw, lab0), "confirmed_2of3": first(w_23, lab0),
                               "confirmed_3of3": first(w_final, lab0)},
            "realistic_d15": {"raw_1of1": first(w_raw, lab15), "confirmed_2of3": first(w_23, lab15),
                              "confirmed_3of3": first(w_final, lab15), "strong_3of3": first(s_final, lab15)},
            "class": ev["class"], "fn": ev["fn"], "decomposition_minutes": ev["decomposition"]}


def audit():
    started = clock.perf_counter()
    p = Panel(load_selection_rows())
    for d in DELAYS:
        p.build_labels(d)
    br = {d: base_rate(p, d) for d in DELAYS}
    w_raw = p.watch_raw(R1_FINAL_WATCH)
    w_final = fr.confirm(w_raw, p.seg_start, 3, 3)
    s_raw = p.strong_raw(R1_FINAL_STRONG)
    s_final = fr.confirm(s_raw, p.seg_start, 3, 3)
    gated = p.watch_raw({**R1_FINAL_WATCH, "xs": 0.9, "rel": 1.0})
    print(f"panel {len(p.rows)} satır, {len(p.sessions)} seans, {clock.perf_counter() - started:.0f} sn", flush=True)
    watch, strong, single = sweep(p, "WATCH"), sweep(p, "STRONG"), single_feature_sweep(p)
    print(f"ızgara {len(watch)}+{len(strong)}+{len(single)}, {clock.perf_counter() - started:.0f} sn", flush=True)
    r1w = {d: fr.metrics(w_final, p.sess, p.labels[d], X) for d in DELAYS}
    r1s = {d: fr.metrics(s_final, p.sess, p.labels[d], X) for d in DELAYS}
    n_ev = int(p.labels[15].sess_event.sum())
    ev = event_analysis(p, w_raw, w_final, s_final, gated)
    scen = {"A_5m_d15_all_confirm": [q for q in watch if q["delay"] == 15],
            "B_5m_d0_all_confirm": [q for q in watch if q["delay"] == 0],
            "C_5m_d0_raw_1of1": [q for q in watch + single if q["delay"] == 0
                                 and q["config"].get("confirm", (1, 1)) == (1, 1)],
            "C15_5m_d15_raw_1of1 (kontrol)": [q for q in watch + single if q["delay"] == 15
                                              and q["config"].get("confirm", (1, 1)) == (1, 1)]}
    result = {
        "scope": {"assets": len({s for s, _ in p.sessions}), "sessions": len(p.sessions), "rows": len(p.rows),
                  "days": [str(min(d for _, d in p.sessions)), str(max(d for _, d in p.sessions))],
                  "artifact": "momentum_round2/runs/merged_ref_d15.pkl (seçim günleri)",
                  "untouched_final_read": False, "ktlev_in_grid": False},
        "base_rate": {"row_precision_base_by_delay": br, "event_sessions": n_ev,
                      "event_session_rate": n_ev / len(p.sessions), "non_event_sessions": len(p.sessions) - n_ev},
        "round1_final_by_delay": {"WATCH": {d: brief_point(m) for d, m in r1w.items()},
                                  "STRONG": {d: brief_point(m) for d, m in r1s.items()}},
        "watch_frontier": frontier_block(watch, br),
        "strong_frontier": frontier_block(strong, br),
        "strong_vs_watch": strong_vs_watch(watch, strong, r1w),
        "confirmation_cost_watch": confirm_cost(p, w_raw),
        "confirmation_cost_strong": confirm_cost(p, s_raw),
        "events": summarize_events(ev["events"]),
        "event_examples": [{kk: v for kk, v in e.items() if kk not in ("timeline_ns", "firsts_ns")}
                           | {"timeline": {kk: _clock(v) for kk, v in e["timeline_ns"].items()}}
                           for e in sorted(ev["events"], key=lambda e: -e["runup_pct"])[:12]],
        "fp_taxonomy_round1_watch_d15": fp_taxonomy_v2(p, w_final),
        "information_ceiling": {k: {"points": len(v), "frontier3_size": len(frontier3(v)),
                                    **frontier_answers(v, br[0] if "d0" in k else br[15])} for k, v in scen.items()},
        "ktlev_case": ktlev_case(),
        "elapsed_seconds": None,
    }
    result["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    write_json("audit.json", result)
    print("audit.json yazıldı", result["elapsed_seconds"], "sn")


# ------------------------------------------------------------------ yüzey noktalarının sağlamlığı (aşama "wf")
WATCH_TARGET = {"false_positive_rate": ("<=", 0.25), "recall": (">=", 0.40), "lead_fraction_median": ("<=", 0.50)}


def subset_labels(lab: fr.LabelArrays, sess: np.ndarray, keep_sess: np.ndarray):
    """Yalnız `keep_sess` (bool, seans başına) seanslarının satır/etiketleri; seans kimlikleri yeniden numaralanır."""
    r = keep_sess[sess]
    uniq, inv = np.unique(sess[r], return_inverse=True)
    sub = fr.LabelArrays(lab.t_ns[r], lab.entry[r], lab.mfe_close[r], lab.ret_close[r], lab.ok[r],
                         lab.sess_event[uniq], lab.sess_high_ns[uniq], lab.sess_high[uniq], lab.sess_run_low[uniq])
    return r, inv, sub


def final_for(p: Panel, cfg: dict) -> np.ndarray:
    if "feature" in cfg:
        vals = getattr(p, cfg["feature"])
        return p.ok & np.isfinite(vals) & (vals >= cfg["threshold"])
    return fr.confirm(p.watch_raw(cfg), p.seg_start, *cfg["confirm"])


def surface(p: Panel, rows_mask: np.ndarray, kind: str):
    """(yapılandırma, nihai alarm dizisi) üreteci. Tek öznitelik eşikleri YALNIZ `rows_mask` satırlarından."""
    if kind in ("composite", "composite_1of1", "all"):
        last_key, raw = None, None
        for cfg in grid(WATCH_GRID):  # "confirm" son anahtar → aynı ham kural ardışık gelir
            if kind == "composite_1of1" and cfg["confirm"] != (1, 1):
                continue
            rkey = tuple((k, v) for k, v in cfg.items() if k != "confirm")
            if rkey != last_key:
                last_key, raw = rkey, p.watch_raw(cfg)
            yield cfg, fr.confirm(raw, p.seg_start, *cfg["confirm"])
    if kind in ("composite_1of1", "all"):
        for feat in SINGLE_FEATURES:
            vals = getattr(p, feat)
            finite = vals[rows_mask & p.ok & np.isfinite(vals)]
            for q in QUANTILES:
                cfg = {"feature": feat, "quantile": q, "threshold": float(np.percentile(finite, q))}
                yield cfg, final_for(p, cfg)


def walk_forward_feasibility(p: Panel, only: tuple[str, ...] | None = None) -> dict:
    """Her senaryo için: eğitim bloklarında hedefi (YPO≤0.25, duyarlılık≥0.40, lead≤0.50, kesinlik≥1.5×taban)
    sağlayan en düşük lead'li nokta seçilir → sonraki (görülmemiş) blokta ölçülür. Seçim verisi içinde kalır."""
    sel_days, _ = selection_scope()
    day_of_sess = np.array([d for _, d in p.sessions])
    scenarios = {"A_d15_composite": (15, "composite"), "A_d15_composite_plus_single_1of1": (15, "all"),
                 "B_d0_composite": (0, "composite"), "C_d0_1of1": (0, "composite_1of1"),
                 "C15_d15_1of1": (15, "composite_1of1")}
    out = {}
    for name, (delay, kind) in scenarios.items():
        if only is not None and name not in only:
            continue
        folds = []
        for f in ds2.walk_forward_folds(sel_days):
            tr_s, va_s = np.isin(day_of_sess, f["train"]), np.isin(day_of_sess, f["validate"])
            tr_rows, tr_inv, tr_lab = subset_labels(p.labels[delay], p.sess, tr_s)
            va_rows, va_inv, va_lab = subset_labels(p.labels[delay], p.sess, va_s)
            base_tr = float((tr_lab.mfe_close[tr_lab.ok & np.isfinite(tr_lab.mfe_close)] >= X).mean())
            base_va = float((va_lab.mfe_close[va_lab.ok & np.isfinite(va_lab.mfe_close)] >= X).mean())
            pts = [{**fr.metrics(final[tr_rows], tr_inv, tr_lab, X), "config": cfg}
                   for cfg, final in surface(p, tr_rows, kind)]
            cons = {**WATCH_TARGET, "precision": (">=", 1.5 * base_tr)}
            pick = fr.best_under(pts, "lead_fraction_median", False, cons)
            feasible_train = pick is not None
            if pick is None:  # hedef eğitimde bile yok → YPO≤0.25 & duyarlılık≥0.40 altında en erken nokta
                pick = fr.best_under(pts, "lead_fraction_median", False,
                                     {"false_positive_rate": ("<=", 0.25), "recall": (">=", 0.40)})
            rec = {"fold": f["fold"], "feasible_on_train": feasible_train}
            if pick is not None:
                v = fr.metrics(final_for(p, pick["config"])[va_rows], va_inv, va_lab, X)
                passed = fr.best_under([v], "recall", True,
                                       {**WATCH_TARGET, "precision": (">=", 1.5 * base_va)}) is not None
                rec.update({"config": pick["config"],
                            "train": {k: pick[k] for k in ("precision", "recall", "false_positive_rate",
                                                           "lead_fraction_median")},
                            "validate": {k: v[k] for k in ("precision", "recall", "false_positive_rate",
                                                           "lead_fraction_median", "median_first_alert_minute")},
                            "validate_passes_target": passed})
            folds.append(rec)
        out[name] = {"folds": folds, "passes": sum(bool(r.get("validate_passes_target")) for r in folds)}
    return out


def wf_stage():
    started = clock.perf_counter()
    p = Panel(load_selection_rows())
    for d in (0, 15):
        p.build_labels(d)
    res = walk_forward_feasibility(p)
    res["target"] = {**{k: list(v) for k, v in WATCH_TARGET.items()}, "precision": [">=", "1.5x base"]}
    res["elapsed_seconds"] = round(clock.perf_counter() - started, 1)
    write_json("audit_wf.json", res)
    print(json.dumps(res, ensure_ascii=False, default=str))


def write_json(name, payload):
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main(stage: str):
    if stage == "audit":
        return audit()
    if stage == "wf":
        return wf_stage()
    if stage != "run":
        raise SystemExit(f"bilinmeyen aşama: {stage}")
    started = clock.perf_counter()
    p = Panel(load_selection_rows())
    for d in DELAYS:
        p.build_labels(d)
    print(f"panel: {len(p.rows)} satır, {len(p.sessions)} seans, {clock.perf_counter() - started:.0f} sn", flush=True)
    br = {d: base_rate(p, d) for d in DELAYS}
    # Tutarlılık: Round 1 final WATCH'ın vektörize metriği Round 2 değerlendirmesiyle aynı olmalı
    r1_raw = p.watch_raw(R1_FINAL_WATCH)
    r1_final = fr.confirm(r1_raw, p.seg_start, 3, 3)
    m15 = fr.metrics(r1_final, p.sess, p.labels[15], X)
    print("R1 final WATCH d15 (vektörize):", {k: m15[k] for k in ("precision", "recall", "false_positive_rate",
                                                                  "lead_fraction_median")}, flush=True)
    watch = sweep(p, "WATCH")
    strong = sweep(p, "STRONG")
    single = single_feature_sweep(p)
    print(f"ızgara: {len(watch)} WATCH, {len(strong)} STRONG, {len(single)} tek öznitelik noktası, "
          f"{clock.perf_counter() - started:.0f} sn", flush=True)
    delay_r1 = {d: fr.metrics(r1_final, p.sess, p.labels[d], X) for d in DELAYS}
    xs_raw = p.watch_raw({**R1_FINAL_WATCH, "xs": 0.9})
    xs_final = fr.confirm(xs_raw, p.seg_start, 3, 3)
    result = {
        "scope": {"assets": len({s for s, _ in p.sessions}), "sessions": len(p.sessions), "rows": len(p.rows),
                  "days": [str(min(d for _, d in p.sessions)), str(max(d for _, d in p.sessions))],
                  "untouched_final_read": False},
        "base_rate": br,
        "round1_final_watch_by_delay": delay_r1,
        "watch_frontier": summarize_frontier(watch, br),
        "strong_frontier": summarize_frontier(strong, br),
        "information_ceiling": {"A_d15_grid": summarize_frontier([q for q in watch if q["delay"] == 15], br)[15],
                                "B_d0_grid": summarize_frontier([q for q in watch if q["delay"] == 0], br)[0],
                                "C_oracle_envelope_d15": summarize_frontier(
                                    [q for q in watch + single if q["delay"] == 15], br)[15],
                                "C_oracle_envelope_d0": summarize_frontier(
                                    [q for q in watch + single if q["delay"] == 0], br)[0]},
        "confirmation_cost": confirmation_cost(p, {**R1_FINAL_WATCH, "confirm": (1, 1)}),
        "event_timing": event_timing(p, r1_final, r1_raw),
        "fp_taxonomy_round1_final_d15": fp_taxonomy(p, r1_final),
        "fp_taxonomy_raw_1of1_d15": fp_taxonomy(p, r1_raw),
        "fn_taxonomy_round1_final_d15": fn_taxonomy(p, r1_final, r1_raw, xs_raw),
        "xs_gate_round1_final_d15": fr.metrics(xs_final, p.sess, p.labels[15], X),
        "elapsed_seconds": round(clock.perf_counter() - started, 1),
    }
    write_json("feasibility.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("watch_frontier", "strong_frontier",
                                                                   "information_ceiling")},
                     ensure_ascii=False, default=str)[:6000])


if __name__ == "__main__":
    with au.candidate_selection():  # aday seçimi/yüzey: tüketilmiş final açılamaz
        main(sys.argv[1] if len(sys.argv) > 1 else "run")
