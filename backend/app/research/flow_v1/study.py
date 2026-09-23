"""FLOW 1B çalışma orkestrasyonu (AĞ YOK — yalnızca dondurulmuş veri).

Çalıştırma: `python -m app.research.flow_v1.study`

TECHNICAL-KÖR: Technical yalnızca KONTROL değişkenidir. Bu modül Technical'ın
kendi IC'sini, kova getirisini, hit-rate'ini veya quintile getirisini HİÇ
hesaplamaz; Technical kovası içindeki Flow grupları yalnızca FARK (delta)
olarak raporlanır. `assert_technical_blind()` sonuç sözlüğünü yazmadan önce
yasak anahtarlara karşı tarar.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from app.research.flow_v1 import statistics as st
from app.research.flow_v1.dataset import load_protocol, load_verified_dataset
from app.research.flow_v1.panel import HORIZONS, build_panel, load_technical_baseline

PRIMARY_H = 10
MIN_IC = 20
MIN_Q = 50
MIN_GROUP = 2
TECH_POSITIVE = 15.0
FLOW_POS = 20.0
FLOW_NEG = -20.0
FLAT_ROC = 0.03
H4_NSV = 0.20
RISING_ROC = 0.10
REBALANCE_EVERY = 10
REBALANCE_BLOCK = 2  # 2 yeniden dengeleme = 20 seans (günlük serilerdeki blok uzunluğuyla aynı süre)
COSTS_BPS = (10, 20, 40)
MIN_MEANINGFUL_PARTIAL_IC = 0.02

FLOW_FEATURES = ["pvfs", "cmf20", "nsv20"]
RESEARCH_FEATURES = ["mfi14", "log_rv20"]
CORR_FEATURES = ["cmf20", "nsv20", "pvfs", "mfi14", "log_rv20", "technical_score", "rsi14",
                 "momentum_component", "roc_component", "roc20_price"]
# Hedefle (getiri) ilişkisi ASLA hesaplanmayacak kolonlar (Technical-kör).
TECHNICAL_ONLY_COLUMNS = frozenset({"technical_score", "rsi14", "momentum_component", "roc_component"})
FORBIDDEN_KEY_TOKENS = ("technical_ic", "technical_hit", "technical_return", "technical_quintile",
                        "tech_positive_mean", "tech_bucket_mean", "tech_positive_level")


class TechnicalBlindViolation(AssertionError):
    pass


def assert_technical_blind(obj, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            if any(tok in key for tok in FORBIDDEN_KEY_TOKENS):
                raise TechnicalBlindViolation(f"yasak anahtar: {path}/{k}")
            assert_technical_blind(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_technical_blind(v, f"{path}[{i}]")


def _guard_feature(feature: str) -> None:
    if feature in TECHNICAL_ONLY_COLUMNS:
        raise TechnicalBlindViolation(f"{feature} için getiri istatistiği hesaplanamaz (Technical-kör)")


# ------------------------------------------------------------------ per-date


def daily_ic(panel: pd.DataFrame, feature: str, target: str, min_n: int = MIN_IC) -> pd.Series:
    _guard_feature(feature)
    out = {}
    for d, g in panel[["date", feature, target]].dropna().groupby("date"):
        if len(g) >= min_n:
            out[d] = st.spearman(g[feature], g[target])
    return pd.Series(out, dtype=float)


def daily_partial_ic(panel: pd.DataFrame, feature: str, controls: list[str], target: str, min_n: int = MIN_IC) -> pd.Series:
    _guard_feature(feature)
    out = {}
    cols = ["date", feature, *controls, target]
    for d, g in panel[cols].dropna().groupby("date"):
        if len(g) >= min_n:
            out[d] = st.partial_rank_ic(g[feature], g[controls], g[target])
    return pd.Series(out, dtype=float)


def daily_residual(panel: pd.DataFrame, feature: str, controls: list[str], min_n: int = MIN_IC) -> pd.Series:
    """Tarih bazında rank(feature) ~ rank(controls) artığı (satır index'li)."""
    parts = []
    for _, g in panel[["date", feature, *controls]].dropna().groupby("date"):
        if len(g) >= min_n:
            parts.append(st.rank_residual(g[feature], g[controls]))
    return pd.concat(parts) if parts else pd.Series(dtype=float)


def quintile_study(panel: pd.DataFrame, feature: str, target: str, raw_target: str | None) -> dict:
    _guard_feature(feature)
    rows = {}
    raw_rows = {}
    spreads = {}
    cols = ["date", feature, target] + ([raw_target] if raw_target else [])
    for d, g in panel[cols].dropna().groupby("date"):
        if len(g) < MIN_Q:
            continue
        q = st.assign_quintiles(g[feature])
        means = g[target].groupby(q).mean()
        rows[d] = means
        spreads[d] = means[5] - means[1]
        if raw_target:
            raw_rows[d] = g[raw_target].groupby(q).mean()
    if not rows:
        return {"n_dates": 0}
    table = pd.DataFrame(rows).T
    qmeans = [float(table[i].mean()) for i in range(1, 6)]
    result = {
        "n_dates": int(len(table)),
        "quintile_mean_excess": qmeans,
        "q5_minus_q1": st.summarize_series(pd.Series(spreads), int(target.split("_")[-1])),
        "monotonicity": st.monotonicity(qmeans),
    }
    if raw_target:
        raw_table = pd.DataFrame(raw_rows).T
        result["quintile_mean_raw"] = [float(raw_table[i].mean()) for i in range(1, 6)]
    return result


def conditional_delta(panel: pd.DataFrame, subset_mask: pd.Series, group_mask: pd.Series, base_mask: pd.Series,
                      target: str) -> dict:
    """Tarih bazında: mean(target | subset & group) − mean(target | subset & base).
    Hem getiri farkı hem hit-rate (target>0) farkı. Seviyeler döndürülmez."""
    df = panel.loc[subset_mask, ["date", target]].copy()
    df["_g"] = group_mask[subset_mask]
    df["_b"] = base_mask[subset_mask]
    df = df.dropna(subset=[target])
    ret, hit, n_group, n_base = {}, {}, 0, 0
    for d, g in df.groupby("date"):
        a = g.loc[g["_g"], target]
        b = g.loc[g["_b"], target]
        if len(a) >= MIN_GROUP and len(b) >= MIN_GROUP:
            ret[d] = a.mean() - b.mean()
            hit[d] = (a > 0).mean() - (b > 0).mean()
            n_group += len(a)
            n_base += len(b)
    h = int(target.split("_")[-1])
    return {
        "return_delta": st.summarize_series(pd.Series(ret, dtype=float), h),
        "hit_rate_delta_pp": st.summarize_series(pd.Series(hit, dtype=float), h, scale=100.0),
        "group_observations": int(n_group),
        "comparison_observations": int(n_base),
        "total_subset_observations": int(len(df)),
        "total_group_observations": int(df["_g"].sum()),
    }


def cost_sensitivity(panel: pd.DataFrame, score: pd.Series, target: str) -> dict:
    """Örtüşmeyen (her 10. uygun tarih) Q5−Q1 ve Q5−XU100 brüt/net."""
    df = panel[["date", "symbol", target]].copy()
    df["_s"] = score
    df = df.dropna()
    dates = [d for d, g in df.groupby("date") if len(g) >= MIN_Q]
    rebal = dates[::REBALANCE_EVERY]
    prev_long, prev_short = None, None
    rows = []
    for d in rebal:
        g = df[df["date"] == d]
        q = st.assign_quintiles(g["_s"])
        long_names = set(g.loc[q == 5, "symbol"])
        short_names = set(g.loc[q == 1, "symbol"])
        long_ret = g.loc[q == 5, target].mean()
        short_ret = g.loc[q == 1, target].mean()
        to_l = 1.0 if prev_long is None else 1.0 - len(long_names & prev_long) / len(long_names)
        to_s = 1.0 if prev_short is None else 1.0 - len(short_names & prev_short) / len(short_names)
        rows.append({"date": d, "ls": long_ret - short_ret, "lo": long_ret, "to_l": to_l, "to_s": to_s})
        prev_long, prev_short = long_names, short_names
    frame = pd.DataFrame(rows).set_index("date")
    out = {
        "rebalance_dates": int(len(frame)),
        "mean_turnover_long": float(frame["to_l"].mean()),
        "mean_turnover_short": float(frame["to_s"].mean()),
        "long_short_gross": st.summarize_series(frame["ls"], 1, block_length=REBALANCE_BLOCK),
        "long_only_excess_gross": st.summarize_series(frame["lo"], 1, block_length=REBALANCE_BLOCK),
    }
    for c in COSTS_BPS:
        cost = c / 10_000.0
        out[f"long_short_net_{c}bps"] = st.summarize_series(frame["ls"] - cost * (frame["to_l"] + frame["to_s"]), 1, block_length=REBALANCE_BLOCK)
        out[f"long_only_excess_net_{c}bps"] = st.summarize_series(frame["lo"] - cost * frame["to_l"], 1, block_length=REBALANCE_BLOCK)
    return out


def correlations(panel: pd.DataFrame) -> dict:
    cols = CORR_FEATURES
    sub = panel[["date", *cols]].dropna()
    per_date = []
    for _, g in sub.groupby("date"):
        if len(g) >= MIN_IC:
            per_date.append(g[cols].rank().corr().to_numpy())
    mean_cs = np.nanmean(np.stack(per_date), axis=0)
    pooled = sub[cols].rank().corr().to_numpy()
    return {
        "features": cols,
        "mean_cross_sectional_spearman": mean_cs.tolist(),
        "pooled_spearman": pooled.tolist(),
        "n_dates": len(per_date),
        "n_observations": int(len(sub)),
    }


def describe_features(panel: pd.DataFrame) -> dict:
    out = {}
    for col in ["cmf20", "nsv20", "pvfs", "mfi14", "rv20", "turnover20", "roc20_price", "technical_score"]:
        s = panel[col].dropna()
        out[col] = {
            "count": int(len(s)), "unavailable": int(panel[col].isna().sum()),
            "mean": float(s.mean()), "std": float(s.std()), "min": float(s.min()),
            "p05": float(s.quantile(0.05)), "p25": float(s.quantile(0.25)), "median": float(s.median()),
            "p75": float(s.quantile(0.75)), "p95": float(s.quantile(0.95)), "max": float(s.max()),
        }
    return out


def technical_parity_check(frames: dict, freeze_now: datetime, baseline: dict, samples: int = 25, seed: int = 12001) -> dict:
    """Vektörize `technical_score_series` ile canlı `compute_technical_analysis`
    arasında skor eşitliği (aynı segment öneki üzerinde). Yalnızca skor
    DEĞERLERİ karşılaştırılır — getiri/performans yok."""
    from app.engines.backtest.engine import technical_score_series
    from app.engines.technical.engine import compute_technical_analysis
    from app.research.flow_v1.dataset import BENCHMARK_SYMBOL, preprocess_symbol
    from app.research.flow_v1.panel import WARMUP_SESSIONS

    bench_segments, _ = preprocess_symbol(BENCHMARK_SYMBOL, frames[BENCHMARK_SYMBOL], freeze_now)
    bench_close = pd.concat([s["Close"] for s in bench_segments])
    bench_close.index = [ts.date() for ts in bench_close.index]
    rng = np.random.default_rng(seed)
    symbols = sorted(s for s in frames if s != BENCHMARK_SYMBOL)
    diffs, errors = [], []
    for _ in range(samples):
        symbol = symbols[int(rng.integers(len(symbols)))]
        segments, _ = preprocess_symbol(symbol, frames[symbol], freeze_now)
        segments = [s for s in segments if len(s) > WARMUP_SESSIONS + 1]
        if not segments:
            continue
        seg = segments[int(rng.integers(len(segments)))]
        pos = int(rng.integers(WARMUP_SESSIONS, len(seg)))
        prefix = seg.iloc[: pos + 1]
        vec = float(technical_score_series(prefix, baseline["weights"], baseline["family_weights"]).iloc[-1])
        try:
            live = compute_technical_analysis(
                prefix, symbol, baseline["weights"], baseline["family_weights"], baseline["scoring_config_hash"],
                "RESEARCH_PARITY_CHECK", {}, benchmark_close_series=bench_close, now=freeze_now,
            ).technical_score
            diffs.append(abs(vec - float(live)))
        except Exception as exc:  # parity kontrolü raporlanır, çalışmayı durdurmaz
            errors.append(f"{symbol}@{prefix.index[-1].date()}: {type(exc).__name__}: {exc}"[:200])
    return {"samples_compared": len(diffs), "max_abs_diff": max(diffs) if diffs else None, "errors": errors}


# ------------------------------------------------------------------ run


def run_study() -> dict:
    protocol, protocol_sha = load_protocol()
    frames, manifest = load_verified_dataset()
    baseline = load_technical_baseline()
    freeze_now = datetime.fromisoformat(manifest["freeze_now_utc"])
    panel, qualities, build_info = build_panel(frames, freeze_now, baseline)
    target = f"ex_{PRIMARY_H}"

    results: dict = {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol_sha,
        "dataset_sha256": manifest["dataset_sha256"],
        "technical_baseline": {k: v for k, v in baseline.items() if k not in ("weights", "family_weights")},
        "technical_blinding": protocol["technical_blinding"]["mode"],
        "build_info": build_info,
        "technical_parity_check": technical_parity_check(frames, freeze_now, baseline),
    }

    # ---- örneklem
    obs = panel
    results["sample"] = {
        "panel_rows": int(len(obs)),
        "symbols_with_observations": int(obs["symbol"].nunique()),
        "first_observation_date": obs["date"].min().date().isoformat(),
        "last_observation_date": obs["date"].max().date().isoformat(),
        "distinct_observation_dates": int(obs["date"].nunique()),
        "per_symbol_observations": {s: int(n) for s, n in obs.groupby("symbol").size().items()},
        "rows_with_pvfs": int(obs["pvfs"].notna().sum()),
        "rows_with_technical": int(obs["technical_score"].notna().sum()),
        "rows_with_target": {f"ex_{h}": int(obs[f"ex_{h}"].notna().sum()) for h in HORIZONS},
        "primary_complete_rows": int(obs[["pvfs", "technical_score", target]].dropna().shape[0]),
    }
    results["quality"] = [q.__dict__ for q in qualities]
    results["feature_descriptives"] = describe_features(obs)
    results["correlations"] = correlations(obs)

    # ---- IC ve partial IC (bilgi hedefi + ayrı yürütme varyantı)
    metrics = []
    series_store: dict[str, pd.Series] = {}
    for variant, prefix in (("information_close_to_close", "ex_"), ("execution_open_e1_to_close_eh", "exec_ex_")):
        for h in HORIZONS:
            tgt = f"{prefix}{h}"
            for feat in FLOW_FEATURES + RESEARCH_FEATURES:
                ic = daily_ic(obs, feat, tgt)
                metrics.append({"variant": variant, "horizon": h, "feature": feat, "statistic": "ic",
                                "controls": "", **st.summarize_series(ic, h)})
                ctrl = ["technical_score"] if feat != "mfi14" else ["technical_score", "rsi14"]
                pic = daily_partial_ic(obs, feat, ctrl, tgt)
                metrics.append({"variant": variant, "horizon": h, "feature": feat, "statistic": "partial_ic",
                                "controls": "+".join(ctrl), **st.summarize_series(pic, h)})
                if variant.startswith("information"):
                    series_store[f"ic|{feat}|{h}"] = ic
                    series_store[f"pic|{feat}|{h}"] = pic
    # MFI yalnızca RSI kontrolü (H6 ek bilgi)
    for h in HORIZONS:
        pic = daily_partial_ic(obs, "mfi14", ["rsi14"], f"ex_{h}")
        metrics.append({"variant": "information_close_to_close", "horizon": h, "feature": "mfi14",
                        "statistic": "partial_ic", "controls": "rsi14", **st.summarize_series(pic, h)})
    results["metrics"] = metrics

    def find(feature, statistic, h, controls=None, variant="information_close_to_close"):
        for m in metrics:
            if (m["feature"], m["statistic"], m["horizon"], m["variant"]) == (feature, statistic, h, variant) and (
                controls is None or m["controls"] == controls
            ):
                return m
        return None

    # ---- birincil hipotez P1
    p1 = find("pvfs", "partial_ic", PRIMARY_H, "technical_score")
    results["P1"] = {"definition": protocol["hypotheses"]["P1_primary"], **p1, "label": st.label_positive(p1)}

    # ---- quintile'lar
    resid_pvfs = daily_residual(obs, "pvfs", ["technical_score"])
    obs = obs.assign(pvfs_resid_tech=resid_pvfs)
    quint = {}
    for h in HORIZONS:
        for feat in ["pvfs", "cmf20", "nsv20", "pvfs_resid_tech"]:
            quint[f"{feat}|{h}"] = quintile_study(obs, feat, f"ex_{h}", f"raw_{h}")
    results["quintiles"] = quint

    # ---- Technical-koşullu (yalnızca farklar)
    tp = obs["technical_score"] >= TECH_POSITIVE
    fpos = obs["pvfs"] >= FLOW_POS
    fneg = obs["pvfs"] <= FLOW_NEG
    fneu = (obs["pvfs"] > FLOW_NEG) & (obs["pvfs"] < FLOW_POS)
    has_pvfs = obs["pvfs"].notna()
    tp_valid = tp & has_pvfs
    hyp = {}
    for h in HORIZONS:
        tgt = f"ex_{h}"
        hyp[f"H1|{h}"] = conditional_delta(obs, tp_valid, fpos, tp_valid, tgt)
        hyp[f"H2|{h}"] = conditional_delta(obs, tp_valid, fneg, tp_valid, tgt)
        hyp[f"H1H2_spread|{h}"] = conditional_delta(obs, tp_valid, fpos, fneg, tgt)
        hyp[f"neutral_vs_all|{h}"] = conditional_delta(obs, tp_valid, fneu, tp_valid, tgt)
        flat = (obs["roc20_price"].abs() <= FLAT_ROC) & obs["nsv20"].notna()
        hyp[f"H4|{h}"] = conditional_delta(obs, flat, obs["nsv20"] >= H4_NSV, obs["nsv20"] < H4_NSV, tgt)
        rising = (obs["roc20_price"] >= RISING_ROC) & obs["nsv20"].notna()
        hyp[f"H5|{h}"] = conditional_delta(obs, rising, obs["nsv20"] <= 0, obs["nsv20"] > 0, tgt)
    h6 = find("mfi14", "partial_ic", PRIMARY_H, "technical_score+rsi14")
    hypotheses = {
        "H1": {**hyp[f"H1|{PRIMARY_H}"], "label": st.label_positive(hyp[f"H1|{PRIMARY_H}"]["return_delta"])},
        "H2": {**hyp[f"H2|{PRIMARY_H}"], "label": st.label_negative(hyp[f"H2|{PRIMARY_H}"]["return_delta"])},
        "H1_H2_spread": hyp[f"H1H2_spread|{PRIMARY_H}"],
        "neutral_vs_all": hyp[f"neutral_vs_all|{PRIMARY_H}"],
        "H4": {**hyp[f"H4|{PRIMARY_H}"], "label": st.label_positive(hyp[f"H4|{PRIMARY_H}"]["return_delta"])},
        "H5": {**hyp[f"H5|{PRIMARY_H}"], "label": st.label_negative(hyp[f"H5|{PRIMARY_H}"]["return_delta"])},
        "H6": {"mfi_partial_ic_controls_technical_rsi": h6,
               "mfi_adds_information": st.label_positive(h6) == "SUPPORTED",
               "label": "MFI_NOT_REDUNDANT" if st.label_positive(h6) == "SUPPORTED" else "MFI_REDUNDANT_OR_UNPROVEN"},
        "all_horizons": hyp,
    }
    results["hypotheses"] = hypotheses

    # ---- maliyet duyarlılığı (T+10)
    results["cost_sensitivity"] = {
        "pvfs": cost_sensitivity(obs, obs["pvfs"], target),
        "pvfs_resid_tech": cost_sensitivity(obs, obs["pvfs_resid_tech"], target),
    }

    # ---- istikrar
    stab = {}
    for feat in FLOW_FEATURES:
        s = series_store[f"pic|{feat}|{PRIMARY_H}"]
        years = {}
        for y, part in s.groupby(s.index.year):
            years[int(y)] = {"n_dates": int(len(part)), "mean": float(part.mean()),
                             "nw_t": st.newey_west_t(part.to_numpy(float), PRIMARY_H)}
        stab[feat] = years
    regime = obs.groupby("date")["bench_roc20"].first()
    s = series_store[f"pic|pvfs|{PRIMARY_H}"]
    reg = regime.reindex(s.index)
    stab["pvfs_by_regime"] = {
        "market_up": st.summarize_series(s[reg > 0], PRIMARY_H),
        "market_down": st.summarize_series(s[reg <= 0], PRIMARY_H),
        "regime_unavailable_dates": int(reg.isna().sum()),
    }
    # likidite sağlamlığı: en düşük işlem-değeri quintile'ı hariç
    liq_rank = obs.groupby("date")["turnover20"].rank(pct=True)
    low_liq = liq_rank <= 0.2
    stab["pvfs_excluding_low_liquidity"] = st.summarize_series(
        daily_partial_ic(obs[~low_liq], "pvfs", ["technical_score"], target), PRIMARY_H)
    stab["low_liquidity_observations"] = int(low_liq.sum())
    results["stability"] = stab

    # ---- çoklu test (ikincil aile)
    secondary_p = {}
    for m in metrics:
        key = f"{m['variant']}|{m['statistic']}|{m['feature']}|{m['controls']}|{m['horizon']}"
        if m is p1:
            continue
        secondary_p[key] = m["p_boot"]
    for name, val in hyp.items():
        secondary_p[f"hyp|{name}"] = val["return_delta"]["p_boot"]
    results["holm_adjusted_secondary"] = st.holm_adjust(secondary_p)

    # ---- kapı
    results["gate"] = evaluate_gate(results, stab)
    assert_technical_blind(results)
    return results


def evaluate_gate(results: dict, stab: dict) -> dict:
    p1 = results["P1"]
    label = p1["label"]
    years = [v for v in stab["pvfs"].values() if v["n_dates"] >= 100]
    positive_years = sum(1 for v in years if v["mean"] > 0)
    year_ok = bool(years) and positive_years >= (2 / 3) * len(years)
    net20 = results["cost_sensitivity"]["pvfs_resid_tech"]["long_short_net_20bps"]["mean"]
    cost_ok = net20 is not None and net20 > 0
    if label == "EVIDENCE_OPPOSITE_DIRECTION" or (p1["ci_high"] is not None and p1["ci_high"] < MIN_MEANINGFUL_PARTIAL_IC):
        decision = "DUR"
    elif label == "SUPPORTED" and year_ok and cost_ok:
        decision = "DEVAM"
    else:
        decision = "BELIRSIZ"
    return {
        "decision": decision,
        "p1_label": label,
        "p1_ci": [p1["ci_low"], p1["ci_high"]],
        "min_meaningful_partial_ic": MIN_MEANINGFUL_PARTIAL_IC,
        "years_with_100_dates": len(years),
        "positive_years": positive_years,
        "year_condition_met": year_ok,
        "resid_long_short_net_20bps_mean": net20,
        "cost_condition_met": cost_ok,
    }


def main() -> None:
    from app.research.flow_v1.report import write_results

    results = run_study()
    write_results(results)
    print(results["gate"])


if __name__ == "__main__":
    main()
