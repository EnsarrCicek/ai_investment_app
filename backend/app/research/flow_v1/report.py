"""FLOW 1B sonuç dosyaları: makine-okunur JSON/CSV + mekanik üretilen
FLOW_1B_REPORT.md. Rapordaki her sayı `results` sözlüğünden gelir; elle
girilmiş sayı yoktur."""

from __future__ import annotations

import csv
import json
import math
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.flow_v1.dataset import FLOW_V1_DIR

RESULTS_DIR = FLOW_V1_DIR / "results"


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=FLOW_V1_DIR, check=True).stdout.strip()
    except Exception as exc:  # pragma: no cover
        return f"UNAVAILABLE ({exc})"


def _fmt(x, digits=4):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:+.{digits}f}"
    return str(x)


def run_manifest(results: dict) -> dict:
    import yfinance

    return {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "code_head": _git("rev-parse", "HEAD"),
        "flow_v1_uncommitted_changes": _git("status", "--short", "--", str(FLOW_V1_DIR)),
        "protocol_version": results["protocol_version"],
        "protocol_sha256": results["protocol_sha256"],
        "dataset_sha256": results["dataset_sha256"],
        "technical_baseline": results["technical_baseline"],
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "yfinance_version_installed": yfinance.__version__,
        "command": "python -m app.research.flow_v1.study",
    }


