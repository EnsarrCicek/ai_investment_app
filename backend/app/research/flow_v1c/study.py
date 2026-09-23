"""FLOW 1C dış doğrulama çalışması (AĞ YOK — yalnızca dondurulmuş dış veri).

Çalıştırma: `python -m app.research.flow_v1c.study`

Kilitli protokol: `resources/flow_v1c_protocol_v1.json`. TECHNICAL-KÖR:
Technical yalnızca kontrol/koşullandırma değişkenidir; Technical-pozitif
adayların KENDİ getiri seviyesi hiçbir yerde döndürülmez — yalnızca
reddedilen/geçen farkları ve filtreli−filtresiz farkları raporlanır.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from app.research.flow_v1 import statistics as st
from app.research.flow_v1.dataset import load_frozen_universe
from app.research.flow_v1.panel import build_panel, load_technical_baseline
from app.research.flow_v1.study import (
    FORBIDDEN_KEY_TOKENS,
    TechnicalBlindViolation,
    daily_partial_ic,
    daily_residual,
)
from app.research.flow_v1c.dataset import load_external_dataset, load_protocol
from app.research.flow_v1c.universe import load_external_universe

PRIMARY_H = 10
SECONDARY_H = (1, 5, 20)
CMF_SCALE = 0.25  # FLOW 1B araştırma ölçeği — AYARLANMADI
NEG_THRESHOLD = -20.0
TECH_POSITIVE = 15.0
MIN_GROUP = 2
MIN_Q = 50
STEP = 10
OFFSETS = tuple(range(STEP))
REBALANCE_BLOCK = 2
COSTS_BPS = (10, 20, 40)
CO_PRIMARY_CI = 97.5  # Bonferroni: 2 eş-birincil hipotez
P1_MIN_MEANINGFUL = 0.02
P2_ECONOMIC = -0.0040
MIN_P1_DATES, MIN_P2_DATES, MIN_MEDIAN_CROSS_SECTION = 500, 250, 100
MIN_POSITIVE_OFFSETS = 8

FORBIDDEN_1C_TOKENS = FORBIDDEN_KEY_TOKENS + ("unfiltered_return", "all_candidates_return", "passed_return_level",
                                              "technical_positive_return")


def assert_technical_blind_1c(obj, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(tok in str(k).lower() for tok in FORBIDDEN_1C_TOKENS):
                raise TechnicalBlindViolation(f"yasak anahtar: {path}/{k}")
            assert_technical_blind_1c(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_technical_blind_1c(v, f"{path}[{i}]")


def cmf_score(cmf20: pd.Series) -> pd.Series:
    """CMFScore = 100 * clamp(CMF20 / 0.25, -1, 1). NaN korunur."""
    return 100.0 * (cmf20 / CMF_SCALE).clip(lower=-1.0, upper=1.0)


def is_rejected(score: pd.Series) -> pd.Series:
    """Negatif-CMF filtresi: CMFScore <= -20 (sınır değeri -20 REDDEDİLİR)."""
    return score <= NEG_THRESHOLD


def enumerate_offsets(dates: list, step: int = STEP) -> dict[int, list]:
    """Offset 0..step-1'in HEPSİ; hiçbir offset seçilmez/atlanmaz."""
    return {o: list(dates[o::step]) for o in range(step)}


def summarize_offsets(per_offset: dict[int, float]) -> dict:
    """Tüm offset'lerin betimsel özeti. 'En iyi offset' alanı YOKTUR."""
    values = np.array([per_offset[o] for o in sorted(per_offset)], dtype=float)
    finite = values[np.isfinite(values)]
    return {
        "offsets_reported": sorted(per_offset),
        "values": [None if not np.isfinite(v) else float(v) for v in values],
        "mean": float(finite.mean()) if len(finite) else None,
        "median": float(np.median(finite)) if len(finite) else None,
        "min": float(finite.min()) if len(finite) else None,
        "max": float(finite.max()) if len(finite) else None,
        "n_positive": int((finite > 0).sum()),
        "n_offsets": int(len(values)),
    }


def label_p1(s: dict) -> str:
    if s.get("ci_low") is None:
        return "INCONCLUSIVE"
    if s["ci_low"] > 0:
        return "SUPPORTED"
    if s["ci_high"] < P1_MIN_MEANINGFUL or s["ci_high"] < 0:
        return "NOT_SUPPORTED"
    return "INCONCLUSIVE"


def label_p2(s: dict) -> str:
    if s.get("ci_low") is None:
        return "INCONCLUSIVE"
    if s["ci_high"] < 0:
        return "SUPPORTED"
    if s["ci_low"] > P2_ECONOMIC or s["ci_low"] > 0:
        return "NOT_SUPPORTED"
    return "INCONCLUSIVE"


