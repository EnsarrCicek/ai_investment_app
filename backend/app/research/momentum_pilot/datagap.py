"""Momentum — veri açığı (data gap) analizi: olumsuz sonucun dondurulması, pilot hata taksonomisi, düşük gecikme
karşı-olgusu, kaynak gereksinim matrisi (YALNIZ araştırma; holdout yok, Pilot-2 yok, aday yok, kural ayarı yok).

* Karşı-olgu: kural tanımları DEĞİŞMEZ (Round 1 WATCH, A5d, redesign iki aşamalı ve lojistik; model/eşik tarihsel
  eğitimden aynen). Yalnız görünürlük gecikmesi 0/1/3/5/10/15 dk varsayılır; alarm satırları aynı kalır, değişen
  görünür zaman ve o andaki giriş fiyatıdır.
* Taksonomi sezgiseldir ve NEDENSELLİK İDDİA ETMEZ: gözlenebilir OHLCV zaman çizgisinden, olayın hangi ek veriyle
  "potansiyel olarak ele alınabileceğini" sınıflar. Haber/KAP arşivi yoksa E sınıfı doğrulanamaz (uydurma yok).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from app.research.momentum_final import candidate as cd
from app.research.momentum_pilot import deep as dp
from app.research.momentum_pilot import redesign as rd
from app.research.momentum_pilot import split as sp

MANIFEST_PATH = sp.HERE / "momentum_data_gap_manifest.json"
CONCLUSION = "OHLCV_ONLY_NOT_SUFFICIENT_FOR_CURRENT_TARGET"
DELAYS = (0, 1, 3, 5, 10, 15)
TAXONOMY = ("A_LOW_LATENCY_PRICE", "B_ORDER_FLOW", "C_ORDER_BOOK_IMBALANCE", "D_VOLUME_DIRECTION_AGGRESSOR",
            "E_NEWS_KAP_EVENT", "F_NO_OBVIOUS_PRECURSOR")
FAILED_FAMILIES = ("absolute threshold rules (Round 1 WATCH/STRONG, historical frozen candidate, gated variants)",
                   "redesigned precursor features (compression/volume/relative-strength/structure/regime)",
                   "simple ML (logistic regression, shallow gradient boosting)", "two-stage precursor + confirmation",
                   "cross-sectional Top-K ranking (3 composite scores, K 1/3/5, persistence 1-3)",
                   "learning-to-rank (logistic within-timestamp)")


class DataGapManifestError(RuntimeError):
    pass


# ------------------------------------------------------------------ 1) olumsuz sonucu dondur
def manifest_body(pilot_sha: str, latency: dict, evidence_files: dict[str, str], created_at: str) -> dict:
    return {"version": "MOMENTUM_DATA_GAP_V1", "kind": "RESEARCH_CONCLUSION (not a candidate freeze)",
            "pilot_manifest_sha256": pilot_sha, "label_v2_sha256": sp.LABEL_V2_SHA256,
            "provider": {"name": "yahoo_finance", "type": "public chart endpoint, delayed intraday OHLCV",
                         "intervals": ["1m", "5m"], "api_key": False},
            "measured_latency_minutes": {"1m": latency["1m"], "5m": latency["5m"],
                                         "method": "PROBE first_seen - bar_end over the 5 PILOT sessions; 5-minute "
                                                   "probe cadence makes values an upper bound"},
            "failed_architecture_families": list(FAILED_FAMILIES),
            "targets": {"FPR_v2_max": 0.25, "recall_evaluable_v2_min": 0.40, "median_visible_lead_v2_max": 0.50},
            "evidence_result_sha256": evidence_files,
            "conclusion": CONCLUSION, "future_holdout": "UNREAD (2026-11-02 onward)", "created_at": created_at}


def freeze_manifest(body: dict, path: Path = MANIFEST_PATH) -> dict:
    doc = {"manifest": body, "sha256": cd.sha256_of(body)}
    if path.exists():
        got = json.loads(path.read_text(encoding="utf-8"))
        if cd.sha256_of(got["manifest"]) != got["sha256"]:
            raise DataGapManifestError("veri açığı manifesti bozulmuş")
        if {k: v for k, v in got["manifest"].items() if k != "created_at"} != \
                {k: v for k, v in body.items() if k != "created_at"}:
            raise DataGapManifestError("veri açığı sonucu dondurulmuş; değişiklik yeni sürüm gerektirir")
        return got
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")
    return doc


def file_sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ 2) pilot hata taksonomisi
def classify_event(rec: dict, news_available: bool, news_hit: bool) -> str:
    """`rec` = redesign.bottleneck olay kaydı. Öncelik: haber (yalnız arşiv varsa) → gecikmeye kaybedilen →
    dikey → erken kanıt var ama ayırt edilemiyor (hacim önce: yön/agresör; fiyat önce: emir akışı) → geç kanıt
    (kırılımla: emir defteri; kırılımsız: öncü yok)."""
    if news_available and news_hit:
        return TAXONOMY[4]
    cls = rec["class"]
    if cls == rd.BOTTLENECK[1]:
        return TAXONOMY[0]
    if cls == rd.BOTTLENECK[3]:
        return TAXONOMY[5]
    if cls == rd.BOTTLENECK[0]:
        t = {k: rec.get(f"{k}_minus_T0_min") for k in ("first_price_evidence", "first_volume_anomaly",
                                                        "first_relative_strength", "first_acceleration")}
        got = {k: v for k, v in t.items() if v is not None}
        first = min(got, key=lambda k: (got[k], k)) if got else None
        return TAXONOMY[3] if first == "first_volume_anomaly" else TAXONOMY[1]
    return TAXONOMY[2] if rec.get("first_breakout_minus_T0_min") is not None else TAXONOMY[5]


def taxonomy(neck: dict, news_available: bool = False) -> dict:
    per = []
    for rec in neck["events"]:
        per.append({**{k: rec[k] for k in ("symbol", "session", "class", "rise_min")},
                    "data_gap_class": classify_event(rec, news_available, False)})
    counts = Counter(r["data_gap_class"] for r in per)
    return {"events": len(per), "counts": {k: counts.get(k, 0) for k in TAXONOMY}, "per_event": per,
            "news_archive_available": news_available,
            "note": "heuristic 'potentially addressable by' classes from observable OHLCV timelines; NO causality; "
                    "E cannot be assigned without a news/KAP archive (none exists for the pilot sessions)"}


def addressable(tax: dict) -> dict:
    c, n = tax["counts"], tax["events"]
    out = {"LOW_LATENCY_PRICE (late visibility)": c[TAXONOMY[0]],
           "ORDER_FLOW (price/volume false-positive discrimination)": c[TAXONOMY[1]] + c[TAXONOMY[3]],
           "ORDER_BOOK (pre-breakout liquidity shift)": c[TAXONOMY[2]],
           "AGGRESSOR_SIDE (direction of early volume)": c[TAXONOMY[3]],
           "KAP/NEWS (catalyst-driven vertical moves)": "UNVERIFIABLE (no archive); upper bound = vertical/no-"
                                                       f"precursor events = {c[TAXONOMY[5]]}"}
    return {"events": n, "potentially_addressable": out,
            "share": {k: (round(v / n, 3) if isinstance(v, int) and n else v) for k, v in out.items()}}


# ------------------------------------------------------------------ 3) düşük gecikme karşı-olgusu
def delayed_grid(grid: rd.Grid, delay_min: float):
    """Aynı ızgara; görünür zaman = bilgi zamanı + gecikme, giriş = o andan sonraki ilk barın açılışı."""
    g = object.__new__(rd.Grid)
    g.__dict__.update(grid.__dict__)
    g.visible = grid.info + int(delay_min * rd.MIN_NS)
    g.entry_vis = np.full(len(grid.rows), np.nan)
    st_all = grid.rows["bar_start_ns"].to_numpy(np.int64)
    op_all = grid.rows["Open"].to_numpy(float)
    for s, idx in grid.rows_of.items():
        st, op = st_all[idx], op_all[idx]
        j = np.searchsorted(st, g.visible[idx], side="left")
        ok = j < len(st)
        g.entry_vis[idx[ok]] = op[j[ok]]
    return g


def frozen_redesign_masks(hist: rd.Grid, pilot: rd.Grid) -> dict[str, np.ndarray]:
    """Redesign mimarileri: tarihsel tüm geliştirme verisiyle eğitim + tarihsel eşik (yeniden ayar YOK)."""
    hist_days = sorted({d for _, d in hist.sessions})
    full = np.ones(len(hist.rows), dtype=bool)
    out = {}
    sc_h, _ = rd.scores_for("logistic", hist, full, hist)
    sc_p, _ = rd.scores_for("logistic", hist, full, pilot)
    thr, _ = rd.choose_threshold(hist, sc_h, hist_days)
    out["redesign_logistic"] = np.nan_to_num(sc_p, nan=-np.inf) >= thr
    sc_h, _ = rd.scores_for("two_stage", hist, full, hist)
    sc_p, _ = rd.scores_for("two_stage", hist, full, pilot)
    _, pick = rd._two_stage_pick(hist, sc_h, hist_days)
    out["redesign_two_stage"] = rd.two_stage_mask(pilot, sc_p, pick["arm_threshold"])
    return out


def latency_counterfactual(p, events, cand: dict, pilot_grid: rd.Grid, redesign_masks: dict) -> dict:
    """Kurallar sabit; yalnız gecikme değişir. Round 1 WATCH / A5d: pilot paneli `p.build_labels(d)` (fx kaydırması);
    redesign: aynı alarm satırları, görünür zaman = bilgi + d."""
    for d in DELAYS:
        if d not in p.labels:
            p.build_labels(d)
    rules = {"round1_watch": dp.grid_mask(p, cand, dp.GRID["A0_round1_watch"]),
             "A5d_weak_volume+relative": dp.grid_mask(p, cand, dp.GRID["A5d_weak_volume+relative"])}
    out = {}
    for name, m in rules.items():
        out[name] = {f"d{d}": _brief(dp.evaluate_subset(p, events, m, d)) for d in DELAYS}
        out[name]["measured"] = _brief(dp.evaluate_subset(p, events, m, "measured"))
    for name, m in redesign_masks.items():
        out[name] = {f"d{d}": _brief_rd(delayed_grid(pilot_grid, d).evaluate(m)) for d in DELAYS}
        out[name]["measured"] = _brief_rd(pilot_grid.evaluate(m))
    for name, v in out.items():
        v["meets_targets_at"] = [k for k, m in v.items() if isinstance(m, dict) and _meets(m)]
    return out


def _brief(m: dict) -> dict:
    return {"alerts": m["alerts"], "TP": m["TP"], "precision": m["precision_v2"], "recall_eval": m["recall_evaluable_v2"],
            "FPR": m["FPR_v2"], "lead": m["median_lead_v2"]}


def _brief_rd(m: dict) -> dict:
    return {k: m[k] for k in ("alerts", "TP", "precision", "recall_eval", "FPR", "lead")}


def _meets(m: dict) -> bool:
    return (m["FPR"] is not None and m["FPR"] <= 0.25 and (m["recall_eval"] or 0) >= 0.40
            and m["lead"] is not None and m["lead"] <= 0.50)


# ------------------------------------------------------------------ 10) sağlayıcı gereksinim matrisi
ROWS = ("real_time_trades", "1m_bars", "tick_data", "bid_ask", "level2_depth", "aggressor_side", "historical_replay",
        "kap_news", "api_availability", "timestamp_precision", "bist_coverage", "licensing_requirement",
        "cost_class", "rate_limits")
U = "UNKNOWN"


def provider_matrix(latency: dict, coverage: int, universe: int) -> dict:
    """Yalnız projede zaten bulunan kaynaklar. Bilinmeyen = UNKNOWN (fiyat/kimlik bilgisi uydurulmaz)."""
    yahoo = {"real_time_trades": f"NO (delayed; measured 5m median {latency['5m']['median']} min, 1m "
                                 f"{latency['1m']['median']} min)",
             "1m_bars": "YES (archived prospectively since 2026-10-19; short range per request)",
             "tick_data": "NOT_OBSERVED", "bid_ask": "NOT_OBSERVED (chart endpoint returns OHLCV only)",
             "level2_depth": "NOT_OBSERVED", "aggressor_side": "NO",
             "historical_replay": "LIMITED (5m ~60 days in project cache; 1m only short recent range)",
             "kap_news": "PARTIAL (project has a yahoo_news_provider; not KAP)",
             "api_availability": "public unauthenticated endpoint (no API key in project)",
             "timestamp_precision": "bar start, minute resolution; no exchange event timestamps",
             "bist_coverage": f"{coverage}/{universe} primary universe symbols with identity MATCH",
             "licensing_requirement": U, "cost_class": "no key / no paid plan in project", "rate_limits": U}
    foreks = {r: U for r in ROWS} | {
        "kap_news": "YES (official RSS 2.0 feed used by project news provider; general market news)",
        "api_availability": "RSS feed (robots.txt disallows /api/)", "timestamp_precision": "RSS pubDate",
        "historical_replay": "NO (live feed only; project keeps no local archive)",
        "real_time_trades": U, "1m_bars": U, "level2_depth": U}
    gnews = {r: "NO" for r in ("real_time_trades", "1m_bars", "tick_data", "bid_ask", "level2_depth",
                               "aggressor_side")} | {
        "historical_replay": "search-based; republished timestamps may differ from original publication",
        "kap_news": "YES (aggregated Turkish financial media via news search)", "api_availability": "RSS search",
        "timestamp_precision": "RSS pubDate", "bist_coverage": U, "licensing_requirement": U, "cost_class": U,
        "rate_limits": U}
    kap = {r: U for r in ROWS} | {
        "kap_news": "YES (official public disclosures; referenced in project docs, NOT integrated)",
        "real_time_trades": "NO", "1m_bars": "NO", "tick_data": "NO", "bid_ask": "NO", "level2_depth": "NO",
        "aggressor_side": "NO"}
    return {"rows": list(ROWS), "columns": {"YAHOO_FINANCE (current reference)": yahoo,
                                            "FOREKS_RSS (project news provider)": foreks,
                                            "GOOGLE_NEWS_RSS (project news provider)": gnews,
                                            "KAP (referenced, not integrated)": kap},
            "missing_capabilities_no_known_provider": ["real-time trades", "tick data", "bid/ask", "Level 2 depth",
                                                       "aggressor side"],
            "note": "providers listed only if already present in project code/docs; capabilities not verified are "
                    "UNKNOWN; no credentials or prices invented"}


def decide(cf: dict, tax: dict) -> dict:
    latency_solves = any(v["meets_targets_at"] for v in cf.values())
    c = tax["counts"]
    discrim = c[TAXONOMY[1]] + c[TAXONOMY[3]]
    if latency_solves:
        choice = "A) LOW-LATENCY OHLCV MAY BE ENOUGH"
    elif discrim >= tax["events"] / 2:
        choice = "D) MULTI-SOURCE LIKELY REQUIRED"
    else:
        choice = "INCONCLUSIVE"
    return {"latency_alone_meets_targets_for_any_rule": latency_solves,
            "events_needing_discrimination_data": discrim, "decision": choice}
