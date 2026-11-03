"""Momentum — kesitsel lider sıralaması (cross-sectional leader ranking). YALNIZ araştırma; dondurma YOK.

Soru: "Bu hisse X eşiğini aştı mı?" yerine "ŞU AN evrenin en güçlüleri hangileri?" Gerçek V2 olayları hareketten
ÖNCE üst sıralarda yoğunlaşıyor mu?

* Satırlar/öznitelikler `redesign` paneliyle aynı (nedensel; tarihsel veri 25.09'da kesilir, tüketilmiş final yok;
  pilot holdout korumalı). Sıralama YALNIZ aynı zaman damgasındaki (aynı bar başlangıcı) varlıklar arasında.
* Kesin Top-K: skor azalan, eşitlikte sembol artan (deterministik). Eşitlikte K genişlemez; skoru NaN olan varlık o
  anın evrenine girmez.
* Önceden sabit ızgara: 3 bileşik skor × K {1,3,5} (+ Top-3/Top-5 ∧ skor ≥ 0.75 tabanı) × kalıcılık {1,2,3}.
* Görünür zaman: pilotta canlı PROBE first_seen (yoksa ölçülmüş medyan), tarihselde ESTIMATED (pilot 5m medyanı).
  Herkes aynı gecikmeyi yaşadığında görünür-zaman sıralaması bilgi-zamanı sıralamasının kaydırılmışıdır; birincil
  karar ölçüsü GÖRÜNÜR zamandır.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from app.research.momentum_pilot import deep as dp
from app.research.momentum_pilot import redesign as rd

MIN_NS = rd.MIN_NS
BAR_NS = rd.BAR_NS
EXPERIMENTAL = rd.EXPERIMENTAL

# Sıralanan öznitelikler (istenen ad → panel sütunu). Hepsi büyük = güçlü yönünde yüzdeliklenir.
RANK_FEATURES = {
    "price_z": "p_sess_ret_z", "ret_z_3": "p_ret3_z", "ret_z_12": "_ret12_z", "acceleration": "_acc",
    "relative_return_xu100": "_rel3", "relative_return_universe": "n_ret3_vs_med", "volume_anomaly": "v_rel",
    "relative_volume": "n_vrel_vs_med", "volume_slope": "v_slope6", "volume_acceleration": "v_accel",
    "breakout_distance": "s_dist_prev_high", "vwap_persistence": "s_vwap_persist", "range_expansion": "e_exp_ratio",
    "atr_expansion": "c_atr_ratio", "compression_to_expansion": "_cte", "distance_recent_high": "c_dist_high",
    "hh_hl_structure": "s_hh_hl6", "relative_strength_buildup": "r_rs_slope6", "volume_buildup": "v_rel_trend",
}
# Önceden sabit bileşik skorlar (yüzdeliklerin basit ortalaması)
SCORES = {
    "MOMENTUM_RANK": ("relative_return_xu100", "acceleration", "volume_acceleration", "ret_z_3"),
    "EARLY_LEADER_RANK": ("relative_strength_buildup", "volume_buildup", "compression_to_expansion",
                          "breakout_distance"),
}
CONFIRMED = "CONFIRMED_LEADER_RANK"  # (EARLY + pct(ret_z_3) + ort(pct breakout, pct vwap)) / 3
SCORE_NAMES = (*SCORES, CONFIRMED)
KS = (1, 3, 5)
FLOOR = 0.75
FLOOR_KS = (3, 5)
PERSISTENCE = (1, 2, 3)
ENRICH_K = (1, 3, 5, 10)
ENRICH_PCT = (0.05, 0.10)
OFFSETS = rd.OFFSETS
TARGETS = dp.TARGETS


# ------------------------------------------------------------------ kesitsel sıralama
def add_percentiles(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    g = out.groupby("bar_start_ns")
    for name, col in RANK_FEATURES.items():
        out[f"pct_{name}"] = g[col].rank(pct=True, method="average")
    for name, parts in SCORES.items():
        out[name] = out[[f"pct_{p}" for p in parts]].mean(axis=1, skipna=False)
    conf = out[["pct_breakout_distance", "pct_vwap_persistence"]].mean(axis=1, skipna=False)
    out[CONFIRMED] = (out["EARLY_LEADER_RANK"] + out["pct_ret_z_3"] + conf) / 3
    return out


def rank_within_timestamp(df: pd.DataFrame, score: str, key: str = "bar_start_ns") -> pd.Series:
    """1 = en güçlü. Yalnız aynı `key` içinde; eşitlik: sembol artan. NaN skor → NaN sıra (evrende değil)."""
    ok = df[score].notna()
    d = df.loc[ok, [key, score, "symbol"]].sort_values([key, score, "symbol"], ascending=[True, False, True],
                                                       kind="mergesort")
    r = d.groupby(key).cumcount() + 1
    out = pd.Series(np.nan, index=df.index)
    out.loc[r.index] = r.to_numpy(float)
    return out


def add_ranks(panel: pd.DataFrame, scores=SCORE_NAMES) -> pd.DataFrame:
    out = panel.copy()
    out["universe_n"] = out.groupby("bar_start_ns")["symbol"].transform("count")
    for s in scores:
        out[f"rank_{s}"] = rank_within_timestamp(out, s)
        out[f"n_{s}"] = out.groupby("bar_start_ns")[s].transform("count")
    return out


def topk_mask(rank: np.ndarray, k: int) -> np.ndarray:
    return np.isfinite(rank) & (rank <= k)


def persistent(mask: np.ndarray, grid: rd.Grid, n: int) -> np.ndarray:
    """Aynı seansta son n değerlendirmenin hepsi Top-K."""
    if n <= 1:
        return mask.copy()
    out = np.zeros(len(mask), dtype=bool)
    for s, idx in grid.rows_of.items():
        m = mask[idx].astype(int)
        cs = np.concatenate([[0], np.cumsum(m)])
        pos = np.arange(len(idx))
        ok = pos >= n - 1
        out[idx[ok]] = (cs[pos[ok] + 1] - cs[pos[ok] - n + 1]) == n
    return out


POLICIES: dict[str, dict] = {}
for _s in SCORE_NAMES:
    for _k in KS:
        for _p in PERSISTENCE:
            POLICIES[f"{_s}|top{_k}|p{_p}"] = {"score": _s, "k": _k, "floor": None, "persistence": _p}
    for _k in FLOOR_KS:
        for _p in PERSISTENCE:
            POLICIES[f"{_s}|top{_k}+floor{FLOOR}|p{_p}"] = {"score": _s, "k": _k, "floor": FLOOR, "persistence": _p}


def policy_mask(grid: rd.Grid, spec: dict, score_col: str | None = None, rank_col: str | None = None) -> np.ndarray:
    rank = grid.col(rank_col or f"rank_{spec['score']}")
    m = topk_mask(rank, spec["k"])
    if spec["floor"] is not None:
        m &= np.nan_to_num(grid.col(score_col or spec["score"]), nan=-1) >= spec["floor"]
    return persistent(m, grid, spec["persistence"])


# ------------------------------------------------------------------ olay zenginleşmesi
def _row_pos(grid: rd.Grid) -> dict:
    b = grid.rows["bar_start_ns"].to_numpy(np.int64)
    return {(int(s), int(x)): i for i, (s, x) in enumerate(zip(grid.sess, b))}


def event_rank_study(grid: rd.Grid, score: str) -> dict:
    """Her değerlendirilebilir olayın T0+ofset bilgi zamanındaki sırası; eşleşmiş kontroller (aynı zaman damgası,
    olaysız seans, en yakın son-24-bar oynaklığı) ve Top-K zenginleşmesi (kapsama, taban oran, kesinlik, kaldıraç)."""
    pos = _row_pos(grid)
    rows = grid.rows
    rank = rows[f"rank_{score}"].to_numpy(float)
    n_univ = rows[f"n_{score}"].to_numpy(float)
    b = rows["bar_start_ns"].to_numpy(np.int64)
    vol_key = ((rows["High"] - rows["Low"]).rolling(24, min_periods=6).mean() / rows["Close"]).to_numpy(float)
    non_event = {s for s, evs in enumerate(grid.events) if not evs}
    by_ts = defaultdict(list)
    for i, s in enumerate(grid.sess):
        if s in non_event and np.isfinite(rank[i]):
            by_ts[int(b[i])].append(i)
    finite = np.isfinite(rank)
    total_pairs = int(finite.sum())
    out = {}
    for off in OFFSETS:
        ev_rank, ev_n, ctl_rank, pos_rows = [], [], [], set()
        n_events = 0
        for s, evs in enumerate(grid.events):
            for ev in evs:
                if not ev.evaluable:
                    continue
                n_events += 1
                i = pos.get((s, ev.start_ns + off * MIN_NS - BAR_NS))
                if i is None or not finite[i]:
                    continue
                pos_rows.add(i)
                ev_rank.append(rank[i])
                ev_n.append(n_univ[i])
                c = by_ts.get(int(b[i]), [])
                if c:
                    d = np.nan_to_num(np.abs(np.log(np.maximum(vol_key[c], 1e-12)) -
                                             np.log(max(vol_key[i], 1e-12))), nan=np.inf)
                    ctl_rank += [rank[c[k]] for k in np.argsort(d, kind="stable")[:rd.CONTROLS_PER_EVENT]]
        er, en, cr = np.array(ev_rank), np.array(ev_n), np.array(ctl_rank)
        base_pos = len(pos_rows) / total_pairs if total_pairs else None
        enrich = {}
        for k in ENRICH_K:
            in_k = topk_mask(rank, k)
            prec = sum(1 for i in pos_rows if in_k[i]) / max(int(in_k.sum()), 1)
            cov = float((er <= k).mean()) if len(er) else None
            exp = float(np.mean(np.minimum(k, en) / en)) if len(en) else None
            enrich[f"top{k}"] = {"event_coverage": dp._round(cov), "expected_by_chance": dp._round(exp),
                                 "lift_vs_chance": dp._round(cov / exp) if cov is not None and exp else None,
                                 "precision": dp._round(prec, 6), "base_rate": dp._round(base_pos, 6),
                                 "precision_lift": dp._round(prec / base_pos) if base_pos else None,
                                 "control_coverage": dp._round(float((cr <= k).mean())) if len(cr) else None}
        for q in ENRICH_PCT:
            cov = float((er <= np.maximum(1, np.floor(q * en))).mean()) if len(er) else None
            exp = float(np.mean(np.maximum(1, np.floor(q * en)) / en)) if len(en) else None
            enrich[f"top{int(q * 100)}pct"] = {"event_coverage": dp._round(cov), "expected_by_chance": dp._round(exp),
                                               "lift_vs_chance": dp._round(cov / exp) if cov and exp else None}
        pr = er / en if len(er) else er
        out[str(off)] = {"events_total": n_events, "events_with_rank": len(er),
                         "median_rank": dp._med(er), "p25_rank": dp._round(np.percentile(er, 25)) if len(er) else None,
                         "p75_rank": dp._round(np.percentile(er, 75)) if len(er) else None,
                         "median_rank_percentile_from_top": dp._med(pr),
                         "control_median_rank": dp._med(cr), "control_n": len(cr),
                         "pct_top3": dp._round(float((er <= 3).mean())) if len(er) else None,
                         "pct_top5": dp._round(float((er <= 5).mean())) if len(er) else None,
                         "pct_top10": dp._round(float((er <= 10).mean())) if len(er) else None,
                         "control_pct_top5": dp._round(float((cr <= 5).mean())) if len(cr) else None,
                         "enrichment": enrich}
    return out


def single_feature_lift(grid: rd.Grid, k: int = 5) -> dict:
    """Her tekil yüzdelik özniteliğin T0−15 ve T0'da Top-K kapsama kaldıracı (kontrol: şans K/N)."""
    pos = _row_pos(grid)
    out = {}
    for name in RANK_FEATURES:
        df = grid.rows.assign(_s=grid.rows[f"pct_{name}"])
        r = rank_within_timestamp(df, "_s").to_numpy(float)
        n = df.groupby("bar_start_ns")["_s"].transform("count").to_numpy(float)
        res = {}
        for off in (-15, 0):
            hits, exp = [], []
            for s, evs in enumerate(grid.events):
                for ev in evs:
                    i = pos.get((s, ev.start_ns + off * MIN_NS - BAR_NS)) if ev.evaluable else None
                    if i is not None and np.isfinite(r[i]):
                        hits.append(r[i] <= k)
                        exp.append(min(k, n[i]) / n[i])
            cov = float(np.mean(hits)) if hits else None
            res[str(off)] = {"coverage": dp._round(cov), "lift": dp._round(cov / np.mean(exp)) if hits else None}
        out[name] = res
    return out