# ------------------------------------------------------------------ P2 / filter


def filter_frame(panel: pd.DataFrame, target: str) -> pd.DataFrame:
    tp = panel["technical_score"] >= TECH_POSITIVE
    df = panel.loc[tp, ["date", "symbol", "cmf_score", target]].dropna()
    df = df.assign(rejected=is_rejected(df["cmf_score"]))
    return df


def p2_daily(panel: pd.DataFrame, target: str) -> dict:
    """Reddedilen − geçen (tarih-dengeli) getiri ve hit-rate farkları."""
    df = filter_frame(panel, target)
    ret, hit = {}, {}
    n_rej = n_pass = 0
    for d, g in df.groupby("date"):
        rej = g.loc[g["rejected"], target]
        pas = g.loc[~g["rejected"], target]
        if len(rej) >= MIN_GROUP and len(pas) >= MIN_GROUP:
            ret[d] = rej.mean() - pas.mean()
            hit[d] = (rej > 0).mean() - (pas > 0).mean()
            n_rej += len(rej)
            n_pass += len(pas)
    return {"ret": pd.Series(ret, dtype=float), "hit": pd.Series(hit, dtype=float),
            "rejected_observations_in_compared_dates": int(n_rej), "passed_observations_in_compared_dates": int(n_pass),
            "technical_positive_observations_with_cmf": int(len(df)),
            "rejected_share_of_technical_positive": float(df["rejected"].mean()) if len(df) else None}


def filter_rebalance_rows(panel: pd.DataFrame, target: str) -> pd.DataFrame:
    """Her uygun tarih için filtre ölçümleri (seviyeler yalnızca iç hesap)."""
    df = filter_frame(panel, target)
    rows = []
    for d, g in df.groupby("date"):
        passed = g.loc[~g["rejected"]]
        if len(g) < 1 or len(passed) < 1:
            continue
        rejected = g.loc[g["rejected"]]
        rows.append({
            "date": d,
            "improvement": passed[target].mean() - g[target].mean(),
            "rejected_minus_passed": (rejected[target].mean() - passed[target].mean()) if len(rejected) else np.nan,
            "passed_names": frozenset(passed["symbol"]),
            "all_names": frozenset(g["symbol"]),
            "_passed_mean": passed[target].mean(),
            "_all_mean": g[target].mean(),
            "n_all": len(g),
            "n_rejected": len(rejected),
        })
    return pd.DataFrame(rows).set_index("date").sort_index()


def filter_offset_study(rows: pd.DataFrame) -> dict:
    offsets = enumerate_offsets(list(rows.index))
    per = {}
    for o, dates in offsets.items():
        sub = rows.loc[dates]
        to_p, to_a = [], []
        prev_p = prev_a = None
        for _, r in sub.iterrows():
            to_p.append(1.0 if prev_p is None else 1.0 - len(r["passed_names"] & prev_p) / len(r["passed_names"]))
            to_a.append(1.0 if prev_a is None else 1.0 - len(r["all_names"] & prev_a) / len(r["all_names"]))
            prev_p, prev_a = r["passed_names"], r["all_names"]
        to_p, to_a = np.array(to_p), np.array(to_a)
        entry = {
            "rebalance_dates": int(len(sub)),
            "gross_improvement": st.summarize_series(sub["improvement"], 1, block_length=REBALANCE_BLOCK),
            "rejected_minus_passed": st.summarize_series(sub["rejected_minus_passed"], 1, block_length=REBALANCE_BLOCK),
            "mean_turnover_passed": float(to_p.mean()),
            "mean_turnover_all": float(to_a.mean()),
            "mean_candidates": float(sub["n_all"].mean()),
            "mean_rejected": float(sub["n_rejected"].mean()),
        }
        for c in COSTS_BPS:
            cost = c / 10_000.0
            net = (sub["_passed_mean"] - cost * to_p) - (sub["_all_mean"] - cost * to_a)
            entry[f"net_improvement_{c}bps"] = st.summarize_series(net, 1, block_length=REBALANCE_BLOCK)
        per[o] = entry
    across = {
        "gross_improvement": summarize_offsets({o: v["gross_improvement"]["mean"] for o, v in per.items()}),
        "rejected_minus_passed": summarize_offsets({o: v["rejected_minus_passed"]["mean"] for o, v in per.items()}),
    }
    for c in COSTS_BPS:
        across[f"net_improvement_{c}bps"] = summarize_offsets({o: v[f"net_improvement_{c}bps"]["mean"] for o, v in per.items()})
    across["all_dates_overlapping_gross_improvement"] = st.summarize_series(rows["improvement"], PRIMARY_H)
    across["all_dates_overlapping_rejected_minus_passed"] = st.summarize_series(rows["rejected_minus_passed"], PRIMARY_H)
    return {"per_offset": {str(o): v for o, v in per.items()}, "across_offsets": across}


