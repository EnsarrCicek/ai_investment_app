"""Momentum PILOT derin analizi — öznitelik ayrışabilirliği, YP ablasyonu, Round 1 WATCH ablasyonu, gerçek 1m
sinyalleri, ölçülmüş gecikme, gün-dışarıda doğrulama ve basit deneysel ML tabanı.

YALNIZ pilot seansları (PILOT / DEVELOPMENT ONLY). Hiçbir yapılandırma dondurulmaz, üretim değişmez, holdout
okunmaz. Izgara küçük ve ÖNCEDEN sabit (aşağıdaki sabitler sonuçlara bakılmadan yazıldı); "en iyi" görünen her ayar
"EXPERIMENTAL — NOT FROZEN" etiketlidir.

Zaman kavramları (UTC ns):
* bilgi zamanı = satırın kullandığı son 5m barın BİTİŞİ (`p.labels[0].t_ns`);
* d15 görünür zaman = bilgi zamanı + 15 dk (tarihsel varsayım);
* ölçülmüş görünür zaman = o son barın arşivdeki `first_seen` anı — yalnız bar canlı PROBE ile görüldüyse ÖLÇÜLMÜŞ;
  EOD ile (ertesi sabah) görülen barlarda canlı ölçüm yoktur → bilgi zamanı + ölçülmüş 5m prob gecikmesi medyanı
  (ESTIMATED_FROM_MEASURED_MEDIAN). Sabit 15 dk varsayılmaz.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_final import experiment as mf
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_pilot import analysis as an
from app.research.momentum_pilot import split as sp

EXPERIMENTAL = "EXPERIMENTAL — NOT FROZEN"
ML_LABEL = "EXPERIMENTAL ML BASELINE"
MIN_NS = au.MIN_NS
BAR_NS = 5 * MIN_NS

FEATURES = ("price_z", "ret_z_3", "ret_z_12", "accel", "accel_pos_3", "rel_ret_z_3", "xs_ret", "relvol_3",
            "volume_anomaly", "breakout", "breakout_dist_atr", "vwap_reclaim", "gap_pct", "session_ret_z",
            "recent_locked_regime", "regime_shock")
# Hiçbir ML/öznitelik girdisinde bulunamaz (gelecek bilgisi / etiket türevleri)
FORBIDDEN_INPUTS = ("entry", "mfe", "mfe_close", "mfe_60", "ret_close", "future_high", "future_low", "future_volume",
                    "event_peak", "event_start", "peak", "lead", "lead_fraction", "sess_high", "sess_high_ns",
                    "sess_run_low", "sess_event", "label", "y", "caught", "outcome", "high_time", "max_runup")

# Önceden sabit küçük ızgara
VOLUME_GATES = {"weak": ("relvol_3", 1.0), "medium": ("relvol_3", 1.5)}  # postmortem VOLUME_GATES ile aynı
PARTICIPATION = 0.5  # Round 1 kanıt eşiği (volume_anomaly)
REL_GATE = 1.0  # fx WATCH_GRID "rel"
ACCEL_GATE = 0.5  # fx WATCH_GRID "accel" (accel ≥ 0.5 ∧ accel_pos_3 ≥ 2)
LR_L2 = 1.0
LR_ITER = 50
ML_ALERT_QUANTILE = 99.0  # eşik = eğitim günleri olasılıklarının 99. yüzdeliği
CLIP_Z = 8.0

# 1m ↔ 5m (analysis ile aynı pencere; ek iki sinyal)
REL_RET_MIN = 0.01  # 15 dk varlık getirisi − XU100 15 dk getirisi ≥ %1
VOL_ACCEL_MULT = 2.0  # son 15 dk hacmi ≥ 2 × önceki 15 dk hacmi


# ------------------------------------------------------------------ değerlendirme (alt küme)
def scenario_arrays(p, key) -> tuple[np.ndarray, np.ndarray]:
    lab = p.labels[key]
    return lab.t_ns, lab.entry


def evaluate_subset(p, events, mask: np.ndarray, key, days: set | None = None) -> dict:
    """Seçili günlerin seanslarında V2 birincil metrikleri (seanslar yeniden numaralanır; diğer günler yok sayılır)."""
    t_ns, entry = scenario_arrays(p, key)
    keep_sess = [s for s, (_, d) in enumerate(p.sessions) if days is None or d in days]
    remap = {s: k for k, s in enumerate(keep_sess)}
    idx = np.flatnonzero(np.isin(p.sess, keep_sess))
    sess = np.array([remap[int(s)] for s in p.sess[idx]], dtype=int)
    first = {}
    for i, s in enumerate(sess):
        first.setdefault(s, i)
    seg = np.array([first[s] for s in sess], dtype=int)
    m = lv.evaluate(mask[idx], sess, seg, t_ns[idx], entry[idx], [events[s] for s in keep_sess], lv.FIRST_ALERT)
    return {"alerts": m["alerts"], "TP": m["alert_classes"][lv.IN_EVENT],
            "FP": m["alerts"] - m["alert_classes"][lv.IN_EVENT], "precision_v2": m["precision_v2"],
            "recall_evaluable_v2": m["recall_evaluable_v2"], "recall_raw_v2": m["recall_raw_v2"],
            "FPR_v2": m["FPR_v2"], "specificity_v2": m["specificity_v2"], "median_lead_v2": m["median_lead_v2"],
            "pre_event_alerts": m["alert_classes"][lv.PRE_EVENT], "post_peak_alerts": m["alert_classes"][lv.POST_PEAK],
            "pre_event_alert_rate": m["pre_event_alert_rate"], "post_peak_alert_rate": m["post_peak_alert_rate"],
            "median_first_alert_time": fx._hm(m["median_first_alert_minute"]),
            "sessions": m["sessions"], "events_raw": m["event_count_raw"], "evaluable_events": m["event_count_evaluable"],
            "non_event_sessions": m["non_event_sessions"]}


def first_alert_classes(p, events, mask: np.ndarray, key) -> dict[int, str]:
    t_ns, _ = scenario_arrays(p, key)
    uniq, rows = fr.first_alert_rows(mask, p.sess)
    return {int(s): lv.match_alerts([int(t_ns[i])], events[s])[0][0] for s, i in zip(uniq, rows)}


def removal(p, events, base: np.ndarray, variant: np.ndarray, key=15) -> dict:
    """Varyantın taban kurala göre neyi kaldırdığı (seans düzeyinde ilk alarm)."""
    b, v = first_alert_classes(p, events, base, key), first_alert_classes(p, events, variant, key)
    out = Counter()
    for s, c in b.items():
        if s not in v:
            out["removed_true_positive" if c == lv.IN_EVENT else "removed_false_alert"] += 1
        elif v[s] != c:
            out[f"shifted_{c}_to_{v[s]}"] += 1
    for s in v:
        if s not in b:
            out["new_session"] += 1
    return dict(out)


# ------------------------------------------------------------------ öznitelikler
def feature_matrix(p) -> np.ndarray:
    """Satır × FEATURES (NaN = eksik). Yalnız değerlendirme anında bilinen panel öznitelikleri."""
    cols = []
    for f in FEATURES:
        if f == "recent_locked_regime":
            cols.append(p.locked.astype(float))
        elif f == "regime_shock":
            cols.append(p.regime_shock.astype(float))
        else:
            cols.append(np.asarray(getattr(p, f), dtype=float))
    return np.column_stack(cols)


def auc(pos: np.ndarray, neg: np.ndarray) -> float | None:
    """Mann–Whitney AUC (bağlarda ortalama sıra)."""
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if not len(pos) or not len(neg):
        return None
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def cohens_d(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return None
    sd = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    return float((a.mean() - b.mean()) / sd) if sd > 0 else None


def event_window_rows(p, events, key=0, evaluable_only=True) -> np.ndarray:
    """Zamanı (senaryo `key`) bir değerlendirilebilir olayın [başlangıç, tepe] penceresinde olan satırlar."""
    t = p.labels[key].t_ns
    out = np.zeros(len(p.rows), dtype=bool)
    for i, s in enumerate(p.sess):
        out[i] = any((ev.evaluable or not evaluable_only) and ev.start_ns <= t[i] <= ev.peak_ns for ev in events[s])
    return out


def separability(p, events, watch_mask: np.ndarray) -> dict:
    X = feature_matrix(p)
    ev_rows = p.ok & event_window_rows(p, events, 0)
    non = p.ok & np.array([not events[s] for s in p.sess])
    cls = first_alert_classes(p, events, watch_mask, 15)
    uniq, rows = fr.first_alert_rows(watch_mask, p.sess)
    tp = np.zeros(len(p.rows), bool)
    fp = np.zeros(len(p.rows), bool)
    for s, i in zip(uniq, rows):
        (tp if cls[int(s)] == lv.IN_EVENT else fp)[i] = True
    out = {}
    for j, f in enumerate(FEATURES):
        x = X[:, j]
        a, b = x[ev_rows], x[non]
        out[f] = {"event_median": _med(a), "non_event_median": _med(b), "TP_median": _med(x[tp]),
                  "FP_median": _med(x[fp]), "effect_size_cohens_d": _round(cohens_d(a, b)),
                  "roc_auc_diagnostic": _round(auc(a, b)), "missing_rate": _round(float(np.isnan(x[p.ok]).mean()))}
    return {"label": sp.PILOT_LABEL, "rows_event_window": int(ev_rows.sum()), "rows_non_event": int(non.sum()),
            "TP_rows": int(tp.sum()), "FP_rows": int(fp.sum()),
            "groups": "event = status-OK rows whose information time lies in an evaluable V2 event window; "
                      "non-event = status-OK rows of sessions without any V2 event; TP/FP = Round 1 WATCH first "
                      "alerts (d15) IN_EVENT vs not",
            "features": out}


def _med(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return round(float(np.median(x)), 4) if len(x) else None


def _round(v, n=4):
    return None if v is None else round(float(v), n)


# ------------------------------------------------------------------ kural varyantları
def gate(p, name: str, thr: float) -> np.ndarray:
    g = np.asarray(getattr(p, name), dtype=float)
    return np.isfinite(g) & (g >= thr)


# ÖNCEDEN İLAN EDİLMİŞ IZGARA (5 günlük metrikler görülmeden sabitlendi). Kapılar satır düzeyinde uygulanır;
# Round 1 WATCH ailesinde göreli güç / ivme `watch_raw` yapılandırmasıyla; doğrulama her zaman 3/3 (değişmez).
GATES = {"weak_volume": "relvol_3 >= 1.0", "medium_volume": "relvol_3 >= 1.5",
         "benchmark_shock_filter": "market regime != SHOCK",
         "relative_strength": "rel_ret_z_3 >= 1.0 (NaN passes, Round 1 grid semantics)",
         "acceleration": "accel >= 0.5 and accel_pos_3 >= 2"}
GRID: dict[str, dict] = {
    "C0_frozen_candidate": {"base": "C", "gates": ()},
    "C1_+weak_volume": {"base": "C", "gates": ("weak_volume",)},
    "C2_+medium_volume": {"base": "C", "gates": ("medium_volume",)},
    "C3_+benchmark_shock_filter": {"base": "C", "gates": ("benchmark_shock_filter",)},
    "C4_+weak_volume+benchmark": {"base": "C", "gates": ("weak_volume", "benchmark_shock_filter")},
    "A0_round1_watch": {"base": "A", "gates": ()},
    "A1_+benchmark_shock_filter": {"base": "A", "gates": ("benchmark_shock_filter",)},
    "A2_+weak_volume": {"base": "A", "gates": ("weak_volume",)},
    "A3_+relative_strength": {"base": "A", "gates": ("relative_strength",)},
    "A4_+acceleration": {"base": "A", "gates": ("acceleration",)},
    "A5a_benchmark+weak_volume": {"base": "A", "gates": ("benchmark_shock_filter", "weak_volume")},
    "A5b_benchmark+relative": {"base": "A", "gates": ("benchmark_shock_filter", "relative_strength")},
    "A5c_benchmark+acceleration": {"base": "A", "gates": ("benchmark_shock_filter", "acceleration")},
    "A5d_weak_volume+relative": {"base": "A", "gates": ("weak_volume", "relative_strength")},
    "A5e_weak_volume+acceleration": {"base": "A", "gates": ("weak_volume", "acceleration")},
    "A5f_relative+acceleration": {"base": "A", "gates": ("relative_strength", "acceleration")},
}
BASES = {"A": "Round 1 final WATCH (price_impulse >= 0.5, score >= 40, participation or structure), confirmation 3/3",
         "C": "historical frozen candidate rel_ret_z_3 >= 5.094139728812382, confirmation 1/1"}


def grid_mask(p, cand: dict, spec: dict) -> np.ndarray:
    gates = spec["gates"]
    unknown = set(gates) - set(GATES)
    if unknown:
        raise ValueError(f"ilan edilmemiş kapı: {unknown}")
    row = np.ones(len(p.rows), dtype=bool)
    if "weak_volume" in gates:
        row &= gate(p, *VOLUME_GATES["weak"])
    if "medium_volume" in gates:
        row &= gate(p, *VOLUME_GATES["medium"])
    if "benchmark_shock_filter" in gates:
        row &= ~p.regime_shock
    if spec["base"] == "C":
        if {"relative_strength", "acceleration"} & set(gates):
            raise ValueError("C ailesinde göreli güç / ivme kapısı ilan edilmedi")
        return mf.candidate_alerts(p, cand) & row
    cfg = {**fx.R1_FINAL_WATCH, "rel": REL_GATE if "relative_strength" in gates else None,
           "accel": ACCEL_GATE if "acceleration" in gates else None}
    return fr.confirm(p.watch_raw(cfg) & row, p.seg_start, 3, 3)


def grid_masks(p, cand: dict, family: str) -> dict[str, np.ndarray]:
    return {name: grid_mask(p, cand, spec) for name, spec in GRID.items() if spec["base"] == family}


def variant_table(p, events, masks: dict[str, np.ndarray], keys=(15, "measured")) -> dict:
    base_name = next(iter(masks))
    out = {}
    for name, m in masks.items():
        out[name] = {f"d{k}" if isinstance(k, int) else k: evaluate_subset(p, events, m, k) for k in keys}
        out[name]["removes_vs_base_d15"] = removal(p, events, masks[base_name], m) if name != base_name else {}
    return out


# ------------------------------------------------------------------ ölçülmüş görünürlük
def measured_visibility(p, b5: pd.DataFrame) -> dict:
    """Satır başına ölçülmüş görünür zaman + giriş fiyatı. `p.labels['measured']` olarak eklenir."""
    probe = b5[b5["collection_mode"] == "PROBE"]
    lat = ((probe["first_seen_ns"] - probe["bar_end_ns"]).to_numpy(float))
    median_ns = int(np.median(lat)) if len(lat) else 15 * MIN_NS
    seen = {(s, int(b)): (int(f), m) for s, b, f, m in b5[["symbol", "bar_start_ns", "first_seen_ns",
                                                             "collection_mode"]].itertuples(index=False)}
    info = p.labels[0].t_ns
    vis = np.zeros(len(p.rows), dtype=np.int64)
    measured = np.zeros(len(p.rows), dtype=bool)
    for i, r in enumerate(p.rows):
        got = seen.get((r["symbol"], int(info[i]) - BAR_NS))
        if got is not None and got[1] == "PROBE":
            vis[i], measured[i] = max(got[0], int(info[i])), True
        else:
            vis[i] = int(info[i]) + median_ns
    entry = np.full(len(p.rows), np.nan)
    by_sess = defaultdict(list)
    for i, s in enumerate(p.sess):
        by_sess[int(s)].append(i)
    for s, idx in by_sess.items():
        sym, day = p.sessions[s]
        d = p.bars[sym].dropna()
        d = d[d.index.date == day]
        starts, opens = d.index.as_unit("ns").asi8, d["Open"].to_numpy(float)
        j = np.searchsorted(starts, vis[idx], side="left")
        ok = j < len(starts)
        entry[np.array(idx)[ok]] = opens[j[ok]]
    lab15 = p.labels[15]
    p.labels["measured"] = fr.LabelArrays(vis, entry, lab15.mfe_close, lab15.ret_close, lab15.ok, lab15.sess_event,
                                          lab15.sess_high_ns, lab15.sess_high, lab15.sess_run_low)
    return {"median_probe_latency_5m_min": median_ns / MIN_NS, "rows_measured_live": int(measured.sum()),
            "rows_estimated": int((~measured).sum()), "measured_mask": measured}


def latency_view(p, events, rules: dict[str, np.ndarray], measured_mask: np.ndarray) -> dict:
    info, vis, v15 = p.labels[0].t_ns, p.labels["measured"].t_ns, p.labels[15].t_ns
    out = {}
    for name, m in rules.items():
        uniq, rows = fr.first_alert_rows(m, p.sess)
        meas = [i for i in rows if measured_mask[i]]
        lag = [(vis[i] - info[i]) / MIN_NS for i in meas]
        out[name] = {"first_alerts": int(len(rows)), "with_live_measured_first_seen": len(meas),
                     "median_information_time": _clock_med(info[rows]),
                     "median_provider_visible_time": _clock_med(vis[rows]),
                     "measured_visible_minus_information_min": {"n": len(lag), "median": _med(lag),
                                                                "min": _round(min(lag)) if lag else None,
                                                                "max": _round(max(lag)) if lag else None},
                     "metrics_information_time_d0": evaluate_subset(p, events, m, 0),
                     "metrics_measured_visibility": evaluate_subset(p, events, m, "measured"),
                     "metrics_assumed_d15": evaluate_subset(p, events, m, 15)}
    return out


def _clock_med(ns):
    ns = np.asarray(ns)
    if not len(ns):
        return None
    minutes = (ns // MIN_NS + 180) % 1440
    return fx._hm(float(np.median(minutes)))


# ------------------------------------------------------------------ gün-dışarıda (LODO) ve seçim kuralları
# ÖNCEDEN SABİT keşif seçim kuralları (5 günlük metrikler görülmeden yazıldı)
SCENARIO = "measured"  # birincil: ölçülmüş (yoksa ölçülmüş medyandan tahmini) sağlayıcı görünürlüğü
TARGETS = {"FPR_v2_max": 0.25, "recall_evaluable_v2_min": 0.40, "median_lead_v2_max": 0.50}
CATASTROPHIC = {"recall_evaluable_v2_below": 0.20, "FPR_v2_above": 0.40, "median_lead_v2_above": 0.75}
MAX_CATASTROPHIC_FOLDS = 1
SELECTION_RULES = {
    "scenario": SCENARIO, "pooled_targets": TARGETS, "fold_targets": TARGETS,
    "catastrophic_fold": CATASTROPHIC, "max_catastrophic_folds": MAX_CATASTROPHIC_FOLDS,
    "eligibility": "pooled 5-day metrics meet ALL targets AND at most 1 catastrophic leave-one-day-out fold",
    "tie_break": ["fewer gates", "more folds meeting all targets", "fewer catastrophic folds",
                  "higher pooled precision_v2", "name"],
    "excluded_from_auto_selection": ["EXPERIMENTAL ML BASELINE"],
    "no_candidate_policy": "if nothing is eligible: NO CANDIDATE - MORE PILOT/DESIGN WORK REQUIRED"}


def meets_targets(m: dict, t: dict = TARGETS) -> bool:
    return (m["FPR_v2"] is not None and m["FPR_v2"] <= t["FPR_v2_max"]
            and m["recall_evaluable_v2"] is not None and m["recall_evaluable_v2"] >= t["recall_evaluable_v2_min"]
            and m["median_lead_v2"] is not None and m["median_lead_v2"] <= t["median_lead_v2_max"])


def catastrophic(m: dict, c: dict = CATASTROPHIC) -> bool:
    if m["evaluable_events"] and (m["recall_evaluable_v2"] or 0.0) < c["recall_evaluable_v2_below"]:
        return True
    if m["FPR_v2"] is not None and m["FPR_v2"] > c["FPR_v2_above"]:
        return True
    return m["median_lead_v2"] is not None and m["median_lead_v2"] > c["median_lead_v2_above"]


def _agg(vals):
    v = [x for x in vals if x is not None]
    return {"median": _round(np.median(v)) if v else None, "min": _round(min(v)) if v else None,
            "max": _round(max(v)) if v else None}


def lodo_grid(p, events, masks: dict[str, np.ndarray], days: list, key=SCENARIO) -> dict:
    """Her kural için gün başına katlama: kurallar sabit (eğitimde uydurulan parametre yok); doğrulama günü metrikleri."""
    out = {}
    for name, m in masks.items():
        folds = []
        for d, train in day_folds(days):
            v = evaluate_subset(p, events, m, key, {d})
            folds.append({"validation_day": str(d), "development_days": [str(x) for x in train],
                          **{k: v[k] for k in ("alerts", "TP", "FP", "precision_v2", "recall_evaluable_v2", "FPR_v2",
                                               "median_lead_v2", "evaluable_events", "non_event_sessions")},
                          "meets_targets": meets_targets(v), "catastrophic": catastrophic(v)})
        out[name] = {"folds": folds,
                     **{k: _agg([f[k] for f in folds]) for k in ("precision_v2", "recall_evaluable_v2", "FPR_v2",
                                                                   "median_lead_v2", "alerts")},
                     "folds_meeting_targets": sum(f["meets_targets"] for f in folds),
                     "catastrophic_folds": sum(f["catastrophic"] for f in folds)}
    return out


def select_candidate(pooled: dict[str, dict], lodo_res: dict[str, dict], grid: dict = GRID) -> dict:
    """Önceden sabit kurallarla seçim. `pooled[name]` = birincil senaryoda 5 günlük metrikler. ML aday olamaz."""
    rows = []
    for name in grid:
        if name not in pooled:
            continue
        m, lo = pooled[name], lodo_res[name]
        ok_pooled = meets_targets(m)
        ok_stable = lo["catastrophic_folds"] <= MAX_CATASTROPHIC_FOLDS
        failed = [k for k, bad in (("FPR_v2", m["FPR_v2"] is None or m["FPR_v2"] > TARGETS["FPR_v2_max"]),
                                   ("recall_evaluable_v2", (m["recall_evaluable_v2"] or 0)
                                    < TARGETS["recall_evaluable_v2_min"]),
                                   ("median_lead_v2", m["median_lead_v2"] is None
                                    or m["median_lead_v2"] > TARGETS["median_lead_v2_max"])) if bad]
        rows.append({"name": name, "eligible": ok_pooled and ok_stable, "pooled_meets_targets": ok_pooled,
                     "failed_targets": failed, "catastrophic_folds": lo["catastrophic_folds"],
                     "folds_meeting_targets": lo["folds_meeting_targets"], "n_gates": len(grid[name]["gates"]),
                     "precision_v2": m["precision_v2"]})
    eligible = sorted((r for r in rows if r["eligible"]),
                      key=lambda r: (r["n_gates"], -r["folds_meeting_targets"], r["catastrophic_folds"],
                                     -(r["precision_v2"] or 0), r["name"]))
    return {"rules": SELECTION_RULES, "table": rows, "selected": eligible[0]["name"] if eligible else None,
            "decision": "CANDIDATE" if eligible else "NO CANDIDATE - MORE PILOT/DESIGN WORK REQUIRED"}


# ------------------------------------------------------------------ deneysel ML (numpy lojistik regresyon)
def ml_labels(p, events) -> np.ndarray:
    """y = 1 ⇔ satırın d15 görünür zamanı bir değerlendirilebilir V2 olay penceresinde (alarm burada olsa TP)."""
    return event_window_rows(p, events, 15).astype(float)


class Standardizer:
    def fit(self, X: np.ndarray) -> "Standardizer":
        self.med = np.nanmedian(np.where(np.isfinite(X), X, np.nan), axis=0)
        self.med = np.where(np.isfinite(self.med), self.med, 0.0)
        Z = self._impute(X)
        self.mu, self.sd = Z.mean(axis=0), Z.std(axis=0)
        self.sd = np.where(self.sd > 0, self.sd, 1.0)
        return self

    def _impute(self, X):
        return np.where(np.isfinite(X), X, self.med)

    def transform(self, X):
        return np.clip((self._impute(X) - self.mu) / self.sd, -CLIP_Z, CLIP_Z)


def fit_logistic(Z: np.ndarray, y: np.ndarray, l2: float = LR_L2, iters: int = LR_ITER) -> np.ndarray:
    """Dengeli sınıf ağırlıklı, L2 cezalı lojistik regresyon (IRLS/Newton; deterministik). [b0, w...]."""
    n, k = Z.shape
    A = np.column_stack([np.ones(n), Z])
    pos = y.sum()
    w_s = np.where(y == 1, n / (2 * max(pos, 1)), n / (2 * max(n - pos, 1)))
    beta = np.zeros(k + 1)
    reg = np.full(k + 1, l2)
    reg[0] = 0.0
    for _ in range(iters):
        pr = 1 / (1 + np.exp(-np.clip(A @ beta, -30, 30)))
        g = A.T @ (w_s * (pr - y)) + reg * beta
        H = (A * (w_s * pr * (1 - pr))[:, None]).T @ A + np.diag(reg)
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def predict(beta: np.ndarray, Z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(beta[0] + Z @ beta[1:], -30, 30)))


def day_folds(days: list) -> list[tuple]:
    """Gün-gruplu bölme: her gün bir kez test; eğitim = diğer günler (aynı gün iki tarafta olamaz)."""
    return [(d, tuple(x for x in days if x != d)) for d in days]


def ml_baseline(p, events, days: list) -> dict:
    X = feature_matrix(p)
    y = ml_labels(p, events)
    day_of = np.array([p.sessions[s][1] for s in p.sess])
    oof = np.zeros(len(y))
    alert = np.zeros(len(y), dtype=bool)
    folds, coefs = [], []
    for d, train_days in day_folds(days):
        tr, te = p.ok & np.isin(day_of, list(train_days)), p.ok & (day_of == d)
        st = Standardizer().fit(X[tr])
        beta = fit_logistic(st.transform(X[tr]), y[tr])
        coefs.append(beta[1:])
        thr = float(np.percentile(predict(beta, st.transform(X[tr])), ML_ALERT_QUANTILE))
        oof[te] = predict(beta, st.transform(X[te]))
        alert[te] = oof[te] >= thr
        m15 = evaluate_subset(p, events, alert, 15, {d})
        folds.append({"held_out": str(d), "train_rows": int(tr.sum()), "test_rows": int(te.sum()),
                      "test_positive_rows": int(y[te].sum()), "row_auc": _round(auc(oof[te & (y == 1)],
                                                                                   oof[te & (y == 0)])),
                      "alert_threshold": round(thr, 4), "metrics_d15": m15,
                      "metrics_measured": evaluate_subset(p, events, alert, "measured", {d})})
    st = Standardizer().fit(X[p.ok])
    full = fit_logistic(st.transform(X[p.ok]), y[p.ok])
    signs = np.sign(np.array(coefs))
    importance = {f: {"coef_full_pilot_standardized": round(float(full[j + 1]), 4),
                      "fold_coefs": [round(float(c[j]), 4) for c in coefs],
                      "sign_stable_across_folds": bool(abs(signs[:, j].sum()) == len(days))}
                  for j, f in enumerate(FEATURES)}
    importance = dict(sorted(importance.items(), key=lambda kv: -abs(kv[1]["coef_full_pilot_standardized"])))
    return {"label": ML_LABEL, "model": "logistic regression (numpy IRLS), L2=1.0, balanced class weights, median "
                                        "imputation + standardization fitted on training days only, z clipped ±8",
            "target": "row visible (d15) inside an evaluable MOMENTUM_EVENT_LABEL_V2 window",
            "alert_policy": f"probability >= {ML_ALERT_QUANTILE}th percentile of training-day probabilities; first "
                            "alert per asset-session",
            "validation": "leave-one-day-out (day-grouped)", "features": list(FEATURES),
            "pooled_out_of_fold": {"row_auc": _round(auc(oof[p.ok & (y == 1)], oof[p.ok & (y == 0)])),
                                   "metrics_d15": evaluate_subset(p, events, alert, 15),
                                   "metrics_measured": evaluate_subset(p, events, alert, "measured")},
            "folds": folds, "feature_importance": importance, "_oof": oof, "_alert": alert}


# ------------------------------------------------------------------ sızıntı denetimi
def static_leakage_check(features=FEATURES) -> dict:
    bad = [f for f in features if any(f == x or f.startswith(x + "_") for x in FORBIDDEN_INPUTS)]
    return {"forbidden_inputs_in_features": bad, "ok": not bad}


def truncation_audit(ctx: dict, n: int = 60, seed: int = 0) -> dict:
    """Örnek satırlarda öznitelikleri, varlık ve gösterge barları bilgi zamanında KESİLMİŞ veriyle yeniden hesaplar;
    tam veriyle aynı olmalı (öznitelik zaman damgası ≤ bilgi zamanı). Kesitsel alanlar (xs_ret, rejim) aynı andaki
    diğer varlıkların aynı nedensel satırlarından türetilir; burada ayrıca yeniden kurulmaz."""
    from app.research.momentum_calibration import dataset as r1ds
    from app.research.momentum_round2 import experiment as r2
    from app.services.momentum.early_momentum_engine import compute_features
    from app.research.momentum_calibration import experiment as r1x
    p, data, bench = ctx["p"], ctx["data"], ctx["bench"]
    rng = np.random.default_rng(seed)
    cand = np.flatnonzero(p.ok)
    pick = np.sort(rng.choice(cand, size=min(n, len(cand)), replace=False))
    info = p.labels[0].t_ns
    config = r1x.config_for("F1", delay=an.DELAY)
    ext_keys = [f for f in FEATURES if f not in ("xs_ret", "regime_shock", "recent_locked_regime", "volume_anomaly",
                                                 "breakout")]
    mism, checked = [], 0
    for i in pick:
        r = p.rows[i]
        cut = pd.Timestamp(int(info[i]) - BAR_NS, tz="UTC")

        def trunc(a):
            return r1ds.AssetData(a.symbol, a.bars[a.bars.index <= cut], a.provenance, a.fetched_at)
        short = trunc(data[r["symbol"]])
        snap_s = compute_features(r["symbol"], r1ds.window_for(short, r["day"]), short.provenance, r["t"], config,
                                  None)
        comp_full, comp_short = r["components"] or {}, snap_s.components or {}
        ext_s = [x for x in r2.ext_rows_for_day(short, trunc(bench), r["day"], an.DELAY) if x["t"] == r["t"]]
        checked += 1
        diffs = [k for k in ("price_impulse", "volume_anomaly", "breakout") if not _same(comp_full.get(k),
                                                                                        comp_short.get(k))]
        if snap_s.status != r["status"]:
            diffs.append("status")
        metrics_s = snap_s.metrics or {}
        for k in ext_keys:
            if ext_s and k in ext_s[0]:
                ref = ext_s[0][k]
            elif k in metrics_s:
                ref = metrics_s[k]
            elif not ext_s and r.get(k) is None:
                continue
            else:
                diffs.append(f"{k}:not_recomputable")
                continue
            if not _same(r.get(k), ref):
                diffs.append(k)
        if diffs:
            mism.append({"symbol": r["symbol"], "t": str(r["t"]), "fields": diffs})
    return {"rows_checked": checked, "rows_with_mismatch": len(mism), "examples": mism[:5],
            "ok": not mism, "definition": "feature recomputed from bars with bar_start <= information_time - 5min "
                                          "(asset and XU100) equals the stored feature"}


def _same(a, b) -> bool:
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    if b is None or (isinstance(b, float) and np.isnan(b)):
        return False
    if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
        return bool(a) == bool(b)
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))


# ------------------------------------------------------------------ gerçek 1m sinyalleri
def signal_times(day: pd.DataFrame, bench_day: pd.DataFrame | None, bar_min: int, vol_base: float | None,
                 start_ns: int, end_ns: int) -> dict:
    """Aynı tanımlar her çözünürlükte (15 dk pencere). `day` / `bench_day` arşivlenmiş FIRST_SEEN barları."""
    n = an.WINDOW_MIN // bar_min
    day = day.sort_values("bar_start_ns").reset_index(drop=True)
    starts = day["bar_start_ns"].to_numpy()
    t_end = starts + bar_min * MIN_NS
    close, low = day["close"].to_numpy(float), day["low"].to_numpy(float)
    idx = pd.DatetimeIndex(pd.to_datetime(starts, utc=True))
    lag = idx - pd.Timedelta(minutes=an.WINDOW_MIN)
    # zaman tabanlı pencere: geriye bakış barı / pencerenin tüm barları arşivde yoksa değer YOK (doldurma yok)
    c = pd.Series(close, index=idx)
    ret = close / c.reindex(lag).to_numpy() - 1
    prev = pd.Series(ret, index=idx).reindex(lag).to_numpy()
    v = pd.Series(day["volume"].to_numpy(float), index=idx)
    roll_s = v.rolling(f"{an.WINDOW_MIN}min").sum()
    roll_s[v.rolling(f"{an.WINDOW_MIN}min").count() < n] = np.nan
    roll = roll_s.to_numpy()
    roll_prev = roll_s.reindex(lag).to_numpy()
    rel = np.full(len(day), np.nan)
    if bench_day is not None and len(bench_day):
        b = pd.Series(bench_day["close"].to_numpy(float),
                      index=pd.DatetimeIndex(pd.to_datetime(bench_day["bar_start_ns"].to_numpy(), utc=True)))
        rel = ret - (b.reindex(idx).to_numpy() / b.reindex(lag).to_numpy() - 1)
    conds = {"price_impulse": close >= np.minimum.accumulate(low) * (1 + an.PRICE_RISE),
             "acceleration": (np.nan_to_num(ret, nan=-1) >= an.ACCEL_MIN_RET)
             & (~np.isfinite(prev) | (np.nan_to_num(ret) > np.nan_to_num(prev, nan=-9))),
             "relative_return": np.nan_to_num(rel, nan=-1) >= REL_RET_MIN,
             "volume_acceleration": np.isfinite(roll_prev) & (roll_prev > 0)
             & (np.nan_to_num(roll) >= VOL_ACCEL_MULT * np.nan_to_num(roll_prev, nan=np.inf)),
             "volume_anomaly": (np.nan_to_num(roll) >= an.VOLUME_MULT * vol_base) if vol_base
             else np.zeros(len(day), bool)}
    win = (t_end >= start_ns) & (t_end <= end_ns)
    out = {}
    for k, c in conds.items():
        hit = np.flatnonzero(c & win)
        out[k] = int(t_end[hit[0]]) if len(hit) else None
    both = [out["price_impulse"], *(out[k] for k in ("volume_acceleration", "volume_anomaly", "relative_return"))]
    out["first_useful_signal"] = (max(out["price_impulse"], min(x for x in both[1:] if x is not None))
                                  if out["price_impulse"] is not None and any(x is not None for x in both[1:])
                                  else None)
    return out


SIGNALS = ("price_impulse", "acceleration", "relative_return", "volume_acceleration", "volume_anomaly",
           "first_useful_signal")


def probe_seen(bars: pd.DataFrame) -> tuple[dict, int]:
    """(PROBE ile canlı görülen barlar: (sembol, bar_start_ns) → first_seen_ns, ölçülmüş medyan gecikme ns)."""
    pr = bars[bars["collection_mode"] == "PROBE"]
    lat = (pr["first_seen_ns"] - pr["bar_end_ns"]).to_numpy(float)
    seen = {(sym, int(b)): int(f) for sym, b, f in pr[["symbol", "bar_start_ns", "first_seen_ns"]]
            .itertuples(index=False)}
    return seen, int(np.median(lat)) if len(lat) else 15 * MIN_NS


def visible_time(seen: dict, median_ns: int, symbol: str, info_ns: int | None, bar_min: int) -> tuple:
    """Sinyalin görünür zamanı: sinyali taşıyan barın canlı first_seen'i (ölçülmüş) yoksa bilgi zamanı + o aralığın
    ölçülmüş medyan gecikmesi (tahmini)."""
    if info_ns is None:
        return None, None
    got = seen.get((symbol, int(info_ns) - bar_min * MIN_NS))
    return (max(got, int(info_ns)), "MEASURED") if got is not None else (int(info_ns) + median_ns, "ESTIMATED")


def one_minute_study(table: list[dict], ev_by_key: dict, b5: pd.DataFrame, b1: pd.DataFrame, bench: str) -> dict:
    seen = {5: probe_seen(b5), 1: probe_seen(b1)}
    g5 = {k: g for k, g in b5.groupby(["symbol", "session_date"])}
    g1 = {k: g for k, g in b1.groupby(["symbol", "session_date"])}
    per, skipped, base = [], Counter(), {}
    for rec in table:
        key = (rec["symbol"], rec["session"])
        ev = ev_by_key[(rec["symbol"], rec["session"], rec["event_k"])]
        start, end = ev.start_ns, ev.peak_ns + BAR_NS
        if key not in g1:
            skipped["no_1m_bars"] += 1
            continue
        d1 = g1[key]
        expected = (end - start) // MIN_NS
        have = int(((d1["bar_start_ns"] >= start) & (d1["bar_start_ns"] < end)).sum())
        if have < 0.8 * expected:
            skipped["1m_window_coverage_below_80pct"] += 1
            continue
        times = {}
        for res, src, grp in ((5, b5, g5), (1, b1, g1)):
            bk = (rec["symbol"], rec["session"], res)
            if bk not in base:
                base[bk] = an.volume_baseline(src[(src["symbol"] == rec["symbol"])
                                                  & (src["session_date"] < rec["session"])], res)
            times[res] = signal_times(grp[key], grp.get((bench, rec["session"])), res, base[bk], start, end)
        row = {"symbol": rec["symbol"], "session": rec["session"], "event_start": rec["event_start"],
               "event_peak": rec["event_peak"], "runup_pct": rec["runup_pct"],
               "early_move_group": rec["early_move_group"]}
        for k in SIGNALS:
            t5, t1 = times[5][k], times[1][k]
            (v5, s5), (v1, s1) = (visible_time(*seen[5], rec["symbol"], t5, 5),
                                  visible_time(*seen[1], rec["symbol"], t1, 1))
            row[k] = {"5m": an._clock(t5), "1m": an._clock(t1),
                      "gain_min": (t5 - t1) / MIN_NS if t5 is not None and t1 is not None else None,
                      "visible_5m": an._clock(v5), "visible_1m": an._clock(v1), "visible_source": [s5, s1],
                      "visible_gain_min": (v5 - v1) / MIN_NS if v5 is not None and v1 is not None else None,
                      "latency_penalty_1m_vs_5m_min": ((v1 - t1) - (v5 - t5)) / MIN_NS
                      if v5 is not None and v1 is not None else None,
                      "only_1m": t1 is not None and t5 is None, "only_5m": t5 is not None and t1 is None}
        per.append(row)
    summ = {}
    for k in SIGNALS:
        g = [r[k]["gain_min"] for r in per if r[k]["gain_min"] is not None]
        vg = [r[k]["visible_gain_min"] for r in per if r[k]["visible_gain_min"] is not None]
        pen = [r[k]["latency_penalty_1m_vs_5m_min"] for r in per if r[k]["latency_penalty_1m_vs_5m_min"] is not None]
        both_measured = [r[k]["visible_gain_min"] for r in per
                         if r[k]["visible_gain_min"] is not None and r[k]["visible_source"] == ["MEASURED", "MEASURED"]]
        summ[k] = {"events_both": len(g), "median_information_gain_min": _med(g), "p25": _q(g, 25), "p75": _q(g, 75),
                   "median_visible_gain_min": _med(vg), "visible_p25": _q(vg, 25), "visible_p75": _q(vg, 75),
                   "median_latency_penalty_1m_vs_5m_min": _med(pen),
                   "events_both_live_measured": len(both_measured),
                   "median_visible_gain_live_measured_min": _med(both_measured),
                   "only_1m": sum(r[k]["only_1m"] for r in per), "only_5m": sum(r[k]["only_5m"] for r in per)}
    return {"label": sp.PILOT_LABEL, "definitions": {
        "price_impulse": f"close >= running session low x {1 + an.PRICE_RISE}",
        "acceleration": f"{an.WINDOW_MIN}-min return >= {an.ACCEL_MIN_RET} and > previous {an.WINDOW_MIN}-min return",
        "relative_return": f"{an.WINDOW_MIN}-min return minus XU100 {an.WINDOW_MIN}-min return >= {REL_RET_MIN}",
        "volume_acceleration": f"trailing {an.WINDOW_MIN}-min volume >= {VOL_ACCEL_MULT} x previous "
                               f"{an.WINDOW_MIN}-min volume",
        "volume_anomaly": f"trailing {an.WINDOW_MIN}-min volume >= {an.VOLUME_MULT} x prior-session median",
        "first_useful_signal": "price_impulse AND (volume_acceleration OR volume_anomaly OR relative_return) both "
                               "seen; time = later of the two",
        "bars": "archived FIRST_SEEN bars only; missing 1m minutes are NOT filled or resampled"},
        "summary": summ, "skipped": dict(skipped), "events": per}


def _q(v, q):
    return float(np.percentile(v, q)) if v else None


# ------------------------------------------------------------------ vaka çalışmaları
CASES = (("TURSG", "2026-10-23"), ("MIATK", "2026-10-23"), ("HALKB", "2026-10-23"))


def pick_cases(table: list[dict], p, events, cand_mask: np.ndarray) -> list[tuple[str, str, str]]:
    """Önceden sabit seçim: 3 adlandırılmış olay + en büyük rel_ret_z_3'lü olaysız-seans yanlış alarmı (dondurulmuş
    aday, d15) + en büyük yükselişli VERTICAL_MOVE + en büyük yükselişli NO_EARLY_SIGNAL."""
    out = [(s, d, "named") for s, d in CASES]
    cls = first_alert_classes(p, events, cand_mask, 15)
    uniq, rows = fr.first_alert_rows(cand_mask, p.sess)
    fps = [(p.rel_ret_z_3[i], s) for s, i in zip(uniq, rows) if cls[int(s)] == lv.NO_EVENT]
    if fps:
        s = max(fps)[1]
        out.append((p.sessions[s][0], str(p.sessions[s][1]), "false_positive"))
    for grp, tag in ((an.VERTICAL, "vertical_move"), (an.NO_SIGNAL, "no_early_signal")):
        cand = sorted((r for r in table if r["early_move_group"] == grp), key=lambda r: -r["runup_pct"])
        if cand:
            out.append((cand[0]["symbol"], cand[0]["session"], tag))
    return out


def case_studies(cases, p, events, table, one_min: dict, rules: dict[str, np.ndarray], ml: dict,
                 measured_mask: np.ndarray) -> list[dict]:
    info, v15, vis = p.labels[0].t_ns, p.labels[15].t_ns, p.labels["measured"].t_ns
    sid = {(s, str(d)): k for k, (s, d) in enumerate(p.sessions)}
    om = {(r["symbol"], r["session"], r["event_start"]): r for r in one_min["events"]}
    out = []
    for sym, day, tag in cases:
        s = sid.get((sym, day))
        if s is None:
            out.append({"symbol": sym, "session": day, "case": tag, "status": "NOT_IN_PILOT_PANEL"})
            continue
        idx = np.flatnonzero(p.sess == s)
        rec = {"symbol": sym, "session": day, "case": tag,
               "events": [{k: r[k] for k in ("event_class", "event_start", "event_peak", "runup_pct",
                                             "early_move_group", "first_price_evidence", "first_volume_anomaly",
                                             "first_relative_strength", "first_acceleration")}
                          for r in table if r["symbol"] == sym and r["session"] == day],
               "one_minute_vs_five_minute": {r["event_start"]: ({k: v for k, v in om[(sym, day, r["event_start"])]
                                                                 .items() if k in SIGNALS}
                                                                if (sym, day, r["event_start"]) in om
                                                                else "NO_1M_COMPARISON (1m coverage < 80%)")
                                             for r in table if r["symbol"] == sym and r["session"] == day}
               or "NO_EVENT",
               "live_first_seen_measured_rows": int(measured_mask[idx].sum()), "rule_alerts": {}}
        for name, m in rules.items():
            hit = idx[m[idx]]
            if not len(hit):
                rec["rule_alerts"][name] = None
                continue
            i = hit[0]
            cls, _ = lv.match_alerts([int(v15[i])], events[s])
            rec["rule_alerts"][name] = {"information_time": an._clock(info[i]), "visible_d15": an._clock(v15[i]),
                                        "visible_measured": an._clock(vis[i]),
                                        "visibility_source": "PROBE_FIRST_SEEN" if measured_mask[i]
                                        else "ESTIMATED_FROM_MEASURED_MEDIAN", "v2_class_d15": cls[0]}
        prob = ml["_oof"][idx]
        alert = ml["_alert"][idx]
        rec["ml_out_of_fold"] = {"max_probability": _round(prob.max()),
                                 "max_probability_time": an._clock(info[idx[int(np.argmax(prob))]]),
                                 "first_ml_alert_information_time": an._clock(info[idx[alert][0]]) if alert.any()
                                 else None}
        evs = [e for e in events[s] if e.evaluable]
        if evs:
            e = evs[0] if len(evs) == 1 else max(evs, key=lambda x: x.runup)
            w = (info[idx] >= e.start_ns) & (info[idx] <= e.peak_ns)
            rec["ml_out_of_fold"]["max_probability_in_event_window"] = _round(prob[w].max()) if w.any() else None
        out.append(rec)
    return out


# ------------------------------------------------------------------ ölçülmüş gecikme ve kapsam
def latency_table(b5: pd.DataFrame, b1: pd.DataFrame) -> dict:
    """PROBE first_seen − bar_end (dk). Prob ritmi 5 dk: değerler canlı görünürlüğün üst sınırıdır."""
    out = {}
    for iv, b in (("5m", b5), ("1m", b1)):
        pr = b[b["collection_mode"] == "PROBE"]
        lat = ((pr["first_seen_ns"] - pr["bar_end_ns"]) / MIN_NS).to_numpy(float)
        out[iv] = {"n": int(len(lat)), "symbols": int(pr["symbol"].nunique()),
                   **({"median": _round(np.median(lat), 3), "p25": _round(np.percentile(lat, 25), 3),
                       "p75": _round(np.percentile(lat, 75), 3), "p90": _round(np.percentile(lat, 90), 3),
                       "min": _round(lat.min(), 3), "max": _round(lat.max(), 3)} if len(lat) else {})}
    return out


def coverage(b5: pd.DataFrame, b1: pd.DataFrame, universe: list[str], pilot: list[str]) -> dict:
    out = {}
    for iv, b in (("5m", b5), ("1m", b1)):
        d = b[b["symbol"].isin(universe) & b["session_date"].isin(pilot)]
        per = d.groupby(["symbol", "session_date"]).size()
        out[iv] = {"asset_sessions_with_bars": int(len(per)), "asset_sessions_possible": len(universe) * len(pilot),
                   "bars": int(len(d)), "median_bars_per_asset_session": _round(per.median()) if len(per) else None,
                   "min_bars_per_asset_session": int(per.min()) if len(per) else None}
    return out


# ------------------------------------------------------------------ aday dondurma (tek sefer)
CANDIDATE_PATH = sp.HERE / "frozen_candidate.json"
CANDIDATE_VERSION = "momentum-pilot-candidate-v1"


class CandidateFreezeError(RuntimeError):
    pass


def candidate_payload(name: str, cand_c: dict, pilot_manifest: dict, created_at: str) -> dict:
    spec = GRID[name]
    rule = {"family": spec["base"], "base_rule": BASES[spec["base"]],
            "gates": {g: GATES[g] for g in spec["gates"]}}
    if spec["base"] == "C":
        rule.update({"feature": cand_c["feature"], "comparison": cand_c["comparison"], "threshold": cand_c["threshold"],
                     "confirmation": [1, 1]})
    else:
        rule.update({"round1_watch_config": {k: (list(v) if isinstance(v, tuple) else v)
                                             for k, v in fx.R1_FINAL_WATCH.items()},
                     "relative_strength_gate": REL_GATE if "relative_strength" in spec["gates"] else None,
                     "acceleration_gate": ACCEL_GATE if "acceleration" in spec["gates"] else None,
                     "confirmation": [3, 3]})
    m = pilot_manifest["manifest"]
    return {"version": CANDIDATE_VERSION, "candidate_type": "RULE_BASED", "grid_name": name, "rule": rule,
            "interval": "5m", "alert_unit": lv.FIRST_ALERT,
            "latency_semantics": "information time = end of last completed 5m bar; visible time = live first_seen of "
                                 "that bar when probed, else information time + measured median probe latency",
            "label": lv.LABEL_VERSION, "label_v2_sha256": sp.LABEL_V2_SHA256,
            "pilot_manifest_sha256": pilot_manifest["sha256"], "pilot_sessions": m["pilot_sessions"],
            "pilot_cutoff_session": m["pilot_cutoff_session"], "selection_criteria": SELECTION_RULES,
            "selection_methodology": "predeclared GRID evaluated on the 5 PILOT sessions only; leave-one-day-out "
                                     "stability; FUTURE_HOLDOUT never read",
            "created_at": created_at}


def freeze_candidate(payload: dict, path=CANDIDATE_PATH) -> dict:
    """Yazma bir kez: mevcut dondurulmuş aday farklıysa hata (anlam değişikliği yeni sürüm ister)."""
    import json
    from app.research.momentum_final import candidate as cd
    doc = {"candidate": payload, "sha256": cd.sha256_of(payload)}
    if path.exists():
        got = json.loads(path.read_text(encoding="utf-8"))
        if cd.sha256_of(got["candidate"]) != got["sha256"]:
            raise CandidateFreezeError("dondurulmuş aday bozulmuş")
        if got["sha256"] != doc["sha256"]:
            raise CandidateFreezeError("aday dondurulmuş; değişiklik yeni aday sürümü gerektirir")
        return got
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")
    return doc