# ------------------------------------------------------------------ sıralama kalitesi
def ranking_quality(grid: rd.Grid, rank_col: str, ks=(1, 3, 5)) -> dict:
    """Zaman damgası başına Precision@K, Recall@K, NDCG@5 (ilgili = satırın görünür zamanda erken yakalama etiketi
    `grid.y`)."""
    r = grid.col(rank_col)
    y = grid.y
    b = grid.rows["bar_start_ns"].to_numpy(np.int64)
    ok = np.isfinite(r)
    df = pd.DataFrame({"b": b[ok], "r": r[ok], "y": y[ok], "day": grid.day[ok]})
    out = {}
    tot_rel = df["y"].sum()
    for k in ks:
        top = df[df["r"] <= k]
        p_ts = top.groupby("b")["y"].sum() / k
        out[f"precision@{k}"] = dp._round(p_ts.mean()) if len(p_ts) else None
        out[f"recall@{k}"] = dp._round(top["y"].sum() / tot_rel) if tot_rel else None
    top5 = df[df["r"] <= 5].copy()
    top5["g"] = top5["y"] / np.log2(top5["r"] + 1)
    dcg = top5.groupby("b")["g"].sum()
    rel_n = df.groupby("b")["y"].sum().clip(upper=5)
    idcg = rel_n.map(lambda m: sum(1 / np.log2(j + 2) for j in range(int(m))))
    nd = (dcg.reindex(idcg.index).fillna(0) / idcg.replace(0, np.nan)).dropna()
    out["ndcg@5"] = dp._round(nd.mean()) if len(nd) else None
    out["timestamps"] = int(df["b"].nunique())
    out["relevant_rows"] = int(tot_rel)
    by_day = {}
    for d, g in df.groupby("day"):
        t = g[g["r"] <= 3]
        by_day[str(d)] = dp._round((t.groupby("b")["y"].sum() / 3).mean()) if len(t) else None
    out["precision@3_by_day"] = by_day
    return out