def residual_long_short_offsets(panel: pd.DataFrame, target: str) -> dict:
    """İkincil: Technical'a göre artıklaştırılmış CMF Q5−Q1, tüm 10 offset."""
    df = panel[["date", "symbol", target]].copy()
    df["_s"] = panel["cmf20_resid_tech"]
    df = df.dropna()
    rows = []
    for d, g in df.groupby("date"):
        if len(g) < MIN_Q:
            continue
        q = st.assign_quintiles(g["_s"])
        rows.append({"date": d, "ls": g.loc[q == 5, target].mean() - g.loc[q == 1, target].mean(),
                     "long": frozenset(g.loc[q == 5, "symbol"]), "short": frozenset(g.loc[q == 1, "symbol"])})
    frame = pd.DataFrame(rows).set_index("date").sort_index()
    per = {}
    for o, dates in enumerate_offsets(list(frame.index)).items():
        sub = frame.loc[dates]
        tl, ts, pl, ps = [], [], None, None
        for _, r in sub.iterrows():
            tl.append(1.0 if pl is None else 1.0 - len(r["long"] & pl) / len(r["long"]))
            ts.append(1.0 if ps is None else 1.0 - len(r["short"] & ps) / len(r["short"]))
            pl, ps = r["long"], r["short"]
        entry = {"rebalance_dates": int(len(sub)), "gross": float(sub["ls"].mean())}
        for c in COSTS_BPS:
            entry[f"net_{c}bps"] = float((sub["ls"] - c / 10_000.0 * (np.array(tl) + np.array(ts))).mean())
        per[o] = entry
    out = {"per_offset": {str(o): v for o, v in per.items()},
           "all_dates_overlapping_gross": st.summarize_series(frame["ls"], PRIMARY_H)}
    for key in ["gross", *[f"net_{c}bps" for c in COSTS_BPS]]:
        out[f"across_{key}"] = summarize_offsets({o: v[key] for o, v in per.items()})
    return out


# ------------------------------------------------------------------ run


