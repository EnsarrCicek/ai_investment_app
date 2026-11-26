"""Momentum FINAL prospektif holdout — dondurulmuş değerlendirme protokolü (sonuçlar OKUNMADAN önce sabitlendi).

* Birincil hedefler (HEPSİ gerekli; ağırlıklı skor / "neredeyse geçti" / sonradan eşik ayarı YOK):
  FPR <= 0.25, değerlendirilebilir recall >= 0.40, medyan görünür lead <= 0.50 (düşük = erken = iyi).
* Etiket: dondurulmuş MOMENTUM_EVENT_LABEL_V2 (SHA `LABEL_V2_SHA256`); Label V3 YOK.
* Birim: varlık-seans başına İLK nitelikli alarm (`first_watch_alert_per_asset_session`); aynı seanstaki tekrar
  aktivasyonlar alarm sayısını ŞİŞİRMEZ (yalnız teşhis olarak `activations_collapsed` raporlanır).
* Kurallar: yalnız holdout'tan ÖNCE var olan dondurulmuş/referans kurallar; artefakt/hash'ten birebir yeniden
  kurulamazsa `NOT_EVALUABLE_CONFIG_MISSING` (yaklaşık kurulum YOK). Pilot keşif mimarileri (A3/A4/A5d, sıralama,
  lojistik, GBM, iki aşamalı öncül) aday DEĞİLDİR; PASS/FAIL belirlemez.
* Holdout = pilot kesiminden (2026-10-30) sonraki FULL seanslar; değerlendirme kümesi = ilk 20 FULL holdout seansı
  (tarih sırası, sabit; erken/isteğe bağlı durdurma yok).
* Foreks haberleri YALNIZ ikincil açıklayıcı analiz; kullanılabilirlik = received_at (published_at ASLA).

Protokol yükü kanonik JSON → SHA-256. Manifest bir kez yazılır, DEĞİŞTİRİLMEZ; protokol değişikliği yeni sürüm
ister ve holdout açılmadan önce yapılmalıdır.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.research.momentum_final import candidate as cd

HERE = Path(__file__).parent
MANIFEST_PATH = HERE / "momentum_final_holdout_protocol.json"
STATE_DIR = HERE / "state"  # tek seferlik kayıtlar (yazma-bir-kez)

PROTOCOL_VERSION = "MOMENTUM_FINAL_HOLDOUT_PROTOCOL_V1"
LABEL_V2_SHA256 = "9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09"
PILOT_MANIFEST_SHA256 = "d7bb301233841ed278d041c15bd88103763dae3ebdd6f80115af082a8ac44dfd"
FROZEN_CANDIDATE_SHA256 = "a9f943dcb53c6ade6e2a30658ab547ab3bfe3930d5f5e93c2908db1a67cad881"
FROZEN_THRESHOLD = 5.094139728812382
ROUND1_FINAL_SHA256 = "00ae932221aa53ba7a94a6e258c30d3daeee855d153a6c0025cd6f7cad814fab"

HOLDOUT_START = "2026-11-02"
PILOT_CUTOFF = "2026-10-30"
REQUIRED_FULL_SESSIONS = 20
DELAY_MINUTES = 15  # Yahoo d15 görünürlüğü; sıfır gecikmeye ÇEVRİLMEZ
TARGETS = {"FPR": ["<=", 0.25], "evaluable_recall": [">=", 0.40], "median_visible_lead": ["<=", 0.50]}
ALERT_UNIT = "first_watch_alert_per_asset_session"

NOT_EVALUABLE = "NOT_EVALUABLE_CONFIG_MISSING"
EVALUABLE = "EVALUABLE"
EXPLORATORY_NOT_INCLUDED = ("A3", "A4", "A5d", "ranking_policies", "logistic", "GBM", "two_stage_precursor")

NEWS_WINDOWS_MIN = (15, 30, 60)
NEWS_MAX_FETCH_GAP_MIN = 15
NEWS_NOT_OBSERVED = "NEWS_NOT_OBSERVED"
NO_NEWS = "NO_NEWS"
NEWS_PRESENT = "NEWS_PRESENT"

OPENING_PERIOD_END = "10:30"  # Europe/Istanbul; olay başlangıcı bundan önceyse OPENING_PERIOD
BROAD_MARKET_EVENT_SHARE = 0.30  # o tarihte en az bir V2 olaylı varlık-seans payı >= 0.30 → BROAD_MARKET


class ProtocolError(RuntimeError):
    pass


# ------------------------------------------------------------------ kurallar (artefakttan birebir)
def _frozen_candidate() -> dict:
    from app.research.momentum_final import experiment as mf
    m = cd.load_frozen(mf.MANIFEST)  # SHA kendi içinde doğrulanır
    c = m["candidate"]
    if m["sha256"] != FROZEN_CANDIDATE_SHA256:
        raise ProtocolError(f"frozen candidate SHA {m['sha256']} != {FROZEN_CANDIDATE_SHA256}")
    if not (c["feature"] == "rel_ret_z_3" and c["threshold"] == FROZEN_THRESHOLD and c["confirmation"] == [1, 1]
            and c["interval"] == "5m" and c["benchmark"] == "XU100" and c["provider_delay_minutes"] == DELAY_MINUTES):
        raise ProtocolError("frozen candidate content differs from protocol reference")
    return {"rule_id": "C_FROZEN_REL_RET_Z3_1OF1_D15", "label": "C) frozen feasibility relative-return rule",
            "definition": {"feature": c["feature"], "comparison": c["comparison"], "threshold": c["threshold"],
                           "confirmation": c["confirmation"], "interval": c["interval"],
                           "benchmark": c["benchmark"], "provider_delay_minutes": c["provider_delay_minutes"],
                           "status_gate": c["status_gate"], "missing_feature_policy": c["missing_feature_policy"]},
            "source_artifact": "momentum_final/frozen_candidate.json", "source_sha256": m["sha256"]}


def _round1(level: str) -> dict:
    from app.research.momentum_calibration import experiment as r1x
    from app.research.momentum_feasibility import experiment as fx
    from app.research.momentum_round2 import experiment as r2
    got = r1x.config_hash(r2.ROUND1_FINAL)
    if got != ROUND1_FINAL_SHA256 or r2.ROUND1_FINAL_SHA != ROUND1_FINAL_SHA256:
        raise ProtocolError(f"Round 1 final config hash {got} != {ROUND1_FINAL_SHA256}")
    rule = fx.R1_FINAL_WATCH if level == "WATCH" else fx.R1_FINAL_STRONG
    return {"rule_id": f"{'A' if level == 'WATCH' else 'B'}_ROUND1_FINAL_{level}_3OF3_D15",
            "label": f"{'A' if level == 'WATCH' else 'B'}) existing Round 1 {level}",
            "definition": {"level": level, "raw_rule": dict(rule), "confirmation": [3, 3],
                           "round1_engine_config_sha256": got, "provider_delay_minutes": DELAY_MINUTES},
            "source_artifact": "momentum_round2.experiment.ROUND1_FINAL / momentum_feasibility.experiment",
            "source_sha256": got}


RULE_BUILDERS = {"A_ROUND1_FINAL_WATCH_3OF3_D15": lambda: _round1("WATCH"),
                 "B_ROUND1_FINAL_STRONG_3OF3_D15": lambda: _round1("STRONG"),
                 "C_FROZEN_REL_RET_Z3_1OF1_D15": _frozen_candidate}


def resolve_rules(builders: dict | None = None) -> list[dict]:
    """Her kural birebir yeniden kurulur; kurulamazsa NOT_EVALUABLE_CONFIG_MISSING (yaklaşım YOK)."""
    out = []
    for rid, build in (builders or RULE_BUILDERS).items():
        try:
            r = build()
            if r["rule_id"] != rid:
                raise ProtocolError(f"rule id mismatch {r['rule_id']} != {rid}")
            out.append({**r, "status": EVALUABLE, "config_sha256": cd.sha256_of(r["definition"])})
        except Exception as e:  # eksik/bozuk artefakt → değerlendirilemez, tahmin edilmez
            out.append({"rule_id": rid, "status": NOT_EVALUABLE, "reason": f"{type(e).__name__}: {e}"[:300]})
    return out


# ------------------------------------------------------------------ protokol yükü
def protocol_payload(rules: list[dict] | None = None) -> dict:
    rules = resolve_rules() if rules is None else rules
    return {
        "version": PROTOCOL_VERSION,
        "label": {"version": "MOMENTUM_EVENT_LABEL_V2", "sha256": LABEL_V2_SHA256,
                  "unchanged": ["swing definition", "event start", "peak definition", "non-overlap logic",
                                "evaluable definition", "PRE_OBSERVATION handling", "IN_EVENT", "IN_EVENT_DUPLICATE",
                                "PRE_EVENT", "POST_PEAK", "NO_EVENT"]},
        "split": {"pilot_manifest_sha256": PILOT_MANIFEST_SHA256, "pilot_cutoff_session": PILOT_CUTOFF,
                  "holdout_start": HOLDOUT_START, "full_session_definition": "collector integrity.classify_sessions",
                  "evaluation_sessions": f"first {REQUIRED_FULL_SESSIONS} FULL holdout sessions in date order"},
        "gate": {"future_holdout_full_sessions_min": REQUIRED_FULL_SESSIONS,
                 "requires": ["archive integrity OK", "required raw files exist and hash-valid",
                              "Label V2 fingerprint matches", "protocol manifest fingerprint matches",
                              "no previous final evaluation start or completion record"]},
        "primary_targets": TARGETS,
        "pass_rule": "PASS iff ALL primary targets met; missing metric = FAIL; no weighted score; no 'almost pass'; "
                     "no post-hoc threshold change",
        "multiple_rules": "each rule PASS/FAIL independently; holdout is NOT model selection; best rule is NOT "
                          "promoted to a new candidate; if none pass, current OHLCV architectures do not satisfy "
                          "the target",
        "alert_unit": {"primary": ALERT_UNIT,
                       "repeated_activations": "collapsed to the first alert per asset-session; never inflate "
                                               "alert counts (activation count reported as diagnostic only)"},
        "rules": rules,
        "exploratory_reference": {"status": "NOT INCLUDED (definitions not frozen as candidates before holdout)",
                                  "architectures": list(EXPLORATORY_NOT_INCLUDED), "affects_pass_fail": False},
        "latency": {"yahoo": f"d{DELAY_MINUTES} visible time per established provider visibility semantics; never "
                             "converted to zero latency",
                    "foreks": "availability = received_at; published_at never used for availability; "
                              "published_at->received_at archival discovery lag reported separately"},
        "metrics": ["evaluable_events", "primary_alerts", "TP", "FP", "precision", "raw_recall", "evaluable_recall",
                    "non_event_sessions", "FPR", "median_visible_lead", "lead_le_0_50_share",
                    "pre_observation_events", "post_peak_alerts", "duplicate_alerts", "alarm_density_per_session"],
        "metric_definitions": {"TP": "primary alerts classified IN_EVENT or IN_EVENT_DUPLICATE (Label V2)",
                               "FP": "primary alerts - TP", "FPR": "non-event asset-sessions with >=1 primary alert "
                                                                   "/ non-event asset-sessions",
                               "median_visible_lead": "Label V2 median_lead_v2 over caught events at d15",
                               "alarm_density_per_session": "primary alerts / asset-sessions per session date"},
        "stress_breakdowns": {
            "normal_sessions": f"session dates with V2-event asset-session share < {BROAD_MARKET_EVENT_SHARE}",
            "broad_market_high_participation_sessions": f"share >= {BROAD_MARKET_EVENT_SHARE}",
            "opening_period_events": f"event start < {OPENING_PERIOD_END} Europe/Istanbul",
            "intraday_events": f"event start >= {OPENING_PERIOD_END} Europe/Istanbul",
            "yahoo_latency_lost_events": f"evaluable events with peak - start < {DELAY_MINUTES} min (uncatchable "
                                         "at d15)"},
        "secondary_news_analysis": {
            "role": "DESCRIPTIVE ONLY; never tunes OHLCV rules; no news threshold/classifier/candidate",
            "source": "Foreks prospective archive (momentum_secondary.news_events canonical rows)",
            "fields": ["published_at", "received_at", "symbol", "event_type", "source revision state"],
            "company_specific": "symbol == asset (UNRESOLVED excluded)",
            "windows_minutes": list(NEWS_WINDOWS_MIN),
            "availability": "received_at in (observation - window, observation]",
            "observation_points": {"event": "V2 event start", "alert": "primary alert visible time (d15)"},
            "eligibility": f"NEWS-ELIGIBLE only if Foreks collector operational for the whole window: completed "
                           f"fetches with consecutive gaps <= {NEWS_MAX_FETCH_GAP_MIN} min covering it and window "
                           f"after first prospective fetch; otherwise {NEWS_NOT_OBSERVED} (never {NO_NEWS})",
            "strata": ["event_type == other", "event_type != other"],
            "revisions": "SOURCE_REVISION_NEW / SOURCE_REVISION_KNOWN / STORAGE_CONFLICT semantics; one logical "
                         "catalyst per (provider, item_key, symbol); revisions never add catalysts",
            "allowed_statements": ["X% of evaluable events had prospectively received company-specific news within "
                                   "60 minutes", "news-observed events had descriptive lead distribution Y"]},
        "one_shot": {"pre_execution_record": "write-once: protocol SHA, Label V2 SHA, amendment chain status, "
                                             "eligible sessions, raw input fingerprints, code HEAD, timestamp",
                     "completion_marker": "FINAL_HOLDOUT_CONSUMED",
                     "rerun_label": "REANALYSIS_OF_CONSUMED_HOLDOUT (never used for candidate selection)"},
        "forbidden": ["threshold tuning", "model training", "candidate selection", "Pilot-2", "Label V3",
                      "news-based candidate"],
    }


def git_head(repo: Path | None = None) -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo or HERE, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def build_manifest(payload: dict, created_at: datetime, head: str | None) -> dict:
    body = {"protocol": payload, "protocol_sha256": cd.sha256_of(payload),
            "created_at": created_at.isoformat(), "git_head": head}
    return {**body, "manifest_sha256": cd.sha256_of(body)}


def freeze_manifest(path: Path = MANIFEST_PATH, payload: dict | None = None,
                    now: datetime | None = None) -> tuple[dict, bool]:
    """Yazma-bir-kez. Dosya varsa yeniden yazılmaz; yalnız doğrulanır (aynı protokol değilse HATA)."""
    payload = protocol_payload() if payload is None else payload
    if path.exists():
        m = load_manifest(path)
        if m["protocol_sha256"] != cd.sha256_of(payload):
            raise ProtocolError("protocol manifest already frozen with different content; a change requires a new "
                                "protocol version before the holdout is opened")
        return m, False
    m = build_manifest(payload, now or datetime.now(timezone.utc), git_head())
    with path.open("x", encoding="utf-8") as f:  # yarış/üzerine yazma yok
        f.write(json.dumps(m, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    return m, True


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.exists():
        raise ProtocolError("protocol manifest missing")
    m = json.loads(path.read_text(encoding="utf-8"))
    body = {k: m[k] for k in ("protocol", "protocol_sha256", "created_at", "git_head")}
    if cd.sha256_of(m["protocol"]) != m["protocol_sha256"] or cd.sha256_of(body) != m["manifest_sha256"]:
        raise ProtocolError("protocol manifest corrupted (SHA mismatch)")
    return m


def manifest_matches_code(m: dict, payload: dict | None = None) -> bool:
    payload = protocol_payload() if payload is None else payload
    return m["protocol_sha256"] == cd.sha256_of(payload)