# ------------------------------------------------------------------ değerlendirme ve kararlılık
def day_stability(grid: rd.Grid, mask: np.ndarray) -> dict:
    days = sorted({d for _, d in grid.sessions})
    per = [grid.both(mask, {d}) for d in days]
    return rd._stab(per)


def meets(m: dict) -> bool:
    return (m["FPR"] is not None and m["FPR"] <= TARGETS["FPR_v2_max"] and m["recall_eval"] is not None
            and m["recall_eval"] >= TARGETS["recall_evaluable_v2_min"] and m["lead"] is not None
            and m["lead"] <= TARGETS["median_lead_v2_max"])


def evaluate_policies(hist: rd.Grid, pilot: rd.Grid) -> dict:
    out = {}
    for name, spec in POLICIES.items():
        mh, mp = policy_mask(hist, spec), policy_mask(pilot, spec)
        h, p = hist.both(mh), pilot.both(mp)
        out[name] = {"spec": spec, "historical": h, "pilot": p, "historical_meets_targets": meets(h),
                     "pilot_meets_targets": meets(p), "_hist_mask": mh, "_pilot_mask": mp}
    return out


def rank_top3(results: dict) -> list[str]:
    """Önceden sabit sıralama: (tarihsel+pilot hedef sayısı) → pilot görünür (recall − FPR) → pilot lead ≤ 0.5 →
    tarihsel (recall − FPR) → ad."""
    def n_targets(m):
        return sum([m["FPR"] is not None and m["FPR"] <= 0.25, (m["recall_eval"] or 0) >= 0.40,
                    m["lead"] is not None and m["lead"] <= 0.50])

    def key(name):
        r = results[name]
        h, p = r["historical"], r["pilot"]
        return (-(n_targets(h) + n_targets(p)), -((p["recall_eval"] or 0) - (p["FPR"] or 1)),
                -((h["recall_eval"] or 0) - (h["FPR"] or 1)), name)
    return sorted(results, key=key)[:3]


