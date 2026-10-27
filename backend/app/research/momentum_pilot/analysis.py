"""Momentum PILOT analizi — YALNIZ pilot seansları (PILOT / DEVELOPMENT ONLY; final/prospektif sonuç DEĞİL).

* Veri: WINDOWS PRIMARY arşivinin FIRST_SEEN barları (`split.load_primary_bars`, holdout koruması zorunlu).
  Isınma (taban) için başlangıç öncesi arşivlenmiş FULL seanslar kullanılır; tüketilmiş final tarihleri kullanılmaz.
* Öznitelikler mevcut hatla aynı: üretim `compute_features` (Round 1, F1, 15 dk), `extended_features.bar_features`,
  `cross_section` (referans paneli = birincil evren, kendisi hariç), `merge_rows` (Round 1 final düzeyi).
* Etiket: MOMENTUM_EVENT_LABEL_V2 (dondurulmuş SHA 9b9602c1…), birincil birim: varlık-seans başına ilk WATCH.
* Kurallar: Round 1 final WATCH (3/3), Round 1 final STRONG (3/3), tarihsel dondurulmuş aday (rel_ret_z_3 ≥
  5.094139728812382, 1/1). Hiçbiri üretim adayı değildir; eşik değişmez.
* 1m ↔ 5m: gerçekten arşivlenmiş 1m barları; yeniden kurulmuş/uydurma bar YOK. Ölçüler iki çözünürlükte AYNI sabit
  tanımla (aynı 15 dk pencere) hesaplanır; sabitler sonuçlara bakılmadan seçildi ve ayarlanmaz.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_calibration import experiment as r1x
from app.research.momentum_calibration.labels import labels_for_session
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_label_v2 import experiment as lx
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_pilot import split as sp
from app.research.momentum_round2 import experiment as r2
from app.research.momentum_round2.metrics import run_low
from app.services.momentum.early_momentum_engine import compute_features
from app.services.momentum import extended_features as xf

DELAY = 15  # öznitelik satırları 15 dk gecikmeyle; d0 = aynı satırlar bilgi zamanında (fx.Panel kaydırması)
DELAYS = (15, 0)
RULE_NAMES = {"frozen_candidate_watch_1of1": "C) historical frozen candidate rel_ret_z_3 >= 5.094139728812382, 1/1",
              "round1_final_watch_3of3": "A) Round 1 WATCH", "round1_final_strong_3of3": "B) Round 1 STRONG"}
FROZEN_THRESHOLD = 5.094139728812382

# Olay tablosu kanıtları — mevcut `fx.evidence_masks` tanımlarıyla aynı (yeni eşik yok)
EVIDENCE = ("first_price_evidence", "first_volume_anomaly", "first_relative_strength", "first_acceleration")

# Erken hareket grupları (Label V2 lead hedefi 0.5)
EARLY, LATE, NO_SIGNAL, VERTICAL, OPENING = ("EARLY_DETECTABLE", "LATE_DETECTABLE", "NO_EARLY_SIGNAL",
                                             "VERTICAL_MOVE", "OPENING/PRE_OBSERVATION")
VERTICAL_MAX_MIN = 15  # dip→tepe ≤ 15 dk: dikey (fx "abrupt_vertical_jump" ile aynı sınır)

# İstenen YP sınıflaması (mevcut `au.FP_ORDER` önceliği korunur; listede olmayan bayraklar → OTHER)
FP_TAXONOMY = ("BENCHMARK_SHOCK", "GAP_THEN_FADE", "BREAKOUT_FAILURE", "PRICE_SPIKE_NO_VOLUME",
               "VOLUME_SPIKE_NO_CONTINUATION", "SHORT_LIVED_ACCELERATION")

# 1m ↔ 5m ortak tanımlar (sabit, ayarlanmaz)
WINDOW_MIN = 15
PRICE_RISE = 0.02  # kapanış ≥ seansın o ana kadarki en düşüğü × 1.02
ACCEL_MIN_RET = 0.01  # son 15 dk getirisi ≥ %1 ve önceki 15 dk getirisinden büyük
VOLUME_MULT = 3.0  # son 15 dk hacmi ≥ 3 × önceki seansların 15 dk hacim medyanı


# ------------------------------------------------------------------ veri
def to_asset_data(symbol: str, df: pd.DataFrame) -> r1ds.AssetData:
    """Arşiv satırları → mevcut hattın AssetData biçimi (İstanbul saatli bar başlangıçları)."""
    idx = pd.DatetimeIndex(pd.to_datetime(df["bar_start_ns"].to_numpy(), utc=True)).tz_convert(ISTANBUL_TZ)
    bars = pd.DataFrame({"Open": df["open"].to_numpy(float), "High": df["high"].to_numpy(float),
                         "Low": df["low"].to_numpy(float), "Close": df["close"].to_numpy(float),
                         "Volume": df["volume"].to_numpy(float)}, index=idx).sort_index()
    ident = "MATCH" if len(df) and (df["identity_check"] == "MATCH").all() else "UNVERIFIED"
    prov = {"requested_symbol": symbol, "provider_symbol": f"{symbol}.IS", "currency": "TRY", "exchange": "IST",
            "identity_check": ident, "source": sp.PRIMARY_SOURCE,
            "retrieved_at": pd.Timestamp(int(df["first_seen_ns"].max()), tz="UTC").to_pydatetime() if len(df) else None}
    fetched = prov["retrieved_at"] or datetime.now(ISTANBUL_TZ)
    return r1ds.AssetData(symbol, bars, prov, fetched)


def _features_worker(args):
    symbol, data, bench, days = args
    config = r1x.config_for("F1", delay=DELAY)
    have = set(data.bars.index.date)
    r1_rows, ext_rows = [], []
    for day in days:
        if day not in have:
            continue
        window = r1ds.window_for(data, day)
        for t in r1x.eval_times(day, DELAY):
            snap = compute_features(symbol, window, data.provenance, t, config, None)
            m = snap.metrics or {}
            r1_rows.append({"symbol": symbol, "day": day, "t": t, "status": snap.status,
                            "components": snap.components, "persistent": snap.persistent, "data_gap": snap.data_gap,
                            "session_return_pct": m.get("session_return_pct"),
                            "raw_relative_volume": m.get("raw_relative_volume"), "price_z": m.get("price_z")})
        ext_rows.extend(r2.ext_rows_for_day(data, bench, day, DELAY))
    return r1_rows, ext_rows


def build_rows(data: dict[str, r1ds.AssetData], bench: r1ds.AssetData, days: list[date], workers: int = 7) -> list:
    r1_rows, ext_rows = [], []
    jobs = [(s, d, bench, days) for s, d in sorted(data.items())]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for a, b in pool.map(_features_worker, jobs):
            r1_rows.extend(a)
            ext_rows.extend(b)
    ext = pd.DataFrame(ext_rows)
    return r2.merge_rows(r1_rows, r2.add_cross_section(ext, ext))


class PilotPanel(fx.Panel):
    """`fx.Panel` ile aynı; etiketler önbellek yerine verilen pilot barlarından."""

    def __init__(self, rows: list[dict], bars: dict[str, pd.DataFrame]):
        super().__init__(rows)
        self.bars = bars

    def build_labels(self, delay: int):
        shift = timedelta(minutes=15 - delay)
        by_sess = defaultdict(list)
        for i, s in enumerate(self.sess):
            by_sess[s].append(i)
        n, ns = len(self.rows), len(self.sessions)
        entry, mfe, retc = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        ev, hi_ns, hi, low = np.zeros(ns, dtype=bool), np.zeros(ns, dtype=np.int64), np.zeros(ns), np.zeros(ns)
        for s, idx in by_sess.items():
            sym, day = self.sessions[s]
            bars = self.bars[sym]
            outcome, labs = labels_for_session(bars, day, [self.rows[i]["t"] - shift for i in idx])
            for i, lab in zip(idx, labs):
                entry[i] = np.nan if lab.entry is None else lab.entry
                mfe[i] = np.nan if lab.mfe_close is None else lab.mfe_close
                retc[i] = np.nan if lab.ret_close is None else lab.ret_close
            ev[s] = outcome.max_runup >= fx.E
            hi_ns[s] = pd.Timestamp(outcome.high_time).value
            hi[s] = outcome.high
            low[s] = run_low(bars, day)
        self.labels[delay] = fr.LabelArrays(self.t15_ns - int(shift.total_seconds() * 1e9), entry, mfe, retc,
                                            self.ok, ev, hi_ns, hi, low)


def build_events(p: PilotPanel) -> tuple[list[list[lv.Swing]], np.ndarray]:
    """`lx.build_events` ile aynı (V2 olayları + açılış boşluğu), pilot barlarından."""
    events, gap = [], np.zeros(len(p.sessions), dtype=bool)
    for s, (sym, day) in enumerate(p.sessions):
        bars = p.bars[sym].dropna()
        d = bars[bars.index.date == day]
        prev = bars[bars.index.date < day]
        events.append(lv.session_events(d.index.as_unit("ns").asi8, d["High"].to_numpy(), d["Low"].to_numpy()))
        gap[s] = lv.opening_gap(float(d["Open"].iloc[0]), float(prev["Close"].iloc[-1]) if len(prev) else None)
    return events, gap


# ------------------------------------------------------------------ kurallar ve metrikler
def rule_masks(p: PilotPanel, cand: dict) -> dict[str, np.ndarray]:
    if not (cand["feature"] == "rel_ret_z_3" and cand["threshold"] == FROZEN_THRESHOLD
            and cand["confirmation"] == [1, 1]):
        raise RuntimeError("tarihsel dondurulmuş aday beklenenden farklı")
    return lx.masks(p, cand)


METRIC_KEYS = ("alerts", "alert_sessions", "precision_v2", "recall_raw_v2", "recall_evaluable_v2", "FPR_v2",
               "median_lead_v2", "caught_raw", "caught_evaluable", "false_positive_sessions", "sessions",
               "event_sessions", "non_event_sessions", "event_count_raw", "event_count_evaluable")


def rule_metrics(p: PilotPanel, events, mask: np.ndarray, delay: int) -> dict:
    m = lx.evaluate(p, events, mask, delay, lv.FIRST_ALERT)
    out = {k: m[k] for k in METRIC_KEYS}
    out["pre_event_alerts"] = m["alert_classes"][lv.PRE_EVENT]
    out["post_peak_alerts"] = m["alert_classes"][lv.POST_PEAK]
    out["no_event_session_alerts"] = m["alert_classes"][lv.NO_EVENT]
    out["in_event_alerts"] = m["alert_classes"][lv.IN_EVENT]
    out["median_first_alert_clock"] = fx._hm(m["median_first_alert_minute"])
    out["label"] = sp.PILOT_LABEL
    return out


# ------------------------------------------------------------------ olay tablosu
def _clock(ns) -> str | None:
    return None if ns is None else pd.Timestamp(int(ns), tz="UTC").tz_convert(ISTANBUL_TZ).strftime("%H:%M")


def evidence_masks(p: PilotPanel) -> dict[str, np.ndarray]:
    return {"first_price_evidence": p.ok & (p.price_impulse >= fx.THR),
            "first_volume_anomaly": p.ok & (p.volume_anomaly >= fx.THR),
            "first_relative_strength": p.ok & (p.rel_ret_z_3 >= 1.0),
            "first_acceleration": p.ok & (p.accel >= 1.0) & (p.accel_pos_3 >= 2)}


def seg_rows(p: PilotPanel) -> dict[int, np.ndarray]:
    out = defaultdict(list)
    for i, s in enumerate(p.sess):
        out[int(s)].append(i)
    return {s: np.array(v) for s, v in out.items()}


def early_group(ev: lv.Swing, gap: bool, evidence_lead: float | None) -> str:
    """Açılış: gözlem öncesi olay ya da açılış boşluğu seansında dibi İLK barda olan olay. Boşluk seansındaki sonraki
    gün içi olaylar gün içi sınıflanır (V2: boşluk ayrı seans bayrağıdır, gün içi olayı silmez)."""
    if ev.event_class == lv.PRE_OBSERVATION or (gap and ev.low_bar == 0):
        return OPENING
    if ev.event_class == lv.INTRABAR or (ev.peak_ns - ev.start_ns) <= VERTICAL_MAX_MIN * au.MIN_NS:
        return VERTICAL
    if evidence_lead is None:
        return NO_SIGNAL
    return EARLY if evidence_lead <= lv.LEAD_TARGET else LATE


def event_table(p: PilotPanel, events, gap, rules: dict[str, np.ndarray], latency: dict) -> list[dict]:
    info = p.labels[0].t_ns
    lab0, lab15 = p.labels[0], p.labels[15]
    ev_masks = evidence_masks(p)
    rows_of = seg_rows(p)
    first_alert = {name: dict(zip(*fr.first_alert_rows(mask, p.sess))) for name, mask in rules.items()}
    out = []
    for s, evs in enumerate(events):
        if not evs:
            continue
        sym, day = p.sessions[s]
        idx = rows_of[s]
        for k, ev in enumerate(evs):
            rec = {"symbol": sym, "session": str(day), "event_k": k, "primary_swing": ev.primary,
                   "event_class": ev.event_class, "opening_gap_session": bool(gap[s]),
                   "event_start": _clock(ev.start_ns), "event_peak": _clock(ev.peak_ns),
                   "event_low": round(ev.low, 4), "event_high": round(ev.high, 4),
                   "runup_pct": round(ev.runup * 100, 2), "rise_minutes": (ev.peak_ns - ev.start_ns) / au.MIN_NS}
            win = (info[idx] >= ev.start_ns) & (info[idx] <= ev.peak_ns)
            price_lead = None
            for name, mask in ev_masks.items():
                hit = idx[mask[idx] & win]
                rec[name] = _clock(info[hit[0]]) if len(hit) else None
                if name == "first_price_evidence" and len(hit):
                    price_lead = lv.lead_v2(float(lab0.entry[hit[0]]), ev)
            rec["price_evidence_lead_v2_info_time"] = price_lead
            for name in rules:
                row = first_alert[name].get(s)
                if row is None:
                    rec[f"{name}_first_alert"] = None
                    continue
                cls, matched = lv.match_alerts([int(lab15.t_ns[row])], evs)
                mine = matched[k] == 0
                rec[f"{name}_first_alert"] = {"visible_d15": _clock(lab15.t_ns[row]), "class": cls[0],
                                              "matched_this_event": mine,
                                              "lead_v2_d15": lv.lead_v2(float(lab15.entry[row]), ev) if mine else None}
            rec["provider_visibility_latency_min_5m"] = latency.get((sym, str(day)), "EOD_ONLY_NOT_PROBED")
            rec["early_move_group"] = early_group(ev, bool(gap[s]), price_lead)
            out.append(rec)
    return out


def early_summary(table: list[dict]) -> dict:
    groups = Counter(r["early_move_group"] for r in table)
    examples = {g: [{k: r[k] for k in ("symbol", "session", "event_class", "event_start", "event_peak",
                                       "runup_pct", "first_price_evidence", "price_evidence_lead_v2_info_time")}
                    for r in sorted(table, key=lambda r: -r["runup_pct"]) if r["early_move_group"] == g][:3]
                for g in groups}
    return {"counts": dict(groups), "events": len(table), "examples": examples, "label": sp.PILOT_LABEL}


# ------------------------------------------------------------------ yanlış alarmlar
def fp_analysis(p: PilotPanel, events, mask: np.ndarray, delay: int = 15) -> dict:
    lab = p.labels[delay]
    uniq, rows = fr.first_alert_rows(mask, p.sess)
    cats, other_flags, examples = Counter(), Counter(), defaultdict(list)
    for s, i in zip(uniq, rows):
        cls, _ = lv.match_alerts([int(lab.t_ns[i])], events[s])
        if cls[0] == lv.IN_EVENT:
            continue
        nxt = [j for j in range(i + 1, min(i + 4, len(p.sess))) if p.sess[j] == s]
        nxt_acc = np.nanmin(p.accel[nxt]) if nxt and np.isfinite(p.accel[nxt]).any() else np.nan
        minute = float((lab.t_ns[i] // au.MIN_NS + 180) % 1440)
        flags = au.fp_flags(locked=bool(p.locked[i]), volume_missing=bool(np.isnan(p.volume_anomaly[i])),
                            regime_shock=bool(p.regime_shock[i]), rel_ret_z_3=p.rel_ret_z_3[i], gap_pct=p.gap_pct[i],
                            ret_close=lab.ret_close[i], breakout=p.breakout[i], volume_anomaly=p.volume_anomaly[i],
                            relvol_3=p.relvol_3[i], mfe_close=lab.mfe_close[i], accel=p.accel[i],
                            accel_next_min=nxt_acc, visible_minute=minute, evidence_threshold=fx.THR, x=fx.X)
        on = [k for k in au.FP_ORDER if flags.get(k) and k in FP_TAXONOMY]
        cat = on[0] if on else "OTHER"
        cats[cat] += 1
        for k in au.FP_ORDER:
            if flags.get(k) and k not in FP_TAXONOMY:
                other_flags[k] += 1
        sym, day = p.sessions[s]
        if len(examples[cat]) < 3:
            examples[cat].append({"symbol": sym, "session": str(day), "visible_d15": _clock(lab.t_ns[i]),
                                  "v2_class": cls[0], "rel_ret_z_3": _r(p.rel_ret_z_3[i]),
                                  "volume_anomaly": _r(p.volume_anomaly[i]), "mfe_close": _r(lab.mfe_close[i]),
                                  "ret_close": _r(lab.ret_close[i])})
    return {"false_first_alerts": sum(cats.values()), "counts": dict(cats.most_common()),
            "non_taxonomy_flags_seen": dict(other_flags), "examples": dict(examples), "label": sp.PILOT_LABEL}


def _r(v, n=3):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


# ------------------------------------------------------------------ 1m ↔ 5m
def _resolution_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values("bar_start_ns").reset_index(drop=True)


def first_evidence_times(day: pd.DataFrame, bar_min: int, vol_base: float | None, start_ns: int,
                         end_ns: int) -> dict:
    """Tek çözünürlükte [start, end] içinde (bilgi zamanı = bar bitişi) ilk kanıt zamanları. `day` = o seansın
    zaman sıralı barları (bu çözünürlük)."""
    n = WINDOW_MIN // bar_min
    t_end = day["bar_start_ns"].to_numpy() + bar_min * au.MIN_NS
    close, low, high = (day[k].to_numpy(float) for k in ("close", "low", "high"))
    vol = day["volume"].to_numpy(float)
    run_low = np.minimum.accumulate(low)
    ret = np.full(len(day), np.nan)
    ret_prev = np.full(len(day), np.nan)
    if len(day) > n:
        ret[n:] = close[n:] / close[:-n] - 1
        ret_prev[n:] = ret[:-n]
    roll = pd.Series(vol).rolling(n, min_periods=n).sum().to_numpy()
    win = (t_end >= start_ns) & (t_end <= end_ns)
    conds = {"price": close >= run_low * (1 + PRICE_RISE),
             "acceleration": np.nan_to_num(ret, nan=-1) >= ACCEL_MIN_RET,
             "volume": (np.nan_to_num(roll, nan=0) >= VOLUME_MULT * vol_base) if vol_base else np.zeros(len(day), bool)}
    conds["acceleration"] &= ~np.isfinite(ret_prev) | (np.nan_to_num(ret) > np.nan_to_num(ret_prev, nan=-9))
    out = {}
    for k, c in conds.items():
        hit = np.flatnonzero(c & win)
        out[k] = int(t_end[hit[0]]) if len(hit) else None
    starts = day["bar_start_ns"].to_numpy()
    pk = np.flatnonzero((starts >= start_ns) & (t_end <= end_ns))
    out["peak_bar_start"] = int(starts[pk[np.argmax(high[pk])]]) if len(pk) else None
    return out


def volume_baseline(prior: pd.DataFrame, bar_min: int) -> float | None:
    """Önceki seansların (aynı çözünürlük) seans içi kayan 15 dk hacim toplamlarının medyanı."""
    n = WINDOW_MIN // bar_min
    vals = []
    for _, g in prior.groupby("session_date"):
        v = g.sort_values("bar_start_ns")["volume"].astype(float)
        vals.extend(v.rolling(n, min_periods=n).sum().dropna().tolist())
    vals = [x for x in vals if x > 0]
    return float(np.median(vals)) if vals else None


def timing_comparison(table: list[dict], events_by_key: dict, b5: pd.DataFrame, b1: pd.DataFrame) -> dict:
    """Her olay için 1m ve 5m'de aynı tanımlı ilk kanıt zamanı; fark = 5m − 1m (dk, pozitif = 1m daha erken)."""
    per, skipped = [], Counter()
    g5 = {k: _resolution_frame(g) for k, g in b5.groupby(["symbol", "session_date"])}
    g1 = {k: _resolution_frame(g) for k, g in b1.groupby(["symbol", "session_date"])}
    base_cache: dict = {}
    for rec in table:
        key = (rec["symbol"], rec["session"])
        ev = events_by_key[(rec["symbol"], rec["session"], rec["event_k"])]
        if key not in g1:
            skipped["no_1m_bars_for_session"] += 1
            continue
        start, end = ev.start_ns, ev.peak_ns + 5 * au.MIN_NS
        d1 = g1[key]
        in_win = d1[(d1["bar_start_ns"] >= start) & (d1["bar_start_ns"] < end)]
        expected = (end - start) // au.MIN_NS
        if len(in_win) < 0.8 * expected:
            skipped["1m_window_coverage_below_80pct"] += 1
            continue
        for res, src in ((5, b5), (1, b1)):
            bk = (rec["symbol"], rec["session"], res)
            if bk not in base_cache:
                prior = src[(src["symbol"] == rec["symbol"]) & (src["session_date"] < rec["session"])]
                base_cache[bk] = volume_baseline(prior, res)
        t5 = first_evidence_times(g5[key], 5, base_cache[(rec["symbol"], rec["session"], 5)], start, end)
        t1 = first_evidence_times(d1, 1, base_cache[(rec["symbol"], rec["session"], 1)], start, end)
        row = {"symbol": rec["symbol"], "session": rec["session"], "event_class": rec["event_class"],
               "event_start": rec["event_start"], "event_peak": rec["event_peak"], "runup_pct": rec["runup_pct"],
               "1m_window_coverage": round(len(in_win) / expected, 3)}
        for k in ("price", "acceleration", "volume"):
            row[f"{k}_5m"], row[f"{k}_1m"] = _clock(t5[k]), _clock(t1[k])
            row[f"{k}_gain_min"] = ((t5[k] - t1[k]) / au.MIN_NS) if t5[k] is not None and t1[k] is not None else None
        row["peak_5m_bar_start"], row["peak_1m_bar_start"] = _clock(t5["peak_bar_start"]), _clock(t1["peak_bar_start"])
        row["peak_1m_minus_5m_bar_start_min"] = ((t1["peak_bar_start"] - t5["peak_bar_start"]) / au.MIN_NS
                                                 if t1["peak_bar_start"] and t5["peak_bar_start"] else None)
        per.append(row)
    summ = {}
    for k in ("price", "acceleration", "volume"):
        g = [r[f"{k}_gain_min"] for r in per if r[f"{k}_gain_min"] is not None]
        only1 = sum(r[f"{k}_1m"] is not None and r[f"{k}_5m"] is None for r in per)
        only5 = sum(r[f"{k}_5m"] is not None and r[f"{k}_1m"] is None for r in per)
        summ[k] = {"events_both": len(g), "median_gain_min": _med(g), "p25": _q(g, 25), "p75": _q(g, 75),
                   "min": min(g) if g else None, "max": max(g) if g else None,
                   "only_1m_detected": only1, "only_5m_detected": only5}
    pk = [r["peak_1m_minus_5m_bar_start_min"] for r in per if r["peak_1m_minus_5m_bar_start_min"] is not None]
    summ["peak"] = {"events": len(pk), "median_1m_peak_minus_5m_bar_start_min": _med(pk)}
    return {"definitions": {"window_minutes": WINDOW_MIN, "price": f"close >= running session low x {1 + PRICE_RISE}",
                            "acceleration": f"{WINDOW_MIN}-min return >= {ACCEL_MIN_RET} and > previous "
                                            f"{WINDOW_MIN}-min return",
                            "volume": f"trailing {WINDOW_MIN}-min volume >= {VOLUME_MULT} x median trailing "
                                      f"{WINDOW_MIN}-min volume of prior archived sessions (same resolution)",
                            "information_time": "bar end", "search_window": "[event_start, event_peak bar end]",
                            "bars": "archived FIRST_SEEN 1m and 5m bars only (no reconstruction)"},
            "summary": summ, "skipped": dict(skipped), "events": per, "label": sp.PILOT_LABEL}


