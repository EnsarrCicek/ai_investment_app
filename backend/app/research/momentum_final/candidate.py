"""Erken momentum — tek WATCH adayının dondurulması (YALNIZ araştırma; üretim yapılandırması DEĞİL).

Kurallar (dokunulmamış final görülmeden ÖNCE sabitlendi):
* Aday yalnız seçim verisinin walk-forward sonucundan türetilir (d15, 1/1 yüzeyi).
* Toplama kuralı: üç katın hepsi AYNI kural ailesini (aynı öznitelik, 1/1) seçmiş ve hepsi görülmemiş blokta
  hedefi geçmiş olmalı; sayısal eşik = katlarda seçilen sayısal eşiklerin MEDYANI. Aksi halde aday yok.
  (Yüzdelik değil sayısal eşik: yüzdelik, uygulandığı evrenin bileşimine bağlıdır; dokunulmamış evren farklıdır.
  Tüm seçim panelinde yüzdeliği yeniden uydurmak OOS doğrulanmamış yeni bir sayı üretirdi.)
* Kanonik JSON: sıralı anahtarlar, sabit ayraçlar, NaN yasak → SHA-256. Dondurma sonrası değişiklik reddedilir.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

CANDIDATE_VERSION = "momentum-watch-final-v1"
PASS_CRITERIA = {"false_positive_rate": ["<=", 0.25], "recall": [">=", 0.40], "lead_fraction_median": ["<=", 0.50],
                 "precision_vs_base": [">=", 1.5]}
FEASIBILITY_VERDICT = "MOMENTUM FEASIBILITY: CURRENT DATA SUFFICIENT"
SCENARIO = "C15_d15_1of1"


class FrozenCandidateError(RuntimeError):
    pass


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def aggregate_threshold(folds: list[dict]) -> tuple[str, float]:
    """(öznitelik, medyan eşik). Ön koşullar sağlanmazsa FrozenCandidateError."""
    if len(folds) < 3:
        raise FrozenCandidateError("walk-forward tamamlanmamış")
    feats = {f.get("config", {}).get("feature") for f in folds}
    if len(feats) != 1 or None in feats:
        raise FrozenCandidateError(f"katlar aynı tek öznitelik ailesini seçmedi: {feats}")
    if not all(f.get("feasible_on_train") and f.get("validate_passes_target") for f in folds):
        raise FrozenCandidateError("her kat eğitimde uygun ve görülmemiş blokta geçer olmalı")
    thr = sorted(float(f["config"]["threshold"]) for f in folds)
    n = len(thr)
    median = thr[n // 2] if n % 2 else (thr[n // 2 - 1] + thr[n // 2]) / 2
    return feats.pop(), median


def build_candidate(wf_folds: list[dict], selection: dict, round1_sha: str, ext_sha: str) -> dict:
    feature, threshold = aggregate_threshold(wf_folds)
    return {
        "version": CANDIDATE_VERSION,
        "level": "WATCH",
        "feature": feature,
        "comparison": ">=",
        "threshold": threshold,
        "confirmation": [1, 1],
        "provider_delay_minutes": 15,
        "interval": "5m",
        "benchmark": "XU100",
        "status_gate": "Round 1 final engine status == OK",
        "missing_feature_policy": "no alert",
        "alert_unit": "first alert per asset-session",
        "round1_engine_config_sha256": round1_sha,
        "extended_feature_config_sha256": ext_sha,
        "strong_rule": "unchanged Round 1 final GROUPS STRONG (reference only, not part of candidate)",
        "selection": {**selection, "aggregation": "median of fold-selected numeric thresholds",
                      "fold_thresholds": [float(f["config"]["threshold"]) for f in wf_folds],
                      "fold_quantiles": [f["config"]["quantile"] for f in wf_folds]},
        "evaluation": {"precision_horizon_mfe": 0.03, "event_runup": 0.05,
                       "lead_fraction": "(entry - run_low) / (session_high - run_low), caught only if alert <= peak"},
        "pass_criteria": PASS_CRITERIA,
        "feasibility_verdict": FEASIBILITY_VERDICT,
    }


def freeze(path: Path, candidate: dict) -> dict:
    """İlk çağrı yazar; sonraki çağrılar yalnız AYNI adayı kabul eder (değişiklik → hata)."""
    manifest = {"candidate": candidate, "sha256": sha256_of(candidate)}
    if path.exists():
        existing = load_frozen(path)
        if existing["sha256"] != manifest["sha256"]:
            raise FrozenCandidateError("aday dondurulmuş; değiştirilemez")
        return existing
    path.write_text(json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")
    return manifest


def load_frozen(path: Path) -> dict:
    if not path.exists():
        raise FrozenCandidateError("final, dondurulmuş aday olmadan değerlendirilemez")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if sha256_of(manifest["candidate"]) != manifest.get("sha256"):
        raise FrozenCandidateError("dondurulmuş aday bozulmuş/değiştirilmiş (SHA uyuşmuyor)")
    return manifest


# ------------------------------------------------------------------ değerlendirme yardımcıları
def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def pass_table(metrics: dict, base_rate: float, criteria: dict = PASS_CRITERIA) -> dict:
    values = {"false_positive_rate": metrics.get("false_positive_rate"), "recall": metrics.get("recall"),
              "lead_fraction_median": metrics.get("lead_fraction_median"),
              "precision_vs_base": (metrics["precision"] / base_rate
                                    if metrics.get("precision") is not None and base_rate else None)}
    out = {}
    for k, (op, limit) in criteria.items():
        v = values[k]
        ok = v is not None and (v <= limit if op == "<=" else v >= limit)
        out[k] = {"value": v, "op": op, "limit": limit, "result": "PASS" if ok else "FAIL"}
    return out


def verdict(table: dict) -> str:
    ok = all(row["result"] == "PASS" for row in table.values())
    return "MOMENTUM UNTOUCHED FINAL: " + ("PASS" if ok else "FAIL")