# ------------------------------------------------------------------ öğrenmeli sıralama (teşhis)
LTR_FEATURES = tuple(f"pct_{n}" for n in RANK_FEATURES)


def _ltr_X(grid: rd.Grid) -> np.ndarray:
    return np.nan_to_num(grid.rows[list(LTR_FEATURES)].to_numpy(float), nan=0.5)


def ltr(hist: rd.Grid, pilot: rd.Grid) -> dict:
    """Yüzdelik öznitelikler → lojistik skor; skor yalnız AYNI zaman damgasında sıralanır. Tarihsel: 5 ardışık gün
    bloğu; pilot: tarihsel + diğer 4 pilot günü ile eğit, kalan günü sına (gün-dışarıda)."""
    Xh, Xp = _ltr_X(hist), _ltr_X(pilot)
    hdays = sorted({d for _, d in hist.sessions})
    pdays = sorted({d for _, d in pilot.sessions})
    sh = np.full(len(Xh), np.nan)
    for blk in rd.blocks(hdays):
        tr = ~np.isin(hist.day, blk)
        beta = dp.fit_logistic(Xh[tr] - 0.5, hist.y[tr])
        te = np.isin(hist.day, blk)
        sh[te] = dp.predict(beta, Xh[te] - 0.5)
    sp_ = np.full(len(Xp), np.nan)
    for d in pdays:
        trp = pilot.day != d
        beta = dp.fit_logistic(np.vstack([Xh, Xp[trp]]) - 0.5, np.concatenate([hist.y, pilot.y[trp]]))
        te = pilot.day == d
        sp_[te] = dp.predict(beta, Xp[te] - 0.5)
    full = dp.fit_logistic(Xh - 0.5, hist.y)
    hist.rows["LTR"], pilot.rows["LTR"] = sh, sp_
    hist.rows["rank_LTR"] = rank_within_timestamp(hist.rows, "LTR").to_numpy()
    pilot.rows["rank_LTR"] = rank_within_timestamp(pilot.rows, "LTR").to_numpy()
    res = {"model": "logistic (numpy IRLS, L2=1, balanced) on within-timestamp percentile features; ranks only "
                    "within the same timestamp", "target": "row visible inside an evaluable V2 window with lead <= 0.5",
           "coef_historical_full": {n: round(float(c), 4) for n, c in zip(LTR_FEATURES, full[1:])},
           "quality_historical": ranking_quality(hist, "rank_LTR"), "quality_pilot": ranking_quality(pilot, "rank_LTR"),
           "policies": {}}
    for k in (3, 5):
        for p in (1, 2):
            spec = {"k": k, "floor": None, "persistence": p, "score": "LTR"}
            mh, mp = policy_mask(hist, spec, "LTR", "rank_LTR"), policy_mask(pilot, spec, "LTR", "rank_LTR")
            res["policies"][f"LTR|top{k}|p{p}"] = {"historical": hist.both(mh), "pilot": pilot.both(mp),
                                                   "historical_stability": day_stability(hist, mh),
                                                   "pilot_stability": day_stability(pilot, mp)}
    return res