def write_results(results: dict, out_dir: Path = RESULTS_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = _clean(results)

    def dump(name, obj):
        (out_dir / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = run_manifest(results)
    dump("manifest.json", manifest)
    summary = {k: v for k, v in results.items() if k not in ("metrics", "quality", "hypotheses", "quintiles")}
    summary["sample"] = {k: v for k, v in results["sample"].items() if k != "per_symbol_observations"}
    dump("summary.json", summary)
    dump("hypotheses.json", results["hypotheses"])
    dump("sample_quality.json", {"per_symbol_observations": results["sample"]["per_symbol_observations"],
                                 "quality": results["quality"]})

    metric_cols = ["variant", "horizon", "feature", "statistic", "controls", "n_dates", "mean", "median", "std",
                   "positive_rate", "ci_low", "ci_high", "p_boot", "nw_t"]
    with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=metric_cols, extrasaction="ignore")
        w.writeheader()
        for m in results["metrics"]:
            w.writerow(m)

    corr = results["correlations"]
    with (out_dir / "correlations.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for label, key in (("mean_cross_sectional_spearman", "mean_cross_sectional_spearman"), ("pooled_spearman", "pooled_spearman")):
            w.writerow([label, *corr["features"]])
            for name, row in zip(corr["features"], corr[key]):
                w.writerow([name, *[f"{v:.4f}" for v in row]])
            w.writerow([])

    with (out_dir / "quintiles.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["feature", "horizon", "n_dates", "Q1", "Q2", "Q3", "Q4", "Q5", "Q5_minus_Q1_mean", "ci_low", "ci_high",
                    "monotonic_spearman", "increasing_steps_of_4", "raw_Q1", "raw_Q5"])
        for key, q in results["quintiles"].items():
            feat, h = key.split("|")
            if not q.get("n_dates"):
                w.writerow([feat, h, 0])
                continue
            s = q["q5_minus_q1"]
            raw = q.get("quintile_mean_raw") or [None] * 5
            w.writerow([feat, h, q["n_dates"], *q["quintile_mean_excess"], s["mean"], s["ci_low"], s["ci_high"],
                        q["monotonicity"]["spearman_vs_rank"], q["monotonicity"]["increasing_steps_of_4"], raw[0], raw[4]])

    (out_dir / "FLOW_1B_REPORT.md").write_text(render_markdown(results, manifest), encoding="utf-8")


def _metric(results, feature, statistic, h, controls, variant="information_close_to_close"):
    for m in results["metrics"]:
        if (m["feature"], m["statistic"], m["horizon"], m["controls"], m["variant"]) == (feature, statistic, h, controls, variant):
            return m
    return None


def _ci(m, digits=4):
    if not m or m.get("mean") is None:
        return "—"
    return f"{m['mean']:+.{digits}f} [{m['ci_low']:+.{digits}f}, {m['ci_high']:+.{digits}f}] (n={m['n_dates']}, NW t={_fmt(m['nw_t'], 2)})"


def render_markdown(r: dict, manifest: dict) -> str:
    L = []
    add = L.append
    add("# FLOW 1B — Offline Incremental-Value Report (MECHANICALLY GENERATED)\n")
    add("> **CURRENT FROZEN-UNIVERSE RETROSPECTIVE STUDY.** 2026-09-09 BIST100 listesi geçmişe uygulandı — "
        "yüksek hayatta kalma yanlılığı riski; tarihsel BIST100 portföy performansı DEĞİLDİR. Yahoo verisi temettü/bölünme "
        "düzeltmeli ve geriye dönük değişebilir; bu çalışma dondurulmuş bir snapshot üzerindedir, point-in-time kanıtı "
        "veya prospektif geçerlilik DEĞİLDİR. CMF/NSV/MFI gerçek para girişi değil, fiyat/hacim VEKİLLERİDİR. "
        "Technical-KÖR mod: Technical'ın kendi getiri performansı hesaplanmadı.\n")
    add("## Kimlik\n")
    for k in ("code_head", "protocol_version", "protocol_sha256", "dataset_sha256", "run_timestamp_utc", "python_version",
              "numpy_version", "pandas_version"):
        add(f"- `{k}`: {manifest[k]}")
    tb = r["technical_baseline"]
    add(f"- Technical baseline: `{tb['score_function']}`, engine {tb['current_engine_version']} (manifest {tb['manifest_engine_version']}), "
        f"scoring_config_hash `{tb['scoring_config_hash']}`, freeze_manifest_sha256 `{tb['freeze_manifest_sha256']}`")
    pc = r["technical_parity_check"]
    add(f"- Vektörize vs canlı Technical skor paritesi: {pc['samples_compared']} örnek, max |fark| = {pc['max_abs_diff']}, hata = {len(pc['errors'])}\n")

    s = r["sample"]
    add("## Örneklem\n")
    add(f"- Gözlem tarihleri: {s['first_observation_date']} → {s['last_observation_date']} ({s['distinct_observation_dates']} farklı tarih)")
    add(f"- Panel satırı: {s['panel_rows']}, sembol: {s['symbols_with_observations']}, birincil tam satır (PVFS+Technical+T+10): {s['primary_complete_rows']}")
    add(f"- Hedef mevcut satır: {s['rows_with_target']}")
    add(f"- Warm-up dışı bırakılan bar: {r['build_info']['warmup_excluded_bars']}, warm-up'tan kısa segment: {r['build_info']['segments_too_short_for_warmup']}\n")
    qual = [q for q in r["quality"]]
    tot = lambda k: sum(q[k] for q in qual if q["symbol"] != "XU100")
    add(f"- Kalite toplamları (hisseler): ham bar {tot('raw_bars')}, tamamlanmamış bar {tot('dropped_incomplete_bars')}, "
        f"takvim-dışı (hayalet) bar {tot('dropped_non_session_bars')}, bütünlük ihlali {tot('invalid_integrity_bars')}, "
        f"eksik beklenen seans {tot('missing_expected_sessions')}, sıfır hacimli seans {tot('zero_volume_sessions')}, "
        f"H==L seans {tot('high_equals_low_sessions')}")
    late = sorted((q["first_valid_session"], q["symbol"]) for q in qual if q["symbol"] != "XU100" and q["first_valid_session"] and q["first_valid_session"] > "2021-03-01")
    add(f"- 2021-03 sonrası başlayan (yeni halka arz vb.) semboller: {len(late)} → " + ", ".join(f"{sym} ({d})" for d, sym in late) + "\n")

    add("## Birincil hipotez P1 (T+10, PVFS partial IC | Technical)\n")
    add(f"- {_ci(r['P1'])} → **{r['P1']['label']}**\n")

    add("## IC ve partial IC (bilgi hedefi: Close(T)→Close(T+h), XU100-göreli)\n")
    add("| Özellik | h | IC | partial IC (kontrol) |")
    add("|---|---|---|---|")
    for feat in ("pvfs", "cmf20", "nsv20", "mfi14", "log_rv20"):
        for h in (1, 5, 10, 20):
            ctrl = "technical_score+rsi14" if feat == "mfi14" else "technical_score"
            add(f"| {feat} | {h} | {_ci(_metric(r, feat, 'ic', h, ''))} | {_ci(_metric(r, feat, 'partial_ic', h, ctrl))} ({ctrl}) |")
    add("\n### Yürütme varyantı (AYRI): Open(E1)→Close(Eh)\n")
    add("| Özellik | h | IC | partial IC |")
    add("|---|---|---|---|")
    for feat in ("pvfs", "cmf20", "nsv20"):
        for h in (1, 5, 10, 20):
            add(f"| {feat} | {h} | {_ci(_metric(r, feat, 'ic', h, '', 'execution_open_e1_to_close_eh'))} | "
                f"{_ci(_metric(r, feat, 'partial_ic', h, 'technical_score', 'execution_open_e1_to_close_eh'))} |")

    add("\n## Quintile'lar (ortalama XU100-göreli getiri, tarih-dengeli)\n")
    add("| Özellik | h | n | Q1 | Q2 | Q3 | Q4 | Q5 | Q5−Q1 [CI] | monotonluk ρ / artan adım |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for key, q in r["quintiles"].items():
        feat, h = key.split("|")
        if not q.get("n_dates"):
            continue
        qs = " | ".join(f"{v*100:+.2f}%" for v in q["quintile_mean_excess"])
        sp = q["q5_minus_q1"]
        add(f"| {feat} | {h} | {q['n_dates']} | {qs} | {sp['mean']*100:+.2f}% [{sp['ci_low']*100:+.2f}, {sp['ci_high']*100:+.2f}] | "
            f"{_fmt(q['monotonicity']['spearman_vs_rank'], 2)} / {q['monotonicity']['increasing_steps_of_4']} |")

    add("\n## Hipotezler (T+10; yalnızca farklar — Technical-kör)\n")
    hyp = r["hypotheses"]
    for name in ("H1", "H2", "H1_H2_spread", "neutral_vs_all", "H4", "H5"):
        hd = hyp[name]
        rd, hr = hd["return_delta"], hd["hit_rate_delta_pp"]
        add(f"- **{name}** {hd.get('label', '(betimsel)')}: getiri farkı {_ci(rd)}; hit-rate farkı (pp) {_ci(hr, 2)}; "
            f"grup gözlemi {hd['group_observations']} / karşılaştırma {hd['comparison_observations']} "
            f"(alt küme toplamı {hd['total_subset_observations']}, grup toplamı {hd['total_group_observations']})")
    h6 = hyp["H6"]
    add(f"- **H6** {h6['label']}: MFI partial IC | Technical+RSI = {_ci(h6['mfi_partial_ic_controls_technical_rsi'])}")
    add(f"- MFI partial IC | yalnız RSI (T+10) = {_ci(_metric(r, 'mfi14', 'partial_ic', 10, 'rsi14'))}\n")

    add("## Maliyet duyarlılığı (T+10, örtüşmeyen 10 seanslık yeniden dengeleme)\n")
    add("| Skor | yeniden dengeleme | devir L/S | L−S brüt | L−S net 10/20/40 bps | Q5−XU100 brüt | Q5−XU100 net 10/20/40 bps |")
    add("|---|---|---|---|---|---|---|")
    for name, c in r["cost_sensitivity"].items():
        pct = lambda m: f"{m['mean']*100:+.2f}%" if m["mean"] is not None else "—"
        add(f"| {name} | {c['rebalance_dates']} | {c['mean_turnover_long']:.2f}/{c['mean_turnover_short']:.2f} | "
            f"{pct(c['long_short_gross'])} [{c['long_short_gross']['ci_low']*100:+.2f}, {c['long_short_gross']['ci_high']*100:+.2f}] | "
            f"{pct(c['long_short_net_10bps'])} / {pct(c['long_short_net_20bps'])} / {pct(c['long_short_net_40bps'])} | "
            f"{pct(c['long_only_excess_gross'])} | {pct(c['long_only_excess_net_10bps'])} / {pct(c['long_only_excess_net_20bps'])} / {pct(c['long_only_excess_net_40bps'])} |")

    add("\n## İstikrar (T+10 partial IC)\n")
    st_ = r["stability"]
    add("| Yıl | " + " | ".join(("pvfs", "cmf20", "nsv20")) + " |")
    add("|---|---|---|---|")
    years = sorted(st_["pvfs"].keys())
    for y in years:
        cells = []
        for feat in ("pvfs", "cmf20", "nsv20"):
            v = st_[feat].get(y)
            cells.append(f"{v['mean']:+.4f} (n={v['n_dates']}, t={_fmt(v['nw_t'], 2)})" if v else "—")
        add(f"| {y} | " + " | ".join(cells) + " |")
    add(f"\n- Piyasa yukarı rejimi: {_ci(st_['pvfs_by_regime']['market_up'])}")
    add(f"- Piyasa aşağı rejimi: {_ci(st_['pvfs_by_regime']['market_down'])}")
    add(f"- Düşük likidite quintile'ı hariç P1: {_ci(st_['pvfs_excluding_low_liquidity'])} (dışlanan gözlem {st_['low_liquidity_observations']})\n")

    add("## Korelasyonlar (tarih bazlı kesitsel Spearman ortalaması)\n")
    c = r["correlations"]
    add("| | " + " | ".join(c["features"]) + " |")
    add("|---|" + "---|" * len(c["features"]))
    for name, row in zip(c["features"], c["mean_cross_sectional_spearman"]):
        add(f"| {name} | " + " | ".join(f"{v:+.2f}" for v in row) + " |")

    add("\n## Özellik betimsel istatistikleri\n")
    add("| Özellik | n | mevcut değil | ort. | std | p05 | medyan | p95 |")
    add("|---|---|---|---|---|---|---|---|")
    for name, d in r["feature_descriptives"].items():
        add(f"| {name} | {d['count']} | {d['unavailable']} | {d['mean']:.4g} | {d['std']:.4g} | {d['p05']:.4g} | {d['median']:.4g} | {d['p95']:.4g} |")

    g = r["gate"]
    add("\n## Araştırma kapısı (protokoldeki kurallarla mekanik)\n")
    add(f"- Karar: **{g['decision']}**")
    add(f"- P1: {g['p1_label']}, CI {g['p1_ci']}; anlamlı eşik {g['min_meaningful_partial_ic']}")
    add(f"- Yıl koşulu: {g['positive_years']}/{g['years_with_100_dates']} pozitif → {g['year_condition_met']}")
    add(f"- Maliyet koşulu (artık PVFS L−S net 20 bps ort.): {g['resid_long_short_net_20bps_mean']} → {g['cost_condition_met']}")
    add("\nHolm düzeltmeli ikincil p-değerleri: `summary.json` → `holm_adjusted_secondary`.")
    return "\n".join(L) + "\n"
