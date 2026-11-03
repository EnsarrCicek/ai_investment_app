"""Momentum — pilot sonrası aday yeniden tasarımı: nedensel ÖNCÜ (precursor) öznitelikler, olay-eşleşmeli kontroller,
gecikme-farkında değerlendirme, küçük model ailesi, iki aşamalı dedektör (YALNIZ araştırma; dondurma YOK).

Veri politikası:
* Tarihsel geliştirme = Round 1 referans evreni (50 varlık) × SEÇİM seansları (30.07–25.09). Barlar öznitelik
  hesabından ÖNCE son seçim gününde kesilir; tüketilmiş final (28.09–15.10) bir bar bile girerse HATA.
* PILOT = 5 pilot seansı (+ başlangıç öncesi ısınma), WINDOWS PRIMARY, holdout koruması zorunlu (2026-11-02+ okunamaz).
* Mobil gölge kullanılmaz. Etiket MOMENTUM_EVENT_LABEL_V2; birim varlık-seans başına ilk alarm.

Satır = tamamlanmış her 5m bar; bilgi zamanı = bar bitişi. Öznitelikler yalnız o ana kadarki barlardan (geriye dönük
pencereler, önceki seans tabanları `shift(1)`); kesitsel alanlar aynı zaman damgasındaki diğer varlıklardan.
Görünür zaman: pilotta canlı PROBE first_seen (yoksa ölçülmüş medyan gecikme); tarihsel veride ölçüm yok → pilotta
ölçülen 5m medyan gecikme (ESTIMATED).

Önceden sabit: öznitelik tanımları, kural skoru bileşenleri, eşik ızgarası (eğitim yüzdelikleri), seçim kuralı,
GBM/LR hiperparametreleri, iki aşama yapılandırmaları. Hiçbiri holdout ile seçilmez.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_pilot import deep as dp
from app.research.momentum_pilot import split as sp

MIN_NS = 60_000_000_000
BAR_NS = 5 * MIN_NS
BASE_SESSIONS = 10
BASE_MIN = 3
EARLY_LEAD = 0.5
EXPERIMENTAL = "EXPERIMENTAL — NOT FROZEN"

COMPRESSION = ("c_range6", "c_atr_ratio", "c_rv_ratio", "c_dist_high")
EXPANSION = ("e_exp_ratio", "e_range_pos", "e_hh_streak", "e_tr_accel")
VOLUME = ("v_rel", "v_slope6", "v_accel", "v_rel_trend", "v_above_streak", "v_pv_agree")
RELATIVE = ("r_rs", "r_rs_slope6", "r_rs_accel", "r_rs_streak")
STRUCTURE = ("s_hh_hl6", "s_dist_prev_high", "s_dist_sess_high", "s_failed_bo", "s_vwap_persist", "s_reclaim_hold")
PRICE = ("p_ret3_z", "p_sess_ret_z")
MARKET = ("m_breadth", "m_xu_ret3_z", "m_pct_accel", "m_shock")
NORMALIZED = ("n_ret3_vs_med", "n_vrel_vs_med", "n_acc_vs_med", "n_ret3_pct", "n_vrel_pct")
FEATURES = COMPRESSION + EXPANSION + VOLUME + RELATIVE + STRUCTURE + PRICE + MARKET + NORMALIZED
PRECURSOR = COMPRESSION + VOLUME + RELATIVE + MARKET + ("n_vrel_vs_med", "n_vrel_pct", "s_vwap_persist",
                                                          "s_hh_hl6", "s_dist_sess_high")
# Kural skoru (önceden sabit, işaretli): z-skorların ortalaması
RULE_SCORE = {"v_rel_trend": 1, "v_pv_agree": 1, "r_rs_slope6": 1, "n_ret3_vs_med": 1, "s_vwap_persist": 1,
              "s_hh_hl6": 1, "s_dist_sess_high": 1, "m_shock": -1}
QUANTILES = (90.0, 95.0, 97.0, 98.0, 99.0, 99.5, 99.8)
FPR_CAP = 0.25
TWO_STAGE = {"arm_quantiles": (80.0, 90.0, 95.0), "arm_minutes": 60,
             "confirm": "p_ret3_z >= 1.5 OR e_exp_ratio >= 1.5 OR s_dist_sess_high >= 0"}
GBM = {"rounds": 60, "lr": 0.1, "depth": 2, "bins": 16, "l2": 1.0, "min_hess": 5.0}
OFFSETS = (-30, -20, -15, -10, -5, 0)
CONTROLS_PER_EVENT = 5


class DataPolicyError(RuntimeError):
    pass


# ------------------------------------------------------------------ yardımcılar
def _streak(cond: pd.Series, day: pd.Series) -> pd.Series:
    c = cond.fillna(False).astype(int)
    grp = (c == 0).astype(int).groupby(day).cumsum()
    return c.groupby([day, grp]).cumsum()


def _slope(y: pd.Series, n: int) -> pd.Series:
    x = np.arange(n) - (n - 1) / 2
    w = x / (x ** 2).sum()
    arr = y.to_numpy(float)
    out = np.full(len(arr), np.nan)
    if len(arr) >= n:
        out[n - 1:] = np.convolve(arr, w[::-1], mode="valid")
    return pd.Series(out, index=y.index)


def _prior_session_stat(values: pd.Series, day: pd.Series, how: str) -> pd.Series:
    per_day = values.groupby(day).agg(how)
    base = per_day.shift(1).rolling(BASE_SESSIONS, min_periods=BASE_MIN).median()
    return day.map(base)


# ------------------------------------------------------------------ öznitelikler (varlık başına, nedensel)
def asset_features(bars: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    """`bars`/`bench`: İstanbul saatli bar BAŞLANGIÇ indeksi, Open/High/Low/Close/Volume. Satır = bar; değerler o
    barın BİTİŞİNDE bilinir."""
    df = bars.dropna(subset=["Open", "High", "Low", "Close"]).sort_index().copy()
    day = pd.Series(df.index.date, index=df.index)
    o, h, l, c = (df[k].astype(float) for k in ("Open", "High", "Low", "Close"))
    v = df["Volume"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    first = day != day.shift(1)
    lr = np.log(c / pc).where(~first)  # seans içi getiri (açılış boşluğu tabana girmez)
    atr_base = _prior_session_stat(tr, day, "median")
    rv_base = _prior_session_stat(lr, day, "std")
    slot = pd.Series(df.index.strftime("%H:%M"), index=df.index)
    slot_base = v.groupby(slot).transform(lambda s: s.shift(1).rolling(BASE_SESSIONS, min_periods=BASE_MIN).median())
    out = pd.DataFrame(index=df.index)
    out["c_range6"] = (h - l).rolling(6).mean() / atr_base
    out["c_atr_ratio"] = tr.rolling(6).mean() / tr.rolling(24).mean()
    out["c_rv_ratio"] = lr.rolling(12, min_periods=6).std() / rv_base
    out["c_dist_high"] = c / h.rolling(48, min_periods=12).max() - 1
    out["e_exp_ratio"] = tr.rolling(2).mean() / tr.shift(2).rolling(12).mean()
    out["e_range_pos"] = (tr / atr_base) * np.sign(c - o)
    out["e_hh_streak"] = _streak(h > h.shift(1), day).clip(upper=12)
    out["e_tr_accel"] = (tr.rolling(3).mean() - tr.shift(3).rolling(3).mean()) / atr_base
    vrel = v / slot_base
    out["v_rel"] = vrel
    out["v_slope6"] = _slope(np.log1p(vrel), 6)
    out["v_accel"] = v.rolling(3).sum() / v.shift(3).rolling(3).sum()
    out["v_rel_trend"] = vrel.rolling(6).mean() - vrel.shift(6).rolling(6).mean()
    out["v_above_streak"] = _streak(vrel > 1, day)
    out["v_pv_agree"] = (np.sign(lr) * vrel.clip(upper=5)).rolling(6, min_periods=3).mean()
    b = bench.dropna(subset=["Close"]).sort_index()
    bc = b["Close"].astype(float).reindex(df.index)
    b_open = pd.Series(b["Open"].astype(float).groupby(b.index.date).transform("first").to_numpy(), index=b.index)
    b_open = b_open.reindex(df.index)
    s_open = o.groupby(day).transform("first")
    rs = np.log(c / s_open) - np.log(bc / b_open)
    out["r_rs"] = rs
    out["r_rs_slope6"] = _slope(rs, 6)
    out["r_rs_accel"] = _slope(rs, 3) - _slope(rs, 3).shift(3)
    rel_bar = lr - np.log(bc / bc.shift(1)).where(~first)
    out["r_rs_streak"] = _streak(rel_bar > 0, day)
    hh = (h > h.shift(1)) & (l > l.shift(1)) & ~first
    out["s_hh_hl6"] = hh.astype(float).rolling(6).sum()
    prev_high = day.map(h.groupby(day).max().shift(1))
    out["s_dist_prev_high"] = c / prev_high - 1
    sess_high_before = h.groupby(day).transform(lambda s: s.cummax().shift(1))
    out["s_dist_sess_high"] = c / sess_high_before - 1
    fb = (h > prev_high) & (c < prev_high)
    out["s_failed_bo"] = fb.astype(int).groupby(day).cumsum()
    tp = (h + l + c) / 3
    vv = v.fillna(0.0)
    vwap = (tp * vv).groupby(day).cumsum() / vv.groupby(day).cumsum().replace(0, np.nan)
    above = c > vwap
    out["s_vwap_persist"] = above.astype(float).groupby(day).transform(lambda s: s.rolling(12, min_periods=3).mean())
    was_below = (~above).astype(int).groupby(day).cummax().astype(bool)
    out["s_reclaim_hold"] = _streak(above, day).where(was_below & above, 0.0)
    out["p_ret3_z"] = np.log(c / c.shift(3)) / (rv_base * np.sqrt(3))
    out["p_sess_ret_z"] = np.log(c / s_open) / (rv_base * np.sqrt(day.groupby(day).cumcount() + 1))
    b_lr = np.log(bc / bc.shift(1)).where(~first)
    b_rv = _prior_session_stat(b_lr, day, "std")
    out["_xu_ret3_z"] = np.log(bc / bc.shift(3)) / (b_rv * np.sqrt(3))
    out["_sess_ret"] = np.log(c / s_open)
    out["_acc"] = out["p_ret3_z"] - out["p_ret3_z"].shift(3)
    out["_lvrel"] = np.log(vrel)
    # kesitsel sıralama (ranking.py) için ek ham alanlar; FEATURES dışında (redesign modellerini değiştirmez)
    out["_ret12_z"] = np.log(c / c.shift(12)) / (rv_base * np.sqrt(12))
    out["_rel3"] = np.log(c / c.shift(3)) - np.log(bc / bc.shift(3))
    out["_cte"] = out["e_exp_ratio"] / out["c_range6"].shift(2)
    out["day"] = day
    out["bar_start_ns"] = df.index.as_unit("ns").asi8
    for k in ("Open", "High", "Low", "Close"):
        out[k] = df[k].astype(float)
    return out.replace([np.inf, -np.inf], np.nan)


def add_cross_section(panel: pd.DataFrame) -> pd.DataFrame:
    """Aynı bilgi zamanındaki evrene göre pazar rejimi ve normalize edilmiş öznitelikler (satır kendisi dahil, evren
    medyanı; yüzdelikler sıralamadan)."""
    g = panel.groupby("bar_start_ns")
    out = panel.copy()
    out["m_breadth"] = g["_sess_ret"].transform(lambda s: (s > 0).mean())
    out["m_pct_accel"] = g["p_ret3_z"].transform(lambda s: (s > 1).mean())
    out["m_xu_ret3_z"] = out["_xu_ret3_z"]
    med_ret = g["p_ret3_z"].transform("median")
    out["m_shock"] = out["_xu_ret3_z"].abs() + med_ret.abs()
    out["n_ret3_vs_med"] = out["p_ret3_z"] - med_ret
    out["n_vrel_vs_med"] = out["_lvrel"] - g["_lvrel"].transform("median")
    out["n_acc_vs_med"] = out["_acc"] - g["_acc"].transform("median")
    out["n_ret3_pct"] = g["p_ret3_z"].rank(pct=True)
    out["n_vrel_pct"] = g["_lvrel"].rank(pct=True)
    return out


# ------------------------------------------------------------------ değerlendirme ızgarası
class Grid:
    """Hedef seansların satırları (seans, zaman sıralı) + V2 olayları + bilgi/görünür zaman ve giriş fiyatları."""

    def __init__(self, panel: pd.DataFrame, days: list[date], visible_fn, source: str):
        rows = panel[panel["day"].isin(set(days))].sort_values(["symbol", "bar_start_ns"]).reset_index(drop=True)
        self.source = source
        self.rows = rows
        keys = list(zip(rows["symbol"], rows["day"]))
        self.sessions = list(dict.fromkeys(keys))
        sid = {k: i for i, k in enumerate(self.sessions)}
        self.sess = np.array([sid[k] for k in keys])
        first = {}
        for i, s in enumerate(self.sess):
            first.setdefault(s, i)
        self.seg_start = np.array([first[s] for s in self.sess])
        self.day = rows["day"].to_numpy()
        self.info = rows["bar_start_ns"].to_numpy(np.int64) + BAR_NS
        self.visible, self.measured = visible_fn(rows, self.info)
        self.events = []
        self.entry_info = np.full(len(rows), np.nan)
        self.entry_vis = np.full(len(rows), np.nan)
        by = defaultdict(list)
        for i, s in enumerate(self.sess):
            by[s].append(i)
        self.rows_of = {s: np.array(v) for s, v in by.items()}
        for s in range(len(self.sessions)):
            idx = self.rows_of[s]
            st = rows["bar_start_ns"].to_numpy(np.int64)[idx]
            hi, lo, op = (rows[k].to_numpy(float)[idx] for k in ("High", "Low", "Open"))
            self.events.append(lv.session_events(st, hi, lo))
            for arr, t in ((self.entry_info, self.info), (self.entry_vis, self.visible)):
                j = np.searchsorted(st, t[idx], side="left")
                ok = j < len(st)
                arr[idx[ok]] = op[j[ok]]
        self.X = rows[list(FEATURES)].to_numpy(float)
        self.y = self._early_label()

    def _early_label(self) -> np.ndarray:
        """y=1 ⇔ bu satırda verilen alarm (görünür zamanda) bir değerlendirilebilir olayı lead ≤ 0.5 ile yakalar.
        Gelecek bilgi YALNIZ etikette."""
        y = np.zeros(len(self.rows))
        for s, evs in enumerate(self.events):
            idx = self.rows_of[s]
            for ev in evs:
                if not ev.evaluable:
                    continue
                w = idx[(self.visible[idx] >= ev.start_ns) & (self.visible[idx] <= ev.peak_ns)]
                for i in w:
                    ld = lv.lead_v2(float(self.entry_vis[i]), ev)
                    if ld is not None and ld <= EARLY_LEAD:
                        y[i] = 1.0
        return y

    def col(self, name: str) -> np.ndarray:
        return self.rows[name].to_numpy(float)

    def evaluate(self, mask: np.ndarray, days=None, when: str = "visible") -> dict:
        t, e = (self.visible, self.entry_vis) if when == "visible" else (self.info, self.entry_info)
        keep = [s for s, (_, d) in enumerate(self.sessions) if days is None or d in days]
        remap = {s: k for k, s in enumerate(keep)}
        idx = np.concatenate([self.rows_of[s] for s in keep]) if keep else np.array([], int)
        sess = np.array([remap[int(s)] for s in self.sess[idx]], dtype=int)
        first = {}
        for i, s in enumerate(sess):
            first.setdefault(s, i)
        seg = np.array([first[s] for s in sess], dtype=int)
        m = lv.evaluate(mask[idx], sess, seg, t[idx], e[idx], [self.events[s] for s in keep], lv.FIRST_ALERT)
        return {"alerts": m["alerts"], "TP": m["alert_classes"][lv.IN_EVENT], "precision": m["precision_v2"],
                "recall_eval": m["recall_evaluable_v2"], "FPR": m["FPR_v2"], "lead": m["median_lead_v2"],
                "evaluable_events": m["event_count_evaluable"], "non_event_sessions": m["non_event_sessions"]}

    def both(self, mask, days=None) -> dict:
        v, i = self.evaluate(mask, days, "visible"), self.evaluate(mask, days, "info")
        return {**v, "info_lead": i["lead"], "info_recall_eval": i["recall_eval"], "info_precision": i["precision"]}


# ------------------------------------------------------------------ veri yükleyiciler
def load_historical(symbols, bench_sym: str = "XU100") -> tuple[pd.DataFrame, list[date]]:
    """Tarihsel geliştirme paneli. Barlar ÖNCE son seçim gününde kesilir; tüketilmiş final barı → DataPolicyError."""
    from app.research.momentum_calibration import dataset as r1ds
    from app.research.momentum_feasibility import audit as au
    from app.research.momentum_round2 import dataset as ds2
    sel, final = ds2.selection_and_final()
    last = max(sel)
    if not last < min(final):
        raise DataPolicyError("seçim günleri tüketilmiş finalle çakışıyor")
    with au.candidate_selection():
        def cut(sym):
            b = r1ds.load(sym).bars
            b = b[b.index.date <= last]
            if any(d >= min(final) for d in set(b.index.date)):
                raise DataPolicyError(au.CONSUMED_FINAL_ERROR)
            return b
        bench = cut(bench_sym)
        parts = []
        for s in symbols:
            f = asset_features(cut(s), bench)
            f["symbol"] = s
            parts.append(f)
    panel = add_cross_section(pd.concat(parts, ignore_index=True))
    assert panel["day"].max() <= last
    return panel, sorted(sel)


def load_pilot(ctx_loader) -> tuple[pd.DataFrame, list[date], dict]:
    """Pilot paneli — holdout korumalı yükleyiciyle (WINDOWS PRIMARY)."""
    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_pilot import analysis as an
    from app.research.momentum_pilot import experiment as ex
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    if not guard.complete:
        raise DataPolicyError("pilot tamamlanmadı")
    pilot = list(manifest["manifest"]["pilot_sessions"])
    c = mm.load()["config"]
    a = ex._ReadOnlyArchive()
    try:
        _, warm = ex.session_classes(a)
        b5 = sp.load_primary_bars(a.db, guard, warm + pilot, "5m", list(c["universe"]) + [c["benchmark"]])
    finally:
        a.close()
    assert set(b5["source"]) == {sp.PRIMARY_SOURCE}
    data = {s: an.to_asset_data(s, g).bars for s, g in b5.groupby("symbol")}
    bench = data.pop(c["benchmark"])
    parts = []
    for s, bars in sorted(data.items()):
        f = asset_features(bars, bench)
        f["symbol"] = s
        parts.append(f)
    panel = add_cross_section(pd.concat(parts, ignore_index=True))
    guard.check_sessions(sorted({str(d) for d in panel["day"]}))
    audit = {"sessions_read": sorted({str(d) for d in b5["session_date"]}), "cutoff": guard.cutoff,
             "probe_bars": b5[b5["collection_mode"] == "PROBE"]}
    return panel, [date.fromisoformat(d) for d in pilot], audit


def pilot_visibility(probe: pd.DataFrame):
    seen, med = dp.probe_seen(probe.assign(collection_mode="PROBE"))

    def fn(rows: pd.DataFrame, info: np.ndarray):
        vis = info + med
        meas = np.zeros(len(info), dtype=bool)
        for i, (sym, b) in enumerate(zip(rows["symbol"], rows["bar_start_ns"])):
            got = seen.get((sym, int(b)))
            if got is not None:
                vis[i], meas[i] = max(got, int(info[i])), True
        return vis, meas
    return fn, med


def estimated_visibility(median_ns: int):
    def fn(rows, info):
        return info + median_ns, np.zeros(len(info), dtype=bool)
    return fn


# ------------------------------------------------------------------ modeller
class GBMClassifier:
    """Küçük gradyan artırma (lojistik kayıp, derinlik 2, nicelik kutuları; NaN = ayrı kutu 0). Deterministik."""

    def __init__(self, rounds=GBM["rounds"], lr=GBM["lr"], bins=GBM["bins"], l2=GBM["l2"], min_hess=GBM["min_hess"]):
        self.rounds, self.lr, self.nb, self.l2, self.min_hess = rounds, lr, bins, l2, min_hess

    def _bin(self, X):
        B = np.zeros(X.shape, dtype=np.int16)
        for j in range(X.shape[1]):
            x = X[:, j]
            fin = np.isfinite(x)
            B[fin, j] = 1 + np.searchsorted(self.edges[j], x[fin], side="right")
        return B

    def fit(self, X, y):
        self.edges = []
        for j in range(X.shape[1]):
            x = X[np.isfinite(X[:, j]), j]
            qs = np.unique(np.quantile(x, np.linspace(0, 1, self.nb + 1)[1:-1])) if len(x) else np.array([])
            self.edges.append(qs)
        B = self._bin(X)
        n = len(y)
        pos = y.sum()
        w = np.where(y == 1, n / (2 * max(pos, 1)), n / (2 * max(n - pos, 1)))
        self.base = float(np.log(max(pos, 1) / max(n - pos, 1)))
        f = np.full(n, self.base)
        self.trees = []
        for _ in range(self.rounds):
            p = 1 / (1 + np.exp(-f))
            g, h = w * (p - y), w * p * (1 - p)
            tree = self._grow(B, g, h, np.arange(n), 2)
            self.trees.append(tree)
            f += self.lr * self._apply(tree, B)
        return self

    def _best(self, B, g, h, idx):
        G, H = g[idx].sum(), h[idx].sum()
        best = (0.0, None, None)
        for j in range(B.shape[1]):
            nb = len(self.edges[j]) + 2
            gs = np.bincount(B[idx, j], weights=g[idx], minlength=nb)
            hs = np.bincount(B[idx, j], weights=h[idx], minlength=nb)
            gl, hl = np.cumsum(gs)[:-1], np.cumsum(hs)[:-1]
            gr, hr = G - gl, H - hl
            ok = (hl >= self.min_hess) & (hr >= self.min_hess)
            gain = np.where(ok, gl ** 2 / (hl + self.l2) + gr ** 2 / (hr + self.l2) - G ** 2 / (H + self.l2), -np.inf)
            k = int(np.argmax(gain))
            if gain[k] > best[0]:
                best = (float(gain[k]), j, k)
        return best

    def _grow(self, B, g, h, idx, depth):
        leaf = {"leaf": float(-g[idx].sum() / (h[idx].sum() + self.l2))}
        if depth == 0:
            return leaf
        gain, j, k = self._best(B, g, h, idx)
        if j is None:
            return leaf
        left = idx[B[idx, j] <= k]
        right = idx[B[idx, j] > k]
        return {"f": j, "k": k, "gain": gain, "l": self._grow(B, g, h, left, depth - 1),
                "r": self._grow(B, g, h, right, depth - 1)}

    def _apply(self, tree, B):
        if "leaf" in tree:
            return np.full(len(B), tree["leaf"])
        out = np.empty(len(B))
        m = B[:, tree["f"]] <= tree["k"]
        out[m] = self._apply(tree["l"], B[m])
        out[~m] = self._apply(tree["r"], B[~m])
        return out

    def predict(self, X):
        B = self._bin(X)
        f = np.full(len(X), self.base)
        for t in self.trees:
            f += self.lr * self._apply(t, B)
        return 1 / (1 + np.exp(-f))

    def importance(self) -> np.ndarray:
        imp = np.zeros(len(self.edges))

        def walk(t):
            if "leaf" not in t:
                imp[t["f"]] += t["gain"]
                walk(t["l"])
                walk(t["r"])
        for t in self.trees:
            walk(t)
        return imp / imp.sum() if imp.sum() else imp


def feature_index(names) -> list[int]:
    return [FEATURES.index(n) for n in names]


def fit_scorer(kind: str, X: np.ndarray, y: np.ndarray):
    """Eğitim verisinde skorlayıcı; dönen fonksiyon X → skor."""
    if kind == "rule_score":
        cols = feature_index(RULE_SCORE)
        sign = np.array(list(RULE_SCORE.values()), float)
        st = dp.Standardizer().fit(X[:, cols])
        return (lambda Z: (st.transform(Z[:, cols]) * sign).mean(axis=1)), {"weights": dict(RULE_SCORE)}
    if kind in ("logistic", "logistic_precursor"):
        cols = list(range(len(FEATURES))) if kind == "logistic" else feature_index(PRECURSOR)
        st = dp.Standardizer().fit(X[:, cols])
        beta = dp.fit_logistic(st.transform(X[:, cols]), y)
        names = [FEATURES[c] for c in cols]
        return (lambda Z: dp.predict(beta, st.transform(Z[:, cols]))), {"coef": dict(zip(names, beta[1:].round(4)))}
    if kind == "gbm":
        m = GBMClassifier().fit(X, y)
        return m.predict, {"importance": dict(zip(FEATURES, m.importance().round(4)))}
    raise ValueError(kind)


def choose_threshold(grid: Grid, score: np.ndarray, train_days) -> tuple[float, dict]:
    """Önceden sabit: eğitim satırlarının QUANTILES yüzdelikleri; eğitim FPR ≤ 0.25 olanlar içinde (recall − FPR) en
    yüksek; hiçbiri değilse en yüksek yüzdelik."""
    tr = np.isin(grid.day, list(train_days))
    best = None
    for q in QUANTILES:
        thr = float(np.nanpercentile(score[tr], q))
        m = grid.evaluate(np.nan_to_num(score, nan=-np.inf) >= thr, set(train_days))
        if m["FPR"] is not None and m["FPR"] <= FPR_CAP:
            j = (m["recall_eval"] or 0) - m["FPR"]
            if best is None or j > best[0]:
                best = (j, q, thr, m)
    if best is None:
        q = QUANTILES[-1]
        thr = float(np.nanpercentile(score[tr], q))
        return thr, {"quantile": q, "train": grid.evaluate(score >= thr, set(train_days)), "fpr_cap_met": False}
    return best[2], {"quantile": best[1], "train": best[3], "fpr_cap_met": True}


def two_stage_mask(grid: Grid, arm_score: np.ndarray, arm_thr: float) -> np.ndarray:
    """Aşama 1 (öncü skor ≥ eşik) son 60 dk içinde en az bir kez ∧ Aşama 2 onayı (fiyat genişlemesi/kırılım)."""
    armed = np.nan_to_num(arm_score, nan=-np.inf) >= arm_thr
    conf = ((np.nan_to_num(grid.col("p_ret3_z"), nan=-9) >= 1.5)
            | (np.nan_to_num(grid.col("e_exp_ratio"), nan=0) >= 1.5)
            | (np.nan_to_num(grid.col("s_dist_sess_high"), nan=-1) >= 0))
    out = np.zeros(len(armed), dtype=bool)
    k = TWO_STAGE["arm_minutes"] // 5
    for s, idx in grid.rows_of.items():
        a = armed[idx].astype(int)
        cs = np.concatenate([[0], np.cumsum(a)])
        pos = np.arange(len(idx))
        recent = (cs[pos + 1] - cs[np.maximum(pos - k + 1, 0)]) > 0
        out[idx] = recent & conf[idx]
    return out


# ------------------------------------------------------------------ öncü (pre-event) çalışması
def pre_event_study(grid: Grid, features=FEATURES) -> dict:
    """Her değerlendirilebilir olay için olay başlangıcına (T0) göre −30…0 dk bilgi zamanlarında öznitelik değerleri.
    Eşleşmiş kontroller: AYNI seans günü ve AYNI zaman damgası (saat + piyasa rejimi ortak), olaysız varlık-seansları,
    en yakın yakın-dönem oynaklık (son 24 barın ortalama aralığı / fiyat; nedensel)."""
    rows = grid.rows
    vol_key = (rows["High"] - rows["Low"]).rolling(24, min_periods=6).mean() / rows["Close"]
    vol_key = vol_key.to_numpy(float)
    by_ts_day = defaultdict(list)
    non_event = {s for s, evs in enumerate(grid.events) if not evs}
    for i, (s, b) in enumerate(zip(grid.sess, rows["bar_start_ns"].to_numpy(np.int64))):
        if s in non_event:
            by_ts_day[b].append(i)
    pos = {(int(s), int(b)): i for i, (s, b) in enumerate(zip(grid.sess, rows["bar_start_ns"].to_numpy(np.int64)))}
    X = grid.X
    fidx = [FEATURES.index(f) for f in features]
    res = {off: {"ev": [], "ctl": [], "ev_day": [], "ctl_day": []} for off in OFFSETS}
    n_events = 0
    for s, evs in enumerate(grid.events):
        for ev in evs:
            if not ev.evaluable:
                continue
            n_events += 1
            for off in OFFSETS:
                info_t = ev.start_ns + off * MIN_NS
                i = pos.get((s, info_t - BAR_NS))
                if i is None:
                    continue
                cands = by_ts_day.get(info_t - BAR_NS, [])
                if not cands:
                    continue
                d = np.abs(np.log(np.maximum(vol_key[cands], 1e-9)) - np.log(max(vol_key[i], 1e-9)))
                d = np.nan_to_num(d, nan=np.inf)
                ctl = [cands[k] for k in np.argsort(d, kind="stable")[:CONTROLS_PER_EVENT]]
                res[off]["ev"].append(X[i, fidx])
                res[off]["ev_day"].append(grid.day[i])
                for c in ctl:
                    res[off]["ctl"].append(X[c, fidx])
                    res[off]["ctl_day"].append(grid.day[c])
    out = {"events": n_events, "controls_per_event": CONTROLS_PER_EVENT, "offsets": {}}
    for off in OFFSETS:
        r = res[off]
        if not r["ev"]:
            continue
        E, C = np.array(r["ev"]), np.array(r["ctl"])
        ed, cd_ = np.array(r["ev_day"]), np.array(r["ctl_day"])
        days = sorted(set(ed))
        feats = {}
        for j, f in enumerate(features):
            per_day = [dp.auc(E[ed == d, j], C[cd_ == d, j]) for d in days]
            per_day = [a for a in per_day if a is not None]
            feats[f] = {"event_median": dp._med(E[:, j]), "control_median": dp._med(C[:, j]),
                        "effect_size": dp._round(dp.cohens_d(E[:, j], C[:, j])),
                        "auc": dp._round(dp.auc(E[:, j], C[:, j])),
                        "auc_by_day_median": dp._round(np.median(per_day)) if per_day else None,
                        "auc_by_day_p25": dp._round(np.percentile(per_day, 25)) if per_day else None,
                        "days_auc_gt_0_5": int(sum(a > 0.5 for a in per_day)), "days": len(per_day)}
        out["offsets"][str(off)] = {"n_events": len(E), "n_controls": len(C), "features": feats}
    return out


# ------------------------------------------------------------------ gecikme darboğazı (mevcut kanıtlar, pilot)
BOTTLENECK = ("A_EARLY_AT_INFORMATION_TIME", "B_EARLY_BUT_LOST_TO_LATENCY", "C_FEATURES_INFORMATIVE_TOO_LATE",
              "D_INTRINSICALLY_ABRUPT_VERTICAL")


def bottleneck(p, events) -> dict:
    """Pilot panelinin mevcut kanıtlarıyla (fx evidence tanımları) olay başına zaman çizgisi ve A/B/C/D sınıfı.
    Erken = alarmın girişi lead ≤ 0.5 (bilgi zamanında ve ölçülmüş görünür zamanda ayrı)."""
    from app.research.momentum_pilot import analysis as an
    info, vis = p.labels[0].t_ns, p.labels["measured"].t_ns
    e0, ev_ = p.labels[0].entry, p.labels["measured"].entry
    masks = an.evidence_masks(p)
    masks["first_breakout"] = p.ok & (p.breakout >= 0.5)
    rows_of = an.seg_rows(p)
    per, counts = [], dict.fromkeys(BOTTLENECK, 0)
    deltas = defaultdict(list)
    for s, evs in enumerate(events):
        for ev in evs:
            if not ev.evaluable:
                continue
            idx = rows_of[s]
            win = (info[idx] >= ev.start_ns) & (info[idx] <= ev.peak_ns)
            t = {}
            for name, m in masks.items():
                hit = idx[m[idx] & win]
                t[name] = int(hit[0]) if len(hit) else None
            any_rows = [r for r in t.values() if r is not None]
            first = min(any_rows, key=lambda r: info[r]) if any_rows else None
            rise = (ev.peak_ns - ev.start_ns) / MIN_NS
            lead_i = lv.lead_v2(float(e0[first]), ev) if first is not None else None
            lead_v = lv.lead_v2(float(ev_[first]), ev) if first is not None and vis[first] <= ev.peak_ns else None
            if rise <= 15:
                cls = BOTTLENECK[3]
            elif lead_i is None or lead_i > EARLY_LEAD:
                cls = BOTTLENECK[2]
            elif lead_v is None or lead_v > EARLY_LEAD:
                cls = BOTTLENECK[1]
            else:
                cls = BOTTLENECK[0]
            counts[cls] += 1
            rec = {"symbol": p.sessions[s][0], "session": str(p.sessions[s][1]), "class": cls, "rise_min": rise,
                   "lead_info_first_evidence": dp._round(lead_i), "lead_visible_first_evidence": dp._round(lead_v)}
            for name, r in t.items():
                rec[f"{name}_minus_T0_min"] = (info[r] - ev.start_ns) / MIN_NS if r is not None else None
                if r is not None:
                    deltas[name].append((info[r] - ev.start_ns) / MIN_NS)
            rec["Tvisible_minus_T0_min"] = (vis[first] - ev.start_ns) / MIN_NS if first is not None else None
            if first is not None:
                deltas["Tvisible_first_evidence"].append(rec["Tvisible_minus_T0_min"])
            rec["Tpeak_minus_T0_min"] = rise
            deltas["Tpeak"].append(rise)
            per.append(rec)
    summ = {k: {"n": len(v), "median_min": dp._med(v), "p25": dp._round(np.percentile(v, 25)) if v else None,
                "p75": dp._round(np.percentile(v, 75)) if v else None} for k, v in deltas.items()}
    return {"evaluable_events": len(per), "counts": counts, "delta_from_T0": summ, "events": per,
            "definitions": {"evidence": "existing Round 1 / extended evidence masks (price_impulse>=0.5, "
                                        "volume_anomaly>=0.5, rel_ret_z_3>=1, accel>=1 & accel_pos_3>=2, "
                                        "breakout>=0.5) within [T0, Tpeak] by information time",
                            "early": f"lead_v2 of entry at that time <= {EARLY_LEAD}",
                            "D": "rise (Tpeak - T0) <= 15 min", "visible": "measured probe first_seen, else "
                                                                           "information time + measured median"}}


# ------------------------------------------------------------------ çalıştırma: CV, pilot, kararlılık
def _stab(per_day: list[dict], keys=("precision", "recall_eval", "FPR", "lead", "info_lead")) -> dict:
    out = {}
    for k in keys:
        v = [m[k] for m in per_day if m.get(k) is not None]
        worst = (max(v) if k in ("FPR", "lead", "info_lead") else min(v)) if v else None
        out[k] = {"median": dp._round(np.median(v)) if v else None, "p25": dp._round(np.percentile(v, 25)) if v else None,
                  "p75": dp._round(np.percentile(v, 75)) if v else None, "worst": dp._round(worst), "n_days": len(v)}
    return out


def blocks(days: list, n: int = 5) -> list[list]:
    days = sorted(days)
    edges = [round(len(days) * j / n) for j in range(n + 1)]
    return [days[edges[j]:edges[j + 1]] for j in range(n)]


ARCHITECTURES = ("rule_score", "logistic", "gbm", "two_stage")


def scores_for(kind, fit_grid: Grid, train_mask: np.ndarray, apply_grid: Grid) -> tuple[np.ndarray, dict]:
    fn, info = fit_scorer("logistic_precursor" if kind == "two_stage" else kind,
                          fit_grid.X[train_mask], fit_grid.y[train_mask])
    return fn(apply_grid.X), info


def run_architecture(kind: str, hist: Grid, pilot: Grid, hist_days: list) -> dict:
    """Tarihsel: 5 ardışık gün bloğu (gruplu, karıştırma yok). Pilot: tüm tarihsel geliştirme verisiyle eğitilmiş
    model + tarihsel eğitim eşiği, 5 pilot gününe ayrı ayrı uygulanır."""
    hist_mask = np.zeros(len(hist.rows), dtype=bool)
    hist_per_day, picks = [], []
    for blk in blocks(hist_days):
        train_days = [d for d in hist_days if d not in blk]
        tr = np.isin(hist.day, train_days)
        sc, _ = scores_for(kind, hist, tr, hist)
        if kind == "two_stage":
            mask, pick = _two_stage_pick(hist, sc, train_days)
        else:
            thr, pick = choose_threshold(hist, sc, train_days)
            mask = np.nan_to_num(sc, nan=-np.inf) >= thr
        picks.append({"validation_block": [str(blk[0]), str(blk[-1])], **{k: v for k, v in pick.items()
                                                                         if k != "train"}})
        te = np.isin(hist.day, blk)
        hist_mask[te] = mask[te]
        hist_per_day += [hist.both(mask, {d}) for d in blk]
    full_tr = np.ones(len(hist.rows), dtype=bool)
    sc_h, info = scores_for(kind, hist, full_tr, hist)
    sc_p, _ = scores_for(kind, hist, full_tr, pilot)
    if kind == "two_stage":
        _, pick = _two_stage_pick(hist, sc_h, hist_days)
        thr = pick["arm_threshold"]
        p_mask = two_stage_mask(pilot, sc_p, thr)
    else:
        thr, pick = choose_threshold(hist, sc_h, hist_days)
        p_mask = np.nan_to_num(sc_p, nan=-np.inf) >= thr
    pilot_days = sorted({d for _, d in pilot.sessions})
    pilot_per_day = [pilot.both(p_mask, {d}) for d in pilot_days]
    return {"architecture": kind, "historical_cv_pooled": hist.both(hist_mask),
            "historical_day_stability": _stab(hist_per_day), "historical_fold_picks": picks,
            "pilot_pooled": pilot.both(p_mask), "pilot_by_day": {str(d): m for d, m in zip(pilot_days, pilot_per_day)},
            "pilot_day_stability": _stab(pilot_per_day),
            "pilot_threshold_from_historical": {k: v for k, v in pick.items() if k != "train"},
            "model_info": _jsonable(info), "_hist_mask": hist_mask, "_pilot_mask": p_mask, "_pilot_score": sc_p}


def _two_stage_pick(grid: Grid, arm_score: np.ndarray, train_days) -> tuple[np.ndarray, dict]:
    tr = np.isin(grid.day, list(train_days))
    best = None
    for q in TWO_STAGE["arm_quantiles"]:
        thr = float(np.nanpercentile(arm_score[tr], q))
        mask = two_stage_mask(grid, arm_score, thr)
        m = grid.evaluate(mask, set(train_days))
        ok = m["FPR"] is not None and m["FPR"] <= FPR_CAP
        j = (m["recall_eval"] or 0) - (m["FPR"] or 0)
        key = (ok, j)
        if best is None or key > best[0]:
            best = (key, q, thr, mask)
    return best[3], {"arm_quantile": best[1], "arm_threshold": best[2], "fpr_cap_met": best[0][0]}


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (np.floating, np.integer)):
        return float(o)
    return o


def shock_normalization(pilot: Grid, hist: Grid) -> dict:
    """23 Ekim geniş piyasa YP'leri: ham vs kesitsel normalize kural (önceden sabit iki kural, aynı eşik politikası).
    Ham: p_ret3_z + log göreli hacim; normalize: n_ret3_vs_med + n_vrel_vs_med."""
    out = {}
    for name, cols in (("raw", ("p_ret3_z", "_lvrel")), ("normalized", ("n_ret3_vs_med", "n_vrel_vs_med"))):
        def score(g):
            return sum(np.nan_to_num(g.col(c), nan=-9) for c in cols)
        hist_days = sorted({d for _, d in hist.sessions})
        thr, pick = choose_threshold(hist, score(hist), hist_days)
        mask = score(pilot) >= thr
        out[name] = {"rule": " + ".join(cols), "threshold_quantile_from_historical": pick["quantile"],
                     "pilot_pooled": pilot.both(mask),
                     "pilot_by_day": {str(d): pilot.both(mask, {d}) for d in sorted({d for _, d in pilot.sessions})}}
    return out


def holdout_audit(stage: str) -> dict:
    g = sp.HoldoutGuard(sp.load_manifest())
    res = {}
    for d in ("2026-11-02", "2026-11-03", "2026-12-31"):
        try:
            g.check_session(d)
            res[d] = "ALLOWED"
        except sp.HoldoutAccessError:
            res[d] = "FORBIDDEN"
    if any(v != "FORBIDDEN" for v in res.values()):
        raise sp.HoldoutAccessError(f"holdout koruması çalışmıyor ({stage})")
    return {"stage": stage, "cutoff": g.cutoff, "checks": res}