# ------------------------------------------------------------------ 1m ↔ 5m sıralama (pilot, gerçek arşiv)
def minute_scores(bars: pd.DataFrame, bench_sym: str, bar_min: int) -> pd.DataFrame:
    """Varlık × zaman: 15 dk getiri, XU100'e göre 15 dk getiri, 15 dk hacim / önceki 15 dk hacim (zaman tabanlı;
    eksik dakika doldurulmaz → değer yok). Skor = üç yüzdeliğin ortalaması, sıra aynı zaman damgasında."""
    n = 15 // bar_min
    parts = []
    bench = bars[bars["symbol"] == bench_sym].set_index(pd.to_datetime(bars.loc[bars["symbol"] == bench_sym,
                                                                                 "bar_start_ns"], utc=True))["close"]
    for sym, g in bars[bars["symbol"] != bench_sym].groupby("symbol"):
        idx = pd.DatetimeIndex(pd.to_datetime(g["bar_start_ns"].to_numpy(), utc=True))
        lag = idx - pd.Timedelta(minutes=15)
        c = pd.Series(g["close"].to_numpy(float), index=idx)
        ret = c.to_numpy() / c.reindex(lag).to_numpy() - 1
        bret = bench.reindex(idx).to_numpy() / bench.reindex(lag).to_numpy() - 1
        v = pd.Series(g["volume"].to_numpy(float), index=idx)
        roll = v.rolling("15min").sum()
        roll[v.rolling("15min").count() < n] = np.nan
        vacc = roll.to_numpy() / roll.reindex(lag).to_numpy()
        parts.append(pd.DataFrame({"symbol": sym, "bar_start_ns": g["bar_start_ns"].to_numpy(np.int64),
                                   "session_date": g["session_date"].to_numpy(), "ret15": ret, "rel15": ret - bret,
                                   "vacc15": vacc}))
    df = pd.concat(parts, ignore_index=True).replace([np.inf, -np.inf], np.nan)
    gr = df.groupby("bar_start_ns")
    for c in ("ret15", "rel15", "vacc15"):
        df[f"pct_{c}"] = gr[c].rank(pct=True)
    df["score"] = df[["pct_ret15", "pct_rel15", "pct_vacc15"]].mean(axis=1, skipna=False)
    df["rank"] = rank_within_timestamp(df, "score")
    df["info_ns"] = df["bar_start_ns"] + bar_min * MIN_NS
    return df


