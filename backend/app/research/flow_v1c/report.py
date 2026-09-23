"""FLOW 1C sonuç dosyaları: summary.json, offsets.csv, manifest.json ve mekanik
FLOW_1C_REPORT.md. Tüm sayılar `results` sözlüğünden gelir."""

from __future__ import annotations

import csv
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.flow_v1.report import _clean, _git
from app.research.flow_v1c.dataset import FLOW_V1C_DIR

RESULTS_DIR = FLOW_V1C_DIR / "results"


def _pp(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f} pp"


def _ci(s, scale=1.0, d=4, unit=""):
    if not s or s.get("mean") is None:
        return "—"
    return (f"{s['mean'] * scale:+.{d}f}{unit} [{s['ci_low'] * scale:+.{d}f}, {s['ci_high'] * scale:+.{d}f}] "
            f"(CI {s.get('ci_level', 95):g}%, n={s['n_dates']}, NW t={s['nw_t']:+.2f})")


def write_results(results: dict, out_dir: Path = RESULTS_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = _clean(results)
    manifest = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "code_head": _git("rev-parse", "HEAD"),
        "flow_v1c_uncommitted_changes": _git("status", "--short", "--", str(FLOW_V1C_DIR)),
        "protocol_version": r["protocol_version"],
        "protocol_sha256": r["protocol_sha256"],
        "dataset_sha256": r["dataset_sha256"],
        "external_symbols_sha256": r["external_symbols_sha256"],
        "technical_baseline": r["technical_baseline"],
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "command": "python -m app.research.flow_v1c.study",
    }

    def dump(name, obj):
        (out_dir / name).write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    dump("manifest.json", manifest)
    summary = {k: v for k, v in r.items() if k != "quality"}
    summary["sample"] = {k: v for k, v in r["sample"].items() if k != "per_symbol_observations"}
    dump("summary.json", summary)
    dump("sample_quality.json", {"per_symbol_observations": r["sample"]["per_symbol_observations"], "quality": r["quality"]})

    with (out_dir / "offsets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["analysis", "offset", "rebalance_dates", "gross", "net_10bps", "net_20bps", "net_40bps"])
        for o, v in r["filter_offsets"]["per_offset"].items():
            w.writerow(["negcmf_filter_improvement", o, v["rebalance_dates"], v["gross_improvement"]["mean"],
                        v["net_improvement_10bps"]["mean"], v["net_improvement_20bps"]["mean"], v["net_improvement_40bps"]["mean"]])
        for o, v in r["residual_long_short_offsets"]["per_offset"].items():
            w.writerow(["cmf_resid_long_short", o, v["rebalance_dates"], v["gross"], v["net_10bps"], v["net_20bps"], v["net_40bps"]])

    (out_dir / "FLOW_1C_REPORT.md").write_text(render_markdown(r, manifest), encoding="utf-8")


def render_markdown(r: dict, manifest: dict) -> str:
    L = []
    add = L.append
    add("# FLOW 1C — External CMF Validation Report (MECHANICALLY GENERATED)\n")
    add("> **EXTERNAL CROSS-SECTIONAL ROBUSTNESS STUDY.** Doğrulama evreni = KAP BIST TÜM − FLOW 1B keşif 100'ü "
        "(kesişim 0). Güncel listeleme evreni geriye uygulandı: hayatta kalma yanlılığı ÇÖZÜLMEDİ. Dönem keşifle aynı "
        "(2021–2026), semboller ayrık — zamansal değil kesitsel dış doğrulama. CMF gerçek para girişi değil, fiyat/hacim "
        "VEKİLİDİR. Technical-KÖR: Technical-pozitif adayların kendi getiri seviyesi hesaplanmadı/gösterilmedi.\n")
    add("## Kimlik\n")
    for k in ("code_head", "protocol_version", "protocol_sha256", "dataset_sha256", "external_symbols_sha256",
              "run_timestamp_utc", "python_version", "pandas_version"):
        add(f"- `{k}`: {manifest[k]}")
    s = r["sample"]
    add("\n## Örneklem\n")
    add(f"- Dış evren: {s['universe_size']} sembol; Yahoo çekim hatası: {len(s['fetch_failed'])} → {', '.join(s['fetch_failed']) or '—'}")
    add(f"- Gözlemi olan sembol: {s['symbols_with_observations']}; keşif kesişimi: {s['discovery_overlap_in_panel'] or 0}")
    add(f"- Tarihler: {s['first_observation_date']} → {s['last_observation_date']} ({s['distinct_observation_dates']} tarih); panel satırı {s['panel_rows']}; P1 tam satır {s['primary_complete_rows']}")
    add(f"- P1 kesit büyüklüğü: medyan {s['p1_cross_section_median']:.0f}, min {s['p1_cross_section_min']}, max {s['p1_cross_section_max']}")
    q = [x for x in r["quality"] if x["symbol"] != "XU100"]
    tot = lambda k: sum(x[k] for x in q)
    add(f"- Kalite: ham bar {tot('raw_bars')}, hayalet bar {tot('dropped_non_session_bars')}, bütünlük ihlali {tot('invalid_integrity_bars')}, "
        f"eksik beklenen seans {tot('missing_expected_sessions')}, sıfır hacim {tot('zero_volume_sessions')}, H==L {tot('high_equals_low_sessions')}; "
        f"warm-up'tan kısa segment {r['build_info']['segments_too_short_for_warmup']}\n")

    add("## Eş-birincil hipotezler (Bonferroni, %97.5 CI)\n")
    p1, p2 = r["P1"], r["P2"]
    add(f"- **P1** CMF20 T+10 partial IC | Technical: {_ci(p1)} → **{p1['label']}** (95% referans: {_ci(p1['ci95_reference'])})")
    add(f"- **P2** negatif-CMF filtresi (reddedilen − geçen, Technical-pozitif içinde): getiri {_ci(p2['return_delta'], 100, 2, ' pp')}; "
        f"hit-rate {_ci(p2['hit_rate_delta_pp'], 1, 2, ' pp')} → **{p2['label']}**; ekonomik anlamlı (≤ −0.40 pp): {p2['economically_meaningful']}")
    add(f"  - Reddedilen/geçen gözlem (karşılaştırılan tarihlerde): {p2['rejected_observations_in_compared_dates']} / {p2['passed_observations_in_compared_dates']}; "
        f"Technical-pozitif gözlem: {p2['technical_positive_observations_with_cmf']}; reddedilme payı: {p2['rejected_share_of_technical_positive']:.3f}\n")

    fo = r["filter_offsets"]
    add("## Negatif-CMF filtresi — 10 offset (filtreli − filtresiz, T+10, örtüşmeyen)\n")
    add("| Offset | tarih | brüt iyileşme | net 10 | net 20 | net 40 | reddedilen−geçen | devir geçen/tümü | ort. aday / red |")
    add("|---|---|---|---|---|---|---|---|---|")
    for o, v in fo["per_offset"].items():
        add(f"| {o} | {v['rebalance_dates']} | {_pp(v['gross_improvement']['mean'])} | {_pp(v['net_improvement_10bps']['mean'])} | "
            f"{_pp(v['net_improvement_20bps']['mean'])} | {_pp(v['net_improvement_40bps']['mean'])} | {_pp(v['rejected_minus_passed']['mean'])} | "
            f"{v['mean_turnover_passed']:.2f}/{v['mean_turnover_all']:.2f} | {v['mean_candidates']:.1f} / {v['mean_rejected']:.1f} |")
    add("")
    for key, a in fo["across_offsets"].items():
        if key.startswith("all_dates"):
            add(f"- {key}: {_ci(a, 100, 2, ' pp')}")
        else:
            add(f"- {key}: ort. {_pp(a['mean'])}, medyan {_pp(a['median'])}, min {_pp(a['min'])}, max {_pp(a['max'])}, pozitif {a['n_positive']}/{a['n_offsets']}")

    ls = r["residual_long_short_offsets"]
    add("\n## İkincil: Technical'a göre artıklaştırılmış CMF Q5−Q1 — 10 offset\n")
    add(f"- Tüm tarihler (örtüşen) brüt: {_ci(ls['all_dates_overlapping_gross'], 100, 2, ' pp')}")
    for key in ("across_gross", "across_net_10bps", "across_net_20bps", "across_net_40bps"):
        a = ls[key]
        add(f"- {key}: ort. {_pp(a['mean'])}, medyan {_pp(a['median'])}, min {_pp(a['min'])}, max {_pp(a['max'])}, pozitif {a['n_positive']}/{a['n_offsets']}")

    sec = r["secondary"]
    add("\n## İkincil: ufuklar ve CMF vs eski PVFS (partial IC | Technical, %95 CI)\n")
    add("| h | CMF20 | PVFS | CMF − PVFS |")
    add("|---|---|---|---|")
    for h in ("1", "5", "10", "20"):
        add(f"| {h} | {_ci(sec['cmf20_partial_ic'][h])} | {_ci(sec['pvfs_partial_ic'][h])} | {_ci(sec['cmf_minus_pvfs_partial_ic'][h])} |")
    add("\n## İkincil: yıllar\n")
    add("| Yıl | P1 ort. (n, t) | P2 ort. (n) |")
    add("|---|---|---|")
    for y, v in sec["by_year"].items():
        add(f"| {y} | {v['p1_mean']:+.4f} ({v['p1_n_dates']}, {v['p1_nw_t']:+.2f}) | {_pp(v['p2_mean'])} ({v['p2_n_dates']}) |")
    lq = sec["liquidity_excl_bottom_quintile"]
    add(f"\n- Likidite (en düşük quintile hariç, {lq['excluded_observations']} gözlem dışlandı): P1 {_ci(lq['p1'])}; P2 {_ci(lq['p2'], 100, 2, ' pp')}")

    g = r["gate"]
    add("\n## Araştırma kapısı (protokol kuralı, mekanik)\n")
    for k, v in g.items():
        add(f"- {k}: **{v}**" if k == "decision" else f"- {k}: {v}")
    return "\n".join(L) + "\n"