def _med(v):
    return float(np.median(v)) if v else None


def _q(v, q):
    return float(np.percentile(v, q)) if v else None


# ------------------------------------------------------------------ sağlayıcı gecikmesi
def latency_stats(bars: pd.DataFrame) -> dict:
    """PROBE ile ilk görülen barlar: gecikme = first_seen − bar_end (dk). Prob ritmi 5 dk olduğundan ölçüm, gerçek
    görünürlüğün en fazla ~5 dk üstündedir (üst sınır)."""
    out = {}
    for iv in ("1m", "5m"):
        d = bars[(bars["interval"] == iv) & (bars["collection_mode"] == "PROBE")]
        lat = ((d["first_seen_ns"] - d["bar_end_ns"]) / au.MIN_NS).to_numpy(float)
        out[iv] = {"n": int(len(lat)), "median_min": _med(list(lat)), "p25_min": _q(list(lat), 25),
                   "p75_min": _q(list(lat), 75), "min_min": float(lat.min()) if len(lat) else None,
                   "max_min": float(lat.max()) if len(lat) else None,
                   "symbols": int(d["symbol"].nunique()), "sessions": sorted(d["session_date"].unique().tolist())}
    return out


def latency_by_asset_session(bars5: pd.DataFrame) -> dict:
    d = bars5[bars5["collection_mode"] == "PROBE"]
    lat = (d["first_seen_ns"] - d["bar_end_ns"]) / au.MIN_NS
    return {(s, day): round(float(v), 1) for (s, day), v in lat.groupby([d["symbol"], d["session_date"]]).median()
            .items()}


