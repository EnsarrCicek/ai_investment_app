"""TECH-VOL 1A sonuç dosyaları: summary.json, manifest.json, offsets.csv ve
mekanik TECH_VOL_1A_REPORT.md."""

from __future__ import annotations

import csv
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.flow_v1.report import _clean, _git
from app.research.technical_volume_audit.states import AUDIT_DIR, STATES_MANIFEST_FILE

RESULTS_DIR = AUDIT_DIR / "results"


def _ci(s, scale=100.0, d=2, unit=" pp"):
    if not s or s.get("mean") is None:
        return "—"
    return (f"{s['mean'] * scale:+.{d}f}{unit} [{s['ci_low'] * scale:+.{d}f}, {s['ci_high'] * scale:+.{d}f}] "
            f"(n={s['n_dates']}, NW t={s['nw_t']:+.2f})")


def _pp(x):
    return "—" if x is None else f"{x * 100:+.2f} pp"


def write_results(results: dict, out_dir: Path = RESULTS_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = _clean(results)
    states_manifest = json.loads(STATES_MANIFEST_FILE.read_text(encoding="utf-8"))
    manifest = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "code_head": _git("rev-parse", "HEAD"),
        "audit_uncommitted_changes": _git("status", "--short", "--", str(AUDIT_DIR)),
        "protocol_version": r["protocol_version"], "protocol_sha256": r["protocol_sha256"],
        "flow_1c_dataset_sha256": r["dataset_sha256"], "external_symbols_sha256": r["external_symbols_sha256"],
        "production_states_content_sha256": states_manifest["states_content_sha256"],
        "technical_baseline": r["technical_baseline"],
        "python_version": platform.python_version(), "numpy_version": np.__version__, "pandas_version": pd.__version__,
        "commands": ["python -m app.research.technical_volume_audit.states", "python -m app.research.technical_volume_audit.study"],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(r, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    with (out_dir / "offsets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["context", "offset", "rebalance_dates", "gross", "net_10bps", "net_20bps", "net_40bps"])
        for ctx, o in r["offsets"].items():
            for off, v in o["per_offset"].items():
                w.writerow([ctx, off, v["rebalance_dates"], v["gross"], v["net_10bps"], v["net_20bps"], v["net_40bps"]])
    (out_dir / "TECH_VOL_1A_REPORT.md").write_text(render(r, manifest), encoding="utf-8")


def render(r: dict, m: dict) -> str:
    L = []
    add = L.append
    add("# TECH-VOL 1A — High-Volume Confirmation Audit (MECHANICALLY GENERATED)\n")
    add("> **POST-HOC ASSUMPTION AUDIT.** Tetikleyici FLOW 1B'nin ÖN-KAYITSIZ keşif bulgusudur. Veri: FLOW 1C dış evreni "
        "(keşif 100'ü ile kesişim 0), Yahoo geriye düzeltmeli snapshot, güncel-listeleme survivorship'i. Technical-KÖR: "
        "yalnızca AYNI Technical durumu içindeki yüksek − yüksek-olmayan hacim farkları raporlanır. Üretim kodu DEĞİŞTİRİLMEDİ.\n")
    add("## Kimlik\n")
    for k in ("code_head", "protocol_version", "protocol_sha256", "flow_1c_dataset_sha256", "external_symbols_sha256",
              "production_states_content_sha256", "run_timestamp_utc", "python_version", "pandas_version"):
        add(f"- `{k}`: {m[k]}")
    add(f"- Technical: engine {r['technical_baseline']['current_engine_version']}, scoring_config_hash `{r['technical_baseline']['scoring_config_hash']}`")
    add("\n## Örneklem\n")
    for k, v in r["sample"].items():
        add(f"- {k}: {v}")
    add("\n## PRIMARY (Technical-pozitif içinde yüksek − yüksek-olmayan hacim, T+10) ve KEY DIAGNOSTIC\n")
    p = r["PRIMARY"]
    add(f"- Getiri farkı: {_ci(p['return_delta'])}")
    add(f"- Hit-rate farkı: {_ci(p['hit_rate_delta_pp'], 1.0, 2, ' pp')}")
    add(f"- Gözlem (karşılaştırılan tarihlerde) yüksek/yüksek-olmayan: {p['group_observations']} / {p['comparison_observations']} (toplam {p['group_total']} / {p['comparison_total']})")
    add(f"- KEY DIAGNOSTIC log(RV20) partial IC | Technical (T+10): {_ci(r['KEY_DIAGNOSTIC'], 1.0, 4, '')}")
    add("\n## İkincil aile (Holm düzeltmeli p)\n")
    add("| Test | getiri farkı [95% CI] | Holm p | grup / karşılaştırma gözlemi |")
    add("|---|---|---|---|")
    for k, v in r["secondary"].items():
        scale, unit, d = (1.0, "", 4) if k.startswith("KEY_DIAGNOSTIC") else (100.0, " pp", 2)
        add(f"| {k} | {_ci(v['return_delta'], scale, d, unit)} | {r['holm_adjusted_secondary'].get(k, float('nan')):.4f} | "
            f"{v.get('group_observations', '—')} / {v.get('comparison_observations', '—')} |")
    add("\n## İstikrar (PRIMARY farkı)\n")
    for y, v in r["stability"]["by_year"].items():
        add(f"- {y}: {_pp(v['mean'])} (n={v['n_dates']}, t={v['nw_t']:+.2f})")
    add(f"- Piyasa yukarı: {_ci(r['stability']['market_up'])}")
    add(f"- Piyasa aşağı: {_ci(r['stability']['market_down'])}")
    add("\n## 10 offset (seçili yüksek-hacim − tüm bağlam, T+10)\n")
    for ctx, o in r["offsets"].items():
        add(f"### {ctx}\n")
        add(f"- Uygun tarih: {o['eligible_dates']}; tüm tarihler (örtüşen): {_ci(o['all_dates_overlapping'])}")
        add("| offset | tarih | brüt | net 10 | net 20 | net 40 |")
        add("|---|---|---|---|---|---|")
        for off, v in o["per_offset"].items():
            add(f"| {off} | {v['rebalance_dates']} | {_pp(v['gross'])} | {_pp(v['net_10bps'])} | {_pp(v['net_20bps'])} | {_pp(v['net_40bps'])} |")
        for key in ("across_gross", "across_net_10bps", "across_net_20bps", "across_net_40bps"):
            a = o[key]
            add(f"- {key}: ort. {_pp(a['mean'])}, medyan {_pp(a['median'])}, min {_pp(a['min'])}, max {_pp(a['max'])}, "
                f"genel tahminle aynı işaret {a['n_same_sign_as_overall']}/{a['n_offsets']}")
        add("")
    add("## Sınıflandırma (protokol kuralı, mekanik)\n")
    add(f"- Sınıf: **{r['classification']}**")
    add(f"- Üretim değişikliği gerekli mi (kurala göre): **{r['production_change_indicated']}**")
    return "\n".join(L) + "\n"
