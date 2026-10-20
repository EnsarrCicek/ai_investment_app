"""Başarısız untouched final — postmortem (YALNIZ açıklayıcı; aday/eşik SEÇİLMEZ).

Tüketilmiş final dilim (37 varlık × 28.09–15.10) burada yalnız "research feedback" olarak okunur. Aday seçimi
bağlamında (`audit.candidate_selection`) açılması RuntimeError verir. Karşı-olgusal kollar ÖNCEDEN sabit:
gecikme 0/5/10/11/15 dk, eşik ×0.9/×0.8/×0.7, hacim kapısı zayıf/orta/güçlü/R1-katılım. Hiçbiri "en iyi" diye
seçilmez; dondurulmuş final kararı yeniden hesaplanmaz.

Kullanım:
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final.postmortem
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np

from app.research.momentum_calibration import dataset as r1ds
from app.research.momentum_feasibility import audit as au
from app.research.momentum_feasibility import experiment as fx
from app.research.momentum_feasibility import frontier as fr
from app.research.momentum_final import candidate as cd
from app.research.momentum_final import experiment as mf
from app.research.momentum_round2 import dataset as ds2
from app.research.momentum_round2 import experiment as r2

RESULT = mf.HERE / "postmortem_result.json"
DELAYS = (0, 5, 10, 11, 15)  # 11 = 1 dk bar tamamlanma vekili (15 dk gecikmede ≤4 dk kazanç)
THRESHOLD_FACTORS = (1.0, 0.9, 0.8, 0.7)
SLIGHT_THRESHOLD = 0.8  # "eşik biraz düşseydi" karşı-olgusu (önceden sabit)
VOLUME_GATES = {"no_gate": None, "weak_relvol3_ge_1.0": ("relvol_3", 1.0), "medium_relvol3_ge_1.5": ("relvol_3", 1.5),
                "strong_relvol3_ge_2.0": ("relvol_3", 2.0), "r1_participation_volume_anomaly_ge_0.5":
                ("volume_anomaly", 0.5)}
CATEGORIES = ("LATENCY_LIMITED", "BAR_RESOLUTION_LIMITED", "THRESHOLD_LIMITED", "MISSING_INFORMATION",
              "INTRINSICALLY_UNPREDICTABLE", "MIXED")


def open_consumed_final() -> list[dict]:
    """Tüketilmiş final satırları (yalnız postmortem). Aday seçimi bağlamında yasak."""
    if au.selection_active():
        raise RuntimeError(au.CONSUMED_FINAL_ERROR)
    assert ds2.CONSUMED_FINAL and mf.FINAL_RESULT.exists(), "final tüketilmeden postmortem yok"
    _, final_days = fx.selection_scope()
    return [r for r in r2.load_pkl("merged_new_d15.pkl") if r["day"] in final_days]


# ------------------------------------------------------------------ saf sınıflayıcılar
def counterfactual_category(*, intrinsic: bool, caught_1m: bool, caught_d0: bool, caught_lower_thr: bool,
                            caught_d0_lower_thr: bool) -> str:
    """Öncelik: fiziksel imkânsızlık → en küçük değişiklikle kurtulan → birlikte kurtulan → bilgi eksik."""
    if intrinsic:
        return "INTRINSICALLY_UNPREDICTABLE"
    if caught_1m:
        return "BAR_RESOLUTION_LIMITED"
    if caught_d0 and caught_lower_thr:
        return "MIXED"
    if caught_d0:
        return "LATENCY_LIMITED"
    if caught_lower_thr:
        return "THRESHOLD_LIMITED"
    if caught_d0_lower_thr:
        return "MIXED"
    return "MISSING_INFORMATION"


def bar_resolution_bucket(evidence_to_peak_min: float | None) -> str:
    if evidence_to_peak_min is None:
        return "NO_USABLE_EVIDENCE"
    if evidence_to_peak_min < 4:
        return "LT_4MIN_1M_INSUFFICIENT"
    if evidence_to_peak_min <= 15:
        return "4_15MIN_1M_POTENTIALLY_USEFUL"
    return "GT_15MIN_NOT_BAR_LIMITED"


def gate_effect(base_fp: set, base_caught: set, base_early: set, fp: set, caught: set, early: set) -> dict:
    return {"fp_removed": len(base_fp - fp), "fp_removed_share": len(base_fp - fp) / len(base_fp) if base_fp else None,
            "caught_lost": len(base_caught - caught),
            "caught_lost_share": len(base_caught - caught) / len(base_caught) if base_caught else None,
            "early_lost": len(base_early - early),
            "early_lost_share": len(base_early - early) / len(base_early) if base_early else None}


# ------------------------------------------------------------------ yardımcılar
def _min(ns, ref):
    return None if ns is None else (ns - ref) / au.MIN_NS


def session_sets(p, alerts: np.ndarray, delay: int) -> tuple[set, set, set]:
    """(YP seansları, tepe öncesi yakalanan olaylar, erken (lead<0.5) yakalanan olaylar) — ilk alarm tanımıyla."""
    lab = p.labels[delay]
    uniq, rows = fr.first_alert_rows(alerts, p.sess)
    fp, caught, early = set(), set(), set()
    for s, i in zip(uniq, rows):
        if not lab.sess_event[s]:
            fp.add(int(s))
            continue
        if lab.t_ns[i] <= lab.sess_high_ns[s]:
            caught.add(int(s))
            lf = au.lead_fraction(lab.entry[i], lab.sess_run_low[s], lab.sess_high[s])
            if lf is not None and lf < au.LEAD_TARGET:
                early.add(int(s))
    return fp, caught, early


def rule(p, cand: dict, factor: float = 1.0, gate=None) -> np.ndarray:
    vals = getattr(p, cand["feature"])
    m = p.ok & np.isfinite(vals) & (vals >= cand["threshold"] * factor)
    if gate is not None:
        g = getattr(p, gate[0])
        m &= np.isfinite(g) & (g >= gate[1])
    return m


def half_window_min(sym, day, ms_ns: int, lab, s) -> float:
    """Hareket başlangıç barından, yükselişin yarısına (dip + %50 açıklık) ulaşan ilk barın başlangıcına dakika."""
    bars = r1ds.load(sym).bars
    d = bars[bars.index.date == day].dropna()
    mid = lab.sess_run_low[s] + 0.5 * (lab.sess_high[s] - lab.sess_run_low[s])
    t = d.index.as_unit("ns").asi8  # birim bağımsız ns
    hit = np.flatnonzero((t >= ms_ns) & (d["High"].to_numpy() >= mid))
    return (int(t[hit[0]]) - ms_ns) / au.MIN_NS if len(hit) else None


def missed_event_analysis(p, cand: dict) -> list[dict]:
    lab15 = p.labels[15]
    info = p.t15_ns - 15 * au.MIN_NS
    leads = {d: fx._session_arrays(p, d) for d in DELAYS}
    base = rule(p, cand)
    lower = rule(p, cand, SLIGHT_THRESHOLD)
    seg = defaultdict(list)
    for i, s in enumerate(p.sess):
        seg[s].append(i)
    out = []
    for s in np.flatnonzero(lab15.sess_event):
        idx = np.array(seg[s])
        sym, day = p.sessions[s]
        ms, peak = fx._move_start_ns(sym, day), int(lab15.sess_high_ns[s])
        mv = idx[info[idx] > ms]

        def early(mask, d):
            lead, before = leads[d]
            return bool((mask[mv] & before[mv] & (lead[mv] < au.LEAD_TARGET)).any())
        if early(base, 15):
            continue  # finalde erken yakalandı
        okr = mv[p.ok[mv]]

        def first(mask):
            hit = mv[mask[mv]]
            return int(info[hit[0]]) if len(hit) else None
        pe = first(p.ok & (p.price_impulse >= fx.THR))
        sig = first(base)
        # kullanılabilir kanıt: barı tepeden ÖNCE başlamış ilk fiyat kanıtı / aday sinyali
        usable = min([t for t in (pe, sig) if t is not None and t - 5 * au.MIN_NS < peak], default=None)
        # Final taksonomisiyle aynı birincil neden (d15 bilgisi)
        lead15, before15 = leads[15]
        e15 = mv[before15[mv] & (lead15[mv] < au.LEAD_TARGET)]
        e15ok = e15[p.ok[e15]]
        price_ev = e15ok[p.price_impulse[e15ok] >= fx.THR]
        win = mv[before15[mv]]
        gate_flag = bool((np.nan_to_num(p.ret_z_3[e15ok], nan=-9) >= cand["threshold"]).any()
                         and not (np.nan_to_num(p.rel_ret_z_3[e15ok], nan=-9) >= cand["threshold"]).any())
        flags = {"BASELINE_UNAVAILABLE": len(win) > 0 and not (p.ok[win] & np.isfinite(p.rel_ret_z_3[win])).any(),
                 "ABRUPT_VERTICAL_JUMP": (peak - ms) / au.MIN_NS <= 15,
                 "NO_EARLY_PRICE_EVIDENCE": len(price_ev) == 0, "BENCHMARK/CROSS_SECTION_GATE": gate_flag}
        flags["FEATURE_THRESHOLD"] = len(price_ev) > 0 and not gate_flag
        primary, _ = au.classify_fn(flags)
        hw = half_window_min(sym, day, ms, lab15, s)
        intrinsic = hw is not None and hw < 5  # yükselişin yarısı hareketin İLK 5 dk barı içinde
        cf = {"caught_d0": early(base, 0), "caught_d5": early(base, 5), "caught_d10": early(base, 10),
              "caught_1m_proxy_d11": early(base, 11), "caught_thr_x0.8_d15": early(lower, 15),
              "caught_thr_x0.8_d0": early(lower, 0)}
        cat = counterfactual_category(intrinsic=intrinsic, caught_1m=cf["caught_1m_proxy_d11"],
                                      caught_d0=cf["caught_d0"], caught_lower_thr=cf["caught_thr_x0.8_d15"],
                                      caught_d0_lower_thr=cf["caught_thr_x0.8_d0"])
        sub = None
        if cat == "MISSING_INFORMATION":
            sub = ("EARLY_PRICE_EVIDENCE_BUT_RULE_MISMATCH" if len(price_ev)
                   else "NO_EARLY_PRICE_SIGNAL")
        out.append({"symbol": sym, "day": str(day), "primary": primary, "subcategory": sub,
                    "runup_pct": (lab15.sess_high[s] / lab15.sess_run_low[s] - 1) * 100,
                    "rise_min": (peak - ms) / au.MIN_NS, "half_window_min": hw,
                    "first_price_evidence_min": _min(pe, ms),
                    "first_volume_evidence_min": _min(first(p.ok & (p.volume_anomaly >= fx.THR)), ms),
                    "first_rel_strength_min": _min(first(p.ok & (p.rel_ret_z_3 >= 1.0)), ms),
                    "first_raw_signal_min": _min(sig, ms),
                    "provider_visible_min": None if sig is None else _min(sig, ms) + 15,
                    "max_rel_ret_z_3_before_peak": (float(np.nanmax(p.rel_ret_z_3[win])) if len(win) and
                                                    np.isfinite(p.rel_ret_z_3[win]).any() else None),
                    "evidence_to_peak_min": None if usable is None else (peak - (usable - 5 * au.MIN_NS)) / au.MIN_NS,
                    "bar_bucket": bar_resolution_bucket(None if usable is None else
                                                        (peak - (usable - 5 * au.MIN_NS)) / au.MIN_NS),
                    "counterfactual": cf, "category": cat, "intrinsic": intrinsic, "n_ok_rows_before_peak":
                    int(len(okr))})
    return out


def _med(vals):
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return float(np.median(v)) if v else None


def group_summary(events: list[dict], key: str) -> dict:
    out = {}
    for g in sorted({e[key] for e in events}):
        es = [e for e in events if e[key] == g]
        out[g] = {"count": len(es), "share": len(es) / len(events),
                  **{f"median_{k}": _med([e[k] for e in es]) for k in
                     ("runup_pct", "rise_min", "half_window_min", "first_price_evidence_min",
                      "first_volume_evidence_min", "first_rel_strength_min", "first_raw_signal_min",
                      "provider_visible_min", "max_rel_ret_z_3_before_peak", "evidence_to_peak_min")},
                  "share_with_price_evidence": sum(e["first_price_evidence_min"] is not None for e in es) / len(es),
                  "share_with_volume_evidence": sum(e["first_volume_evidence_min"] is not None for e in es) / len(es)}
    return out


def fp_decomposition(p, cand: dict) -> dict:
    lab = p.labels[15]
    alerts = rule(p, cand)
    uniq, rows = fr.first_alert_rows(alerts, p.sess)
    tax = fx.fp_taxonomy_v2(p, alerts, 15)
    # kategori başına satır profilleri (fp_taxonomy_v2 ile aynı birincil sınıf)
    per = defaultdict(list)
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
                            accel_next_min=nxt_acc, visible_minute=minute, evidence_threshold=fx.THR, x=fx.X)
        per[au.classify_fp(flags)[0]].append({"relvol_3": p.relvol_3[i], "volume_anomaly": p.volume_anomaly[i],
                                             "price_z": p.price_z[i], "rel_ret_z_3": p.rel_ret_z_3[i],
                                             "accel": p.accel[i], "future_mfe_close": lab.mfe_close[i],
                                             "alert_minute": minute})
    prof = {k: {"count": len(v), **{f"median_{f}": _med([r[f] for r in v]) for f in v[0]},
                "alert_time_median": fx._hm(_med([r["alert_minute"] for r in v]))} for k, v in per.items()}
    return {"fp_sessions": tax["fp_sessions"], "primary_share": {k: v["share"] for k, v in tax["primary"].items()},
            "profiles": prof}


def volume_gate_table(p, cand: dict) -> dict:
    base_fp, base_c, base_e = session_sets(p, rule(p, cand), 15)
    psnv = set()  # PRICE_SPIKE_NO_VOLUME birincil YP seansları
    lab = p.labels[15]
    uniq, rows = fr.first_alert_rows(rule(p, cand), p.sess)
    for s, i in zip(uniq, rows):
        if not lab.sess_event[s] and not p.locked[i] and not np.isnan(p.volume_anomaly[i]) and not p.regime_shock[i] \
                and not (np.isfinite(p.rel_ret_z_3[i]) and p.rel_ret_z_3[i] < 1.0) \
                and np.nan_to_num(p.volume_anomaly[i]) < fx.THR:
            psnv.add(int(s))  # yaklaşık (gap/breakout öncelik sırası dışında); yalnız açıklayıcı
    out = {}
    for name, gate in VOLUME_GATES.items():
        a = rule(p, cand, gate=gate)
        fp, c, e = session_sets(p, a, 15)
        m = fr.metrics(a, p.sess, lab, fx.X)
        out[name] = {**gate_effect(base_fp, base_c, base_e, fp, c, e),
                     "price_spike_no_volume_fp_removed": len(psnv - fp), "price_spike_no_volume_fp": len(psnv),
                     **{k: m[k] for k in ("precision", "recall", "false_positive_rate", "lead_fraction_median",
                                          "alert_sessions")}}
    return out


def delay_table(p, cand: dict) -> dict:
    out = {}
    for factor in THRESHOLD_FACTORS:
        a = rule(p, cand, factor)
        out[f"x{factor}"] = {d: {k: fr.metrics(a, p.sess, p.labels[d], fx.X)[k] for k in
                                 ("precision", "recall", "false_positive_rate", "lead_fraction_median",
                                  "median_first_alert_minute", "caught_events", "alert_sessions")}
                             for d in DELAYS}
    return out


def ktlev_postmortem(cand: dict) -> dict:
    rows = [r for r in r2.load_pkl("merged_ktlev_d15.pkl") if str(r["day"]) == "2026-10-08"]
    k = fx.Panel(rows)
    for d in (0, 11, 15):
        k.build_labels(d)
    lab = k.labels[15]
    info = k.t15_ns - 15 * au.MIN_NS
    ms, peak = fx._move_start_ns("KTLEV", rows[0]["day"]), int(lab.sess_high_ns[0])
    after = info > ms
    sig = rule(k, cand)

    def first(mask):
        hit = np.flatnonzero(mask & after)
        return None if not len(hit) else int(hit[0])

    def at(i, d):
        if i is None:
            return None
        L = k.labels[d]
        return {"visible": fx._hhmm(L.t_ns[i]), "before_peak": bool(L.t_ns[i] <= peak),
                "lead_fraction": au.lead_fraction(L.entry[i], L.sess_run_low[0], L.sess_high[0])}
    i_sig = first(sig)

    def hh(i):
        return None if i is None else fx._hhmm(info[i])
    tl = {"move_start": fx._hhmm(ms), "peak": fx._hhmm(peak),
          "first_acceleration": hh(first(k.ok & (k.accel >= 0.5) & (k.accel_pos_3 >= 2))),
          "first_relative_strength": hh(first(k.ok & (k.rel_ret_z_3 >= 1.0))),
          "first_price_evidence": hh(first(k.ok & (k.price_impulse >= fx.THR))),
          "first_candidate_signal_info": hh(i_sig),
          "candidate_signal_value": float(k.rel_ret_z_3[i_sig]) if i_sig is not None else None}
    lower = first(rule(k, cand, SLIGHT_THRESHOLD))
    rel_path = [{"info": fx._hhmm(info[i]), "rel_ret_z_3": round(float(k.rel_ret_z_3[i]), 2),
                 "price_impulse": round(float(k.price_impulse[i]), 2), "volume_anomaly":
                 round(float(np.nan_to_num(k.volume_anomaly[i])), 2)}
                for i in np.flatnonzero(after & (info >= peak - 40 * au.MIN_NS) & (info <= peak + 10 * au.MIN_NS))]
    return {"used_for_tuning": False, "timeline": tl,
            "candidate_d0": at(i_sig, 0), "candidate_1m_proxy_d11": at(i_sig, 11), "candidate_d15": at(i_sig, 15),
            "lower_threshold_x0.8_d0": at(lower, 0), "lower_threshold_x0.8_d15": at(lower, 15),
            "path_last_40min": rel_path}


def main():
    with_sel = au.selection_active()
    assert not with_sel
    cand = cd.load_frozen(mf.MANIFEST)["candidate"]
    final = json.loads(mf.FINAL_RESULT.read_text(encoding="utf-8"))
    assert final["sha256"] == cd.sha256_of(cand) == ds2.CONSUMED_FINAL_SHA
    p = fx.Panel(open_consumed_final())
    for d in DELAYS:
        p.build_labels(d)
    events = missed_event_analysis(p, cand)
    out = {
        "consumed_final": True, "candidate_sha256": final["sha256"], "used_for_selection": False,
        "frozen_final_recap": {k: final["watch"][k] for k in ("precision", "recall", "false_positive_rate",
                                                              "lead_fraction_median", "alert_sessions")}
        | {"verdict": final["verdict"]},
        "missed_events": len(events),
        "missed_by_primary": group_summary(events, "primary"),
        "missed_by_counterfactual_category": group_summary(events, "category"),
        "counterfactual_counts": {k: sum(e["counterfactual"][k] for e in events) for k in events[0]["counterfactual"]},
        "missing_information_split": dict(Counter(e["subcategory"] for e in events if e["subcategory"])),
        "bar_resolution": dict(Counter(e["bar_bucket"] for e in events)),
        "bar_resolution_by_category": {c: dict(Counter(e["bar_bucket"] for e in events if e["category"] == c))
                                       for c in CATEGORIES},
        "events": events,
        "fp": fp_decomposition(p, cand),
        "volume_gate": volume_gate_table(p, cand),
        "delay_threshold_counterfactual": delay_table(p, cand),
        "ktlev": ktlev_postmortem(cand),
    }
    RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "events"}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