def one_minute_ranking(pilot: rd.Grid, b5: pd.DataFrame, b1: pd.DataFrame, bench: str, k: int = 5) -> dict:
    s5, s1 = minute_scores(b5, bench, 5), minute_scores(b1, bench, 1)
    seen = {5: dp.probe_seen(b5), 1: dp.probe_seen(b1)}
    per = []
    for s, evs in enumerate(pilot.events):
        sym, day = pilot.sessions[s]
        for ev in evs:
            if not ev.evaluable:
                continue
            rec = {"symbol": sym, "session": str(day)}
            for res, df in ((5, s5), (1, s1)):
                g = df[(df["symbol"] == sym) & (df["session_date"] == str(day))].sort_values("bar_start_ns")
                w = g[(g["info_ns"] >= ev.start_ns - 30 * MIN_NS) & (g["info_ns"] <= ev.peak_ns)]
                top = (w["rank"] <= k).to_numpy()
                first = w["info_ns"].to_numpy()[top][0] if top.any() else None
                pers = None
                for j in range(1, len(top)):
                    if top[j] and top[j - 1]:
                        pers = w["info_ns"].to_numpy()[j]
                        break
                vis, src = dp.visible_time(*seen[res], sym, first, res)
                rec[f"first_top{k}_{res}m"] = first
                rec[f"first_persistent_top{k}_{res}m"] = pers
                rec[f"visible_first_top{k}_{res}m"] = vis
                rec[f"visible_source_{res}m"] = src
            per.append(rec)

    def gain(a, b):
        v = [(r[a] - r[b]) / MIN_NS for r in per if r[a] is not None and r[b] is not None]
        return {"n": len(v), "median_min": dp._med(v), "p25": dp._round(np.percentile(v, 25)) if v else None,
                "p75": dp._round(np.percentile(v, 75)) if v else None}
    return {"k": k, "events": len(per),
            "events_with_top_k_5m": sum(r[f"first_top{k}_5m"] is not None for r in per),
            "events_with_top_k_1m": sum(r[f"first_top{k}_1m"] is not None for r in per),
            "information_gain_first_topk_5m_minus_1m": gain(f"first_top{k}_5m", f"first_top{k}_1m"),
            "information_gain_persistent_5m_minus_1m": gain(f"first_persistent_top{k}_5m",
                                                            f"first_persistent_top{k}_1m"),
            "visible_gain_first_topk_5m_minus_1m": gain(f"visible_first_top{k}_5m", f"visible_first_top{k}_1m"),
            "first_topk_minus_T0_5m": _rel(per, pilot, f"first_top{k}_5m"),
            "first_topk_minus_T0_1m": _rel(per, pilot, f"first_top{k}_1m"),
            "definition": "score = mean percentile of 15-min return, 15-min return minus XU100, 15-min volume / "
                          "previous 15-min volume; rank within the same timestamp; window [T0-30m, peak]; archived "
                          "bars only"}


def _rel(per, pilot, key):
    starts = {}
    for s, evs in enumerate(pilot.events):
        sym, day = pilot.sessions[s]
        for ev in evs:
            if ev.evaluable:
                starts.setdefault((sym, str(day)), []).append(ev.start_ns)
    out, used = [], defaultdict(int)
    for r in per:
        k = (r["symbol"], r["session"])
        t0 = starts[k][used[k]]
        used[k] += 1
        if r[key] is not None:
            out.append((r[key] - t0) / MIN_NS)
    return {"n": len(out), "median_min": dp._med(out)}
