"""TECH-VOL 1A çalışma — AĞ YOK; FLOW 1C dondurulmuş verisi + yerel
production-state tablosu.

Çalıştırma: `python -m app.research.technical_volume_audit.study`

TECHNICAL-KÖR: yalnızca AYNI Technical durumu içindeki yüksek-hacim −
yüksek-olmayan-hacim farkları, seçili−tümü farkları ve log(RV20) partial IC
raporlanır. Hiçbir Technical/sinyal-sınıfı grubunun kendi getiri seviyesi
döndürülmez.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from app.research.flow_v1 import statistics as st
from app.research.flow_v1.dataset import load_frozen_universe
from app.research.flow_v1.panel import build_panel, load_technical_baseline
from app.research.flow_v1.study import TechnicalBlindViolation, daily_partial_ic
from app.research.flow_v1c.dataset import load_external_dataset
from app.research.flow_v1c.study import COSTS_BPS, enumerate_offsets, summarize_offsets
from app.research.flow_v1c.universe import load_external_universe
from app.research.technical_volume_audit.states import (
    HIGH_VOLUME_RATIO,
    load_verified_states,
    price_direction,
    spike_or_sustained,
)

PROTOCOL_FILE_NAME = "tech_vol_1a_protocol_v1.json"
PRIMARY_H = 10
SECONDARY_H = (1, 5, 20)
TECH_POS, TECH_NEG = 15.0, -15.0
MIN_GROUP = 2
MIN_IC = 20
REBALANCE_BLOCK = 2
REDUNDANT_DELTA_BAND = 0.0025
REDUNDANT_IC_BAND = 0.01
FORBIDDEN_TOKENS = ("technical_ic", "technical_hit", "technical_return", "signal_class_return",
                    "tech_positive_mean", "technical_positive_return", "strong_return", "all_return_level")


def load_protocol() -> tuple[dict, str]:
    import json

    from app.research.canonical_hash import content_sha256
    from app.research.flow_v1c.dataset import FLOW_V1C_DIR

    protocol = json.loads((FLOW_V1C_DIR.parent / "resources" / PROTOCOL_FILE_NAME).read_text(encoding="utf-8"))
    return protocol, content_sha256(protocol)


def assert_blind(obj, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(tok in str(k).lower() for tok in FORBIDDEN_TOKENS):
                raise TechnicalBlindViolation(f"yasak anahtar: {path}/{k}")
            assert_blind(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_blind(v, f"{path}[{i}]")


def tech_state(score: pd.Series) -> pd.Series:
    return pd.Series(np.select([score >= TECH_POS, score <= TECH_NEG], ["POS", "NEG"], "NEU"), index=score.index)


def group_delta(df: pd.DataFrame, group: pd.Series, comp: pd.Series, target: str, h: int) -> dict:
    """Tarih-dengeli fark: her tarihte mean(group) − mean(comp) (her biri ≥2)."""
    sub = df.loc[group | comp, ["date", target]].copy()
    sub["_g"] = group[group | comp]
    sub = sub.dropna(subset=[target])
    ret, hit, ng, nc = {}, {}, 0, 0
    for d, g in sub.groupby("date"):
        a, b = g.loc[g["_g"], target], g.loc[~g["_g"], target]
        if len(a) >= MIN_GROUP and len(b) >= MIN_GROUP:
            ret[d] = a.mean() - b.mean()
            hit[d] = (a > 0).mean() - (b > 0).mean()
            ng += len(a)
            nc += len(b)
    return {"return_delta": st.summarize_series(pd.Series(ret, dtype=float), h),
            "hit_rate_delta_pp": st.summarize_series(pd.Series(hit, dtype=float), h, scale=100.0),
            "group_observations": int(ng), "comparison_observations": int(nc),
            "group_total": int(group.sum()), "comparison_total": int(comp.sum()),
            "_series": pd.Series(ret, dtype=float)}


def direction_delta(df: pd.DataFrame, direction: str, target: str, h: int) -> dict:
    """Aynı fiyat yönü içinde yüksek − yüksek-olmayan; her tarihte mevcut
    Technical durumları (POS/NEU/NEG) üzerinden ortalama."""
    sub = df[(df["direction"] == direction) & df["high"].notna()].dropna(subset=[target])
    per_date, ng, nc = {}, 0, 0
    for d, g in sub.groupby("date"):
        vals = []
        for _, gs in g.groupby("tech_state"):
            a, b = gs.loc[gs["high"] == True, target], gs.loc[gs["high"] == False, target]  # noqa: E712
            if len(a) >= MIN_GROUP and len(b) >= MIN_GROUP:
                vals.append(a.mean() - b.mean())
                ng += len(a)
                nc += len(b)
        if vals:
            per_date[d] = float(np.mean(vals))
    s = pd.Series(per_date, dtype=float)
    return {"return_delta": st.summarize_series(s, h), "group_observations": int(ng),
            "comparison_observations": int(nc), "_series": s}


def selection_offsets(df: pd.DataFrame, context: pd.Series, selected: pd.Series, target: str) -> dict:
    """Bağlam içinde seçili (yüksek hacim) − tüm bağlam; 10 offset + maliyet."""
    sub = df.loc[context, ["date", "symbol", target]].copy()
    sub["_sel"] = selected[context]
    sub = sub.dropna(subset=[target])
    rows = []
    for d, g in sub.groupby("date"):
        sel = g[g["_sel"] == True]  # noqa: E712
        if len(sel) < 1:
            continue
        rows.append({"date": d, "improvement": sel[target].mean() - g[target].mean(),
                     "sel_names": frozenset(sel["symbol"]), "all_names": frozenset(g["symbol"]),
                     "_sel_mean": sel[target].mean(), "_all_mean": g[target].mean()})
    frame = pd.DataFrame(rows).set_index("date").sort_index()
    overall = st.summarize_series(frame["improvement"], PRIMARY_H)
    per = {}
    for o, dates in enumerate_offsets(list(frame.index)).items():
        part = frame.loc[dates]
        ts, ta, ps, pa = [], [], None, None
        for _, r in part.iterrows():
            ts.append(1.0 if ps is None else 1.0 - len(r["sel_names"] & ps) / len(r["sel_names"]))
            ta.append(1.0 if pa is None else 1.0 - len(r["all_names"] & pa) / len(r["all_names"]))
            ps, pa = r["sel_names"], r["all_names"]
        ts, ta = np.array(ts), np.array(ta)
        entry = {"rebalance_dates": int(len(part)), "gross": float(part["improvement"].mean())}
        for c in COSTS_BPS:
            net = (part["_sel_mean"] - c / 1e4 * ts) - (part["_all_mean"] - c / 1e4 * ta)
            entry[f"net_{c}bps"] = float(net.mean())
        per[str(o)] = entry
    out = {"eligible_dates": int(len(frame)), "all_dates_overlapping": overall, "per_offset": per}
    sign = np.sign(overall["mean"]) if overall["mean"] else 0
    for key in ["gross", *[f"net_{c}bps" for c in COSTS_BPS]]:
        summ = summarize_offsets({int(o): v[key] for o, v in per.items()})
        summ["n_same_sign_as_overall"] = int(sum(1 for v in summ["values"] if v is not None and np.sign(v) == sign))
        out[f"across_{key}"] = summ
    return out


def classify(primary: dict, key_diag: dict, bearish_holm_p: float | None, bearish_mean: float | None) -> str:
    lo, hi = primary["ci_low"], primary["ci_high"]
    if hi is not None and hi < 0:
        return "HARMFUL"
    if lo is not None and lo > 0:
        if bearish_holm_p is not None and bearish_holm_p < 0.05 and bearish_mean is not None and bearish_mean < 0:
            return "DIRECTION-CONDITIONAL"
        return "SUPPORTED"
    if (lo is not None and -REDUNDANT_DELTA_BAND <= lo and hi <= REDUNDANT_DELTA_BAND
            and -REDUNDANT_IC_BAND <= key_diag["ci_low"] and key_diag["ci_high"] <= REDUNDANT_IC_BAND):
        return "REDUNDANT"
    return "INCONCLUSIVE"


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def run_study() -> dict:
    protocol, protocol_sha = load_protocol()
    symbols, universe = load_external_universe()
    frames, manifest = load_external_dataset()
    baseline = load_technical_baseline()
    panel, _, _ = build_panel(frames, datetime.fromisoformat(manifest["freeze_now_utc"]), baseline)
    states = load_verified_states()
    discovery, _ = load_frozen_universe()
    if set(states["symbol"]) & set(discovery) or not set(states["symbol"]) <= set(symbols):
        raise ValueError("durum tablosu dış evren dışı sembol içeriyor")

    keep = ["date", "symbol", "turnover20", "bench_roc20", *[f"ex_{h}" for h in (1, 5, 10, 20)]]
    df = states.merge(panel[keep], on=["date", "symbol"], how="inner")
    df["high"] = df["rv20"].map(lambda v: None if pd.isna(v) else bool(v >= HIGH_VOLUME_RATIO))
    df["tech_state"] = tech_state(df["technical_score_prod"])
    df["direction"] = df["r_1d"].map(price_direction)
    df["volume_shape"] = df["prior4_high_count"].map(lambda v: None if pd.isna(v) else spike_or_sustained(int(v)))
    df["log_rv20"] = np.where(df["rv20"] > 0, np.log(df["rv20"].where(df["rv20"] > 0)), np.nan)
    liq_rank = df.groupby("date")["turnover20"].rank(pct=True)
    df["low_liquidity"] = liq_rank <= 0.2
    has_rv = df["high"].notna()
    high = df["high"] == True  # noqa: E712
    not_high = df["high"] == False  # noqa: E712
    tp = (df["tech_state"] == "POS") & has_rv
    tn = (df["tech_state"] == "NEG") & has_rv
    tneu = (df["tech_state"] == "NEU") & has_rv
    target = f"ex_{PRIMARY_H}"

    r: dict = {
        "protocol_version": protocol["protocol_version"], "protocol_sha256": protocol_sha,
        "dataset_sha256": manifest["dataset_sha256"], "external_symbols_sha256": universe["external_symbols_sha256"],
        "technical_baseline": {k: v for k, v in baseline.items() if k not in ("weights", "family_weights")},
        "technical_blinding": "TECHNICAL_BLIND",
        "sample": {
            "state_rows": int(len(states)), "merged_rows": int(len(df)),
            "symbols": int(df["symbol"].nunique()), "dates": int(df["date"].nunique()),
            "first_date": df["date"].min().date().isoformat(), "last_date": df["date"].max().date().isoformat(),
            "rv_unavailable_rows": int((~has_rv).sum()), "high_volume_rows": int(high.sum()),
            "high_volume_share": float(high.sum() / has_rv.sum()),
            "technical_positive_rows": int(tp.sum()), "technical_negative_rows": int(tn.sum()),
            "strong_precondition_rows": int((df["strong_precondition"] & has_rv).sum()),
            "strong_precondition_high_rows": int((df["strong_precondition"] & high).sum()),
            "bullish_confirmed_breakout_rows": int((df["bullish_confirmed_breakout"] & has_rv).sum()),
            "high_equals_low_rows": int(df["high_equals_low"].sum()),
            "high_equals_low_high_volume_rows": int((df["high_equals_low"] & high).sum()),
        },
    }

    # PRIMARY + KEY DIAGNOSTIC
    prim = group_delta(df, tp & high, tp & not_high, target, PRIMARY_H)
    r["PRIMARY"] = _strip(prim)
    kd = st.summarize_series(daily_partial_ic(df, "log_rv20", ["technical_score_prod"], target, MIN_IC), PRIMARY_H)
    r["KEY_DIAGNOSTIC"] = kd

    # İKİNCİL aile
    sec: dict = {}
    for h in SECONDARY_H:
        sec[f"PRIMARY_T{h}"] = _strip(group_delta(df, tp & high, tp & not_high, f"ex_{h}", h))
        sec[f"KEY_DIAGNOSTIC_T{h}"] = {"return_delta": st.summarize_series(
            daily_partial_ic(df, "log_rv20", ["technical_score_prod"], f"ex_{h}", MIN_IC), h)}
    sec["BEARISH"] = _strip(group_delta(df, tn & high, tn & not_high, target, PRIMARY_H))
    sec["NEUTRAL"] = _strip(group_delta(df, tneu & high, tneu & not_high, target, PRIMARY_H))
    sp = df["strong_precondition"] & has_rv
    sec["PRODUCTION_STRONG_CONTEXT"] = _strip(group_delta(df, sp & high, sp & not_high, target, PRIMARY_H))
    bc = df["bullish_confirmed_breakout"] & has_rv
    sec["BREAKOUT_CONTEXT"] = _strip(group_delta(df, bc & high, bc & not_high, target, PRIMARY_H))
    for label, direction in (("DIRECTION_UP_A_minus_B", "UP"), ("DIRECTION_DOWN_C_minus_D", "DOWN"),
                             ("DIRECTION_FLAT_E_minus_F", "FLAT")):
        sec[label] = _strip(direction_delta(df, direction, target, PRIMARY_H))
    sec["SPIKE"] = _strip(group_delta(df, tp & high & (df["volume_shape"] == "SPIKE"), tp & not_high, target, PRIMARY_H))
    sec["SUSTAINED"] = _strip(group_delta(df, tp & high & (df["volume_shape"] == "SUSTAINED"), tp & not_high, target, PRIMARY_H))
    low = df["low_liquidity"]
    sec["LIQUIDITY_LOWEST_QUINTILE"] = _strip(group_delta(df, tp & high & low, tp & not_high & low, target, PRIMARY_H))
    sec["LIQUIDITY_REMAINING_80"] = _strip(group_delta(df, tp & high & ~low, tp & not_high & ~low, target, PRIMARY_H))
    hl = df["high_equals_low"]
    sec["LIMIT_LOCKED_EXCLUDED"] = _strip(group_delta(df, tp & high & ~hl, tp & not_high & ~hl, target, PRIMARY_H))
    r["secondary"] = sec
    pvals = {k: v["return_delta"]["p_boot"] for k, v in sec.items()}
    holm = st.holm_adjust(pvals)
    r["holm_adjusted_secondary"] = holm

    # İSTİKRAR
    s = prim["_series"]
    regime = df.groupby("date")["bench_roc20"].first().reindex(s.index)
    r["stability"] = {
        "by_year": {str(y): {"n_dates": int(len(p)), "mean": float(p.mean()), "nw_t": st.newey_west_t(p.to_numpy(float), PRIMARY_H)}
                    for y, p in s.groupby(s.index.year)},
        "market_up": st.summarize_series(s[regime > 0], PRIMARY_H),
        "market_down": st.summarize_series(s[regime <= 0], PRIMARY_H),
    }

    # 10 OFFSET
    r["offsets"] = {
        "technical_positive_high_volume_selection": selection_offsets(df, tp, high, target),
        "production_strong_selection": selection_offsets(df, sp, high, target),
    }

    bear = sec["BEARISH"]["return_delta"]
    r["classification"] = classify(r["PRIMARY"]["return_delta"], kd, holm.get("BEARISH"), bear["mean"])
    r["production_change_indicated"] = {"HARMFUL": "EVET", "DIRECTION-CONDITIONAL": "EVET", "SUPPORTED": "HAYIR",
                                        "REDUNDANT": "HAYIR", "INCONCLUSIVE": "BELIRSIZ"}[r["classification"]]
    assert_blind(r)
    return r


def main() -> None:
    from app.research.technical_volume_audit.report import write_results

    results = run_study()
    write_results(results)
    print({"classification": results["classification"], "production_change_indicated": results["production_change_indicated"]})


if __name__ == "__main__":
    main()
