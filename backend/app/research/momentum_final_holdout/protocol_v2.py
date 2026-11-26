"""Momentum FINAL holdout protokolü V2 — AÇIK KAPSAM POLİTİKASI DEĞİŞİKLİĞİ (V1 dondurulmuş haliyle KORUNUR).

Neden V2: Orijinal 87 hisselik evren önceden ilan edilmiş "her birincil varlık >= 18 geçerli seans" kapsam şartını
SAĞLAMIYOR (KONTR: 0 geçerli seans). Bu gerçek saklanmaz. V2, aynı nesnel uygunluk politikasını BÜTÜN varlıklara eşit
uygular ve değerlendirilebilir varlık listesini holdout sonuçları OKUNMADAN dondurur. Sonuçlar YALNIZ uygun bulunan
varlıklara genellenebilir; 87 varlıklı orijinal araştırma tasarımı için kapsam şartı karşılanmamıştır.

Uygunluk (tek, eşit politika): bir varlık EVALUABLE ⇔ toplayıcının kendi kuralıyla (5m bar sayısı >= 0.8 × gösterge
bar sayısı) geçerli prospektif FULL seans sayısı >= 18. Aksi halde NOT_EVALUABLE_ASSET (nesnel gerekçe: veri kapsamı).
Doğrulanmamış işlem yöntemi iddiaları gerekçe olarak KULLANILMAZ (yalnız not).

Değişmeyenler: Label V2, birincil hedefler, üç kuralın tanımları/config SHA'ları, ilk-alarm birimi, 20 FULL holdout
seansı kapısı, tek-seferlik koruma, Foreks yalnız açıklayıcı.

Modlar:
* A — D15 PROVIDER SIMULATION (BİRİNCİL PASS/FAIL): toplanan barlar teorik 15 dk sağlayıcı gecikmesiyle; gerçek
  zamanlı gözlem kanıtı DEĞİLDİR.
* B — D20 PROVIDER SENSITIVITY (yalnız duyarlılık; PASS/FAIL'i DEĞİŞTİRMEZ): aynı satırlar 20 dk gecikmeyle görünür.
  Gerçek sağlayıcı gecikmesini garanti etmez; "en iyi gecikme" seçilmez.
* C — ACTUAL OBSERVED AVAILABILITY (yalnız açıklayıcı; PASS/FAIL'i DEĞİŞTİRMEZ): her satır, girdisi olan bütün barlar
  GERÇEKTEN ilk görüldüğünde (first_seen) kullanılabilir. Yalnız canlı kapsamı yeterli varlık-seanslar; yetersizse
  NOT_EVALUABLE_LIVE_COVERAGE. Probe alt kümesinden 86 varlığa genelleme YAPILMAZ.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.research.momentum_final import candidate as cd
from app.research.momentum_final_holdout import protocol as pr

MANIFEST_V2_PATH = pr.HERE / "momentum_final_holdout_protocol_v2.json"
PROTOCOL_V2_VERSION = "MOMENTUM_FINAL_HOLDOUT_PROTOCOL_V2"
V1_PROTOCOL_SHA256 = "39be406f16cfcc0e94c869a4bb385638c77bc90aec665c0ab97671036d7a5d32"
V1_MANIFEST_SHA256 = "fce3263123ec93782380358600d71d041e0631d3253c166edb2965cd37d4e1e4"

EVALUABLE_ASSET = "EVALUABLE_ASSET"
NOT_EVALUABLE_ASSET = "NOT_EVALUABLE_ASSET"
NOT_EVALUABLE_LIVE = "NOT_EVALUABLE_LIVE_COVERAGE"
MIN_VALID_SESSIONS = 18
MIN_ASSET_SESSIONS = 1566
ASSET_BAR_SHARE = 0.8  # toplayıcı integrity.ASSET_BAR_SHARE ile aynı (doğrulanır)

MODE_A, MODE_B, MODE_C = "A_D15_PROVIDER_SIMULATION", "B_D20_PROVIDER_SENSITIVITY", "C_ACTUAL_OBSERVED_AVAILABILITY"
MODE_DELAYS = {MODE_A: 15, MODE_B: 20}
# Mod C — holdout açılmadan önce sabit
LIVE_TIMELY_MAX_MIN = 30  # satırın girdileri bilgi zamanından en geç 30 dk sonra gerçekten görülmüş olmalı
LIVE_SESSION_ROW_SHARE = 0.8  # varlık-seans canlı uygun ⇔ satırlarının >= %80'i zamanında
LIVE_MIN_ASSET_SESSIONS = 100  # kural başına en az 100 canlı uygun varlık-seans; yoksa NOT_EVALUABLE_LIVE_COVERAGE
RULE_DEPENDENCIES = {"A_ROUND1_FINAL_WATCH_3OF3_D15": ["ASSET"], "B_ROUND1_FINAL_STRONG_3OF3_D15": ["ASSET"],
                     "C_FROZEN_REL_RET_Z3_1OF1_D15": ["ASSET", "BENCHMARK"]}


class ProtocolV2Error(RuntimeError):
    pass


# ------------------------------------------------------------------ uygunluk (saf)
def asset_eligibility(valid_sessions: dict[str, int], universe: list[str], full_sessions: int,
                      bar_share_by_asset: dict[str, float] | None = None) -> dict:
    """Aynı politika her varlığa: geçerli seans >= 18 → EVALUABLE; değilse NOT_EVALUABLE_ASSET (kapsam gerekçesi)."""
    out = {}
    for s in sorted(universe):
        n = int(valid_sessions.get(s, 0))
        rec = {"valid_sessions": n, "full_sessions_observed": full_sessions}
        if n >= MIN_VALID_SESSIONS:
            out[s] = {"status": EVALUABLE_ASSET, **rec}
        else:
            reason = f"valid prospective FULL sessions {n} < {MIN_VALID_SESSIONS} (5m bars < {ASSET_BAR_SHARE} x " \
                     f"benchmark bars per session)"
            if bar_share_by_asset and s in bar_share_by_asset:
                reason += f"; median per-session bar share {bar_share_by_asset[s]:.3f}"
            out[s] = {"status": NOT_EVALUABLE_ASSET, "reason": reason, **rec}
    return out


def collect_asset_coverage() -> dict:
    """YALNIZ meta veri: varlık başına geçerli seans sayısı ve bar payı (fiyat/sonuç YOK)."""
    from collections import defaultdict
    from statistics import median

    from app.research.momentum_collector import amendments as am
    from app.research.momentum_collector import integrity as ig
    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_pilot import split as sp
    if ig.ASSET_BAR_SHARE != ASSET_BAR_SHARE:
        raise ProtocolV2Error("collector ASSET_BAR_SHARE changed")
    m = mm.load()
    c = m["config"]
    a = am.readonly_archive()
    try:
        sess = ig.classify_sessions(a, c["benchmark"])
        full = sp.observed_full_sessions(sess, c["prospective_start_session"])
        rows = a.validation_rows(m, "5m")
    finally:
        a.db.close()
    bench = rows[rows["symbol"] == c["benchmark"]].groupby("session_date").size()
    per = rows[rows["symbol"].isin(c["universe"]) & rows["session_date"].isin(set(full))].groupby(
        ["symbol", "session_date"]).size()
    valid, shares = defaultdict(int), defaultdict(list)
    for (s, d), n in per.items():
        shares[s].append(n / bench[d])
        if n >= ASSET_BAR_SHARE * bench.get(d, 0):
            valid[s] += 1
    return {"universe": sorted(c["universe"]), "full_sessions": full, "valid_sessions": dict(valid),
            "median_bar_share": {s: float(median(v)) for s, v in shares.items()},
            "collector_minimums": {"minimum_asset_sessions": c["minimum_asset_sessions"],
                                   "minimum_sessions_per_primary_asset": c["minimum_sessions_per_primary_asset"]}}


# ------------------------------------------------------------------ protokol V2 yükü
def protocol_v2_payload(eligibility: dict, universe: list[str], frozen_at_full_sessions: list[str]) -> dict:
    v1 = pr.load_manifest()
    if v1["protocol_sha256"] != V1_PROTOCOL_SHA256 or v1["manifest_sha256"] != V1_MANIFEST_SHA256:
        raise ProtocolV2Error("V1 protocol manifest changed")
    p1 = v1["protocol"]
    evaluable = sorted(s for s, r in eligibility.items() if r["status"] == EVALUABLE_ASSET)
    excluded = {s: r for s, r in eligibility.items() if r["status"] != EVALUABLE_ASSET}
    return {
        "version": PROTOCOL_V2_VERSION,
        "previous_protocol": {"version": p1["version"], "protocol_sha256": V1_PROTOCOL_SHA256,
                              "manifest_sha256": V1_MANIFEST_SHA256, "status": "PRESERVED_UNCHANGED"},
        "change_type": "EXPLICIT_COVERAGE_POLICY_CHANGE",
        "change_reasons": [
            "original 87-asset universe fails predeclared per-asset minimum (>= 18 valid sessions): "
            + ", ".join(f"{s} {r['valid_sessions']}" for s, r in sorted(excluded.items())),
            "uniform objective asset eligibility policy applied to all assets; evaluable list frozen before reading "
            "holdout outcomes",
            "add D20 provider sensitivity (no effect on PASS/FAIL)",
            "add actual observed-availability mode based on first_seen (no effect on PASS/FAIL)"],
        "disclosure": {"original_87_asset_design_meets_coverage": False,
                       "generalization": "results generalize ONLY to the evaluable assets listed here, not to the "
                                         "original 87-asset universe",
                       "unverified_notes": {"KONTR": "possible non-continuous (single-price/auction-like) trading "
                                                     "method NOT verified from official BIST/KAP sources; not used as "
                                                     "a justification"}},
        "asset_eligibility_policy": {
            "rule": f"EVALUABLE iff valid prospective FULL sessions >= {MIN_VALID_SESSIONS}; valid session = 5m bars >= "
                    f"{ASSET_BAR_SHARE} x benchmark 5m bars that session (collector rule)",
            "applied_uniformly_to_all_assets": True, "not_evaluable_status": NOT_EVALUABLE_ASSET,
            "frozen_at_full_sessions": frozen_at_full_sessions},
        "original_universe": {"count": len(universe), "symbols": sorted(universe),
                              "sha256": cd.sha256_of(sorted(universe))},
        "evaluable_universe": {"count": len(evaluable), "symbols": evaluable, "sha256": cd.sha256_of(evaluable)},
        "excluded_assets": excluded,
        "asset_eligibility": eligibility,
        "coverage_requirements": {"min_asset_sessions_over_evaluable": MIN_ASSET_SESSIONS,
                                  "min_valid_sessions_per_evaluable_asset": MIN_VALID_SESSIONS},
        "label": p1["label"], "split": p1["split"], "primary_targets": p1["primary_targets"],
        "pass_rule": p1["pass_rule"], "multiple_rules": p1["multiple_rules"], "alert_unit": p1["alert_unit"],
        "rules": p1["rules"], "exploratory_reference": p1["exploratory_reference"],
        "metrics": p1["metrics"], "metric_definitions": p1["metric_definitions"],
        "stress_breakdowns": p1["stress_breakdowns"], "secondary_news_analysis": p1["secondary_news_analysis"],
        "modes": {
            MODE_A: {"role": "PRIMARY PASS/FAIL", "delay_minutes": 15,
                     "semantics": "collected bars under theoretical 15-minute provider delay; NOT evidence of "
                                  "real-time observation"},
            MODE_B: {"role": "SENSITIVITY ONLY; never changes PASS/FAIL", "delay_minutes": 20,
                     "semantics": "same rows visible 20 minutes after information time; does not guarantee actual "
                                  "provider delay; no best-delay selection"},
            MODE_C: {"role": "DESCRIPTIVE ONLY; never changes PASS/FAIL",
                     "semantics": "row usable only from max(first_seen) of every bar it depends on (bar_end <= "
                                  "information time, full history of each dependency); first-seen values only "
                                  "(revisions never applied); EOD-recovered bars visible only when first seen; rows "
                                  "visible after the session's last benchmark bar end are unusable",
                     "rule_dependencies": RULE_DEPENDENCIES,
                     "row_timely": f"visible - information_time <= {LIVE_TIMELY_MAX_MIN} min",
                     "asset_session_live_evaluable": f">= {LIVE_SESSION_ROW_SHARE} of its rows timely (all "
                                                     "dependencies incl. XU100 where required)",
                     "minimum": f">= {LIVE_MIN_ASSET_SESSIONS} live-evaluable asset-sessions per rule, else "
                                f"{NOT_EVALUABLE_LIVE}",
                     "scope": "probe-observed assets/time ranges reported separately; never generalized to all "
                              "evaluable assets"}},
        "latency": p1["latency"],
        "gate": {"future_holdout_full_sessions_min": pr.REQUIRED_FULL_SESSIONS,
                 "requires": ["frozen eligibility policy and evaluable list", "evaluable coverage", "raw hash "
                              "integrity", "AMD-001 + AMD-002 chain", "original snapshot integrity", "Label V2 SHA",
                              "protocol V1 + V2 SHA", "rule config SHA", "one-shot protection", "holdout not consumed",
                              "evaluation sessions and raw fingerprint identical between preflight and execution"]},
        "one_shot": p1["one_shot"], "forbidden": p1["forbidden"],
        "holdout_outcomes_read_at_creation": False,
    }


def freeze_v2(path: Path = MANIFEST_V2_PATH, payload: dict | None = None,
              now: datetime | None = None) -> tuple[dict, bool]:
    if payload is None:
        cov = collect_asset_coverage()
        payload = protocol_v2_payload(asset_eligibility(cov["valid_sessions"], cov["universe"],
                                                        len(cov["full_sessions"]), cov["median_bar_share"]),
                                      cov["universe"], cov["full_sessions"])
    if path.exists():
        m = load_v2(path)
        if m["protocol_sha256"] != cd.sha256_of(payload):
            raise ProtocolV2Error("protocol V2 already frozen with different content; a change needs V3")
        return m, False
    m = pr.build_manifest(payload, now or datetime.now(timezone.utc), pr.git_head())
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(m, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    return m, True


def load_v2(path: Path = MANIFEST_V2_PATH) -> dict:
    try:
        m = pr.load_manifest(path)
    except pr.ProtocolError as e:
        raise ProtocolV2Error(str(e)) from e
    p = m["protocol"]
    if p.get("version") != PROTOCOL_V2_VERSION or p["previous_protocol"]["protocol_sha256"] != V1_PROTOCOL_SHA256:
        raise ProtocolV2Error("not a V2 manifest chained to V1")
    return m


def v2_matches_code(m: dict) -> bool:
    """Dondurulmuş uygunluk verisinden V2 yükünü GÜNCEL kodla yeniden kurar; SHA aynı olmalı."""
    p = m["protocol"]
    rebuilt = protocol_v2_payload(p["asset_eligibility"], p["original_universe"]["symbols"],
                                  p["asset_eligibility_policy"]["frozen_at_full_sessions"])
    return cd.sha256_of(rebuilt) == m["protocol_sha256"]