# ------------------------------------------------------------------ Windows ↔ Mobil
def compare_sources(primary: pd.DataFrame, mobile: pd.DataFrame, prim_rev: pd.DataFrame | None = None,
                    mob_rev: pd.DataFrame | None = None) -> dict:
    """Yalnız toplama kalitesi. Birleştirme YOK; mobil bar birincilin yerine geçmez."""
    key = ["symbol", "interval", "bar_start_ns"]
    cols = ["open", "high", "low", "close", "volume"]
    m = primary.merge(mobile, on=key, how="outer", suffixes=("_w", "_m"), indicator=True)
    both = m[m["_merge"] == "both"]

    def eq(a, b):
        return (a == b) | (a.isna() & b.isna())
    ohlcv = np.logical_and.reduce([eq(both[f"{c}_w"], both[f"{c}_m"]) for c in cols]) if len(both) else np.array([])
    out = {"overlapping_bars": int(len(both)), "ohlcv_exact_matches": int(ohlcv.sum()),
           "different_bars": int(len(both) - ohlcv.sum()),
           "hash_matches": int((both["bar_hash_w"] == both["bar_hash_m"]).sum()),
           "missing_mobile_bars": int((m["_merge"] == "left_only").sum()),
           "missing_windows_bars": int((m["_merge"] == "right_only").sum()),
           "identity_differences": int((both["identity_check_w"] != both["identity_check_m"]).sum())}
    if prim_rev is not None and mob_rev is not None:
        a = set(map(tuple, prim_rev[key].to_numpy().tolist()))
        b = set(map(tuple, mob_rev[key].to_numpy().tolist()))
        out["revised_only_windows"], out["revised_only_mobile"], out["revised_both"] = len(a - b), len(b - a), len(a & b)
    out["merged_into_primary"] = False
    return out