def run_study() -> dict:
    protocol, protocol_sha = load_protocol()
    symbols, universe = load_external_universe()
    frames, manifest = load_external_dataset()
    baseline = load_technical_baseline()
    freeze_now = datetime.fromisoformat(manifest["freeze_now_utc"])
    panel, qualities, build_info = build_panel(frames, freeze_now, baseline)
    panel = panel.assign(cmf_score=cmf_score(panel["cmf20"]))
    panel = panel.assign(cmf20_resid_tech=daily_residual(panel, "cmf20", ["technical_score"]))
    target = f"ex_{PRIMARY_H}"

    discovery_symbols, _ = load_frozen_universe()
    discovery_overlap = sorted(set(panel["symbol"]) & set(discovery_symbols))
    if discovery_overlap:
        raise ValueError(f"dış panel keşif evreniyle kesişiyor: {discovery_overlap}")
    fetch_failed = sorted(s for s, e in manifest["symbols"].items() if e["status"] != "OK")
    cs_sizes = panel[["date", "cmf20", "technical_score", target]].dropna().groupby("date").size()

    results: dict = {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol_sha,
        "dataset_sha256": manifest["dataset_sha256"],
        "external_symbols_sha256": universe["external_symbols_sha256"],
        "technical_baseline": {k: v for k, v in baseline.items() if k not in ("weights", "family_weights")},
        "technical_blinding": "TECHNICAL_BLIND",
        "build_info": build_info,
        "sample": {
            "universe_size": len(symbols),
            "fetch_failed": fetch_failed,
            "symbols_with_observations": int(panel["symbol"].nunique()),
            "discovery_overlap_in_panel": discovery_overlap,
            "panel_rows": int(len(panel)),
            "first_observation_date": panel["date"].min().date().isoformat(),
            "last_observation_date": panel["date"].max().date().isoformat(),
            "distinct_observation_dates": int(panel["date"].nunique()),
            "primary_complete_rows": int(panel[["cmf20", "technical_score", target]].dropna().shape[0]),
            "p1_cross_section_median": float(cs_sizes.median()),
            "p1_cross_section_min": int(cs_sizes.min()),
            "p1_cross_section_max": int(cs_sizes.max()),
            "per_symbol_observations": {s: int(n) for s, n in panel.groupby("symbol").size().items()},
        },
        "quality": [q.__dict__ for q in qualities],
    }

    # ---- P1
    p1_series = daily_partial_ic(panel, "cmf20", ["technical_score"], target)
    p1 = st.summarize_series(p1_series, PRIMARY_H, ci_level=CO_PRIMARY_CI)
    results["P1"] = {**p1, "label": label_p1(p1), "ci95_reference": st.summarize_series(p1_series, PRIMARY_H)}

    # ---- P2
    p2raw = p2_daily(panel, target)
    p2 = st.summarize_series(p2raw["ret"], PRIMARY_H, ci_level=CO_PRIMARY_CI)
    results["P2"] = {
        "return_delta": p2,
        "hit_rate_delta_pp": st.summarize_series(p2raw["hit"], PRIMARY_H, scale=100.0, ci_level=CO_PRIMARY_CI),
        "label": label_p2(p2),
        "economically_meaningful": p2["mean"] is not None and p2["mean"] <= P2_ECONOMIC,
        **{k: v for k, v in p2raw.items() if k not in ("ret", "hit")},
    }

    # ---- filtre offset'leri ve ikincil artık L−S offset'leri
    rows = filter_rebalance_rows(panel, target)
    results["filter_offsets"] = filter_offset_study(rows)
    results["residual_long_short_offsets"] = residual_long_short_offsets(panel, target)

    # ---- ikincil
    secondary = {"cmf20_partial_ic": {}, "pvfs_partial_ic": {}, "cmf_minus_pvfs_partial_ic": {}}
    for h in (*SECONDARY_H, PRIMARY_H):
        c = daily_partial_ic(panel, "cmf20", ["technical_score"], f"ex_{h}")
        p = daily_partial_ic(panel, "pvfs", ["technical_score"], f"ex_{h}")
        secondary["cmf20_partial_ic"][str(h)] = st.summarize_series(c, h)
        secondary["pvfs_partial_ic"][str(h)] = st.summarize_series(p, h)
        secondary["cmf_minus_pvfs_partial_ic"][str(h)] = st.summarize_series((c - p).dropna(), h)
    years = {}
    p2_ret = p2raw["ret"]
    for y in sorted(set(p1_series.index.year)):
        a = p1_series[p1_series.index.year == y]
        b = p2_ret[p2_ret.index.year == y]
        years[str(y)] = {"p1_n_dates": int(len(a)), "p1_mean": float(a.mean()),
                         "p1_nw_t": st.newey_west_t(a.to_numpy(float), PRIMARY_H),
                         "p2_n_dates": int(len(b)), "p2_mean": float(b.mean()) if len(b) else None}
    secondary["by_year"] = years
    liq = panel.groupby("date")["turnover20"].rank(pct=True) > 0.2
    liquid = panel[liq]
    secondary["liquidity_excl_bottom_quintile"] = {
        "p1": st.summarize_series(daily_partial_ic(liquid, "cmf20", ["technical_score"], target), PRIMARY_H),
        "p2": st.summarize_series(p2_daily(liquid, target)["ret"], PRIMARY_H),
        "excluded_observations": int((~liq).sum()),
    }
    results["secondary"] = secondary

    results["gate"] = evaluate_gate(results)
    assert_technical_blind_1c(results)
    return results


def evaluate_gate(r: dict) -> dict:
    p1, p2 = r["P1"], r["P2"]
    net20 = r["filter_offsets"]["across_offsets"]["net_improvement_20bps"]
    offsets_ok = net20["n_positive"] >= MIN_POSITIVE_OFFSETS
    sample_ok = (p1["n_dates"] >= MIN_P1_DATES and p2["return_delta"]["n_dates"] >= MIN_P2_DATES
                 and r["sample"]["p1_cross_section_median"] >= MIN_MEDIAN_CROSS_SECTION)
    if p1["label"] == "SUPPORTED" and p2["label"] == "SUPPORTED" and p2["economically_meaningful"] and offsets_ok and sample_ok:
        decision = "DEVAM"
    elif p1["label"] == "NOT_SUPPORTED" and p2["label"] == "NOT_SUPPORTED":
        decision = "DUR"
    else:
        decision = "BELIRSIZ"
    return {"decision": decision, "p1_label": p1["label"], "p2_label": p2["label"],
            "p2_economically_meaningful": p2["economically_meaningful"],
            "net20_positive_offsets": net20["n_positive"], "offset_condition_met": offsets_ok,
            "sample_condition_met": sample_ok}


def main() -> None:
    from app.research.flow_v1c.report import write_results

    results = run_study()
    write_results(results)
    print(results["gate"])


if __name__ == "__main__":
    main()
