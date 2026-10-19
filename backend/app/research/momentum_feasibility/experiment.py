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


def load_selection_rows(loader=None) -> list[dict]:
    """Yalnız referans evren × seçim seansları. Final tarihleri ve yeni varlıklar burada elenir ve denetlenir."""
    loader = loader or r2.load_pkl
    sel_days, final_days = selection_scope()
    sel = set(sel_days)
    rows = [r for r in loader("merged_ref_d15.pkl") if r["day"] in sel]
    assert not any(r["day"] in final_days for r in rows)
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
                  "session_ret_z", "gap_pct", "breakout_dist_atr", "vol_accel"):
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


def write_json(name, payload):
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main(stage: str):
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
    main(sys.argv[1] if len(sys.argv) > 1 else "run")
