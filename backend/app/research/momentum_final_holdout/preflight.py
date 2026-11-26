"""Final holdout ÖN KONTROLÜ (preflight) — dondurulmuş protokol kapısına EK, fail-closed denetimler.

Dondurulmuş protokol/manifest DEĞİŞMEZ; bu modül yalnız ek şartları denetler ve `evaluator.execute` bunlardan biri
bile sağlanmazsa yükleyicileri ÇAĞIRMAZ. Yalnız toplama META verisi okunur (seans sınıfı, bar sayıları, ham dosya
hash'leri, değişiklik zinciri, snapshot, manifest/kural SHA'ları). Holdout fiyat/etiket/olay/alarm/metrik OKUNMAZ.

Kapsam iki ayrı raporlanır: (a) önceden ilan edilmiş VERİ SETİ kapsamı (toplayıcı manifesti: tüm prospektif FULL
seanslar; >= 1566 varlık-seans, her birincil varlık >= 18 geçerli seans) — KAPI; (b) yalnız holdout dönemi kapsamı —
yalnız RAPOR (önceden ilan edilmiş eşiği yoktur, kapı olarak kullanılmaz).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.research.momentum_final import candidate as cd
from app.research.momentum_final_holdout import protocol as pr

PREFLIGHT_VERSION = "MOMENTUM_FINAL_HOLDOUT_PREFLIGHT_V1"
READY = "FINAL_HOLDOUT_PREFLIGHT_READY"
BLOCKED = "FINAL_HOLDOUT_PREFLIGHT_BLOCKED"
ORIGINAL_SNAPSHOT_SHA256 = "6d4e814b18f14e930fa4f08d2913ccd9e8a6d57bba0c056a0c03fb4b87b11163"
ORIGINAL_SNAPSHOT_FILE_SHA256 = "b6c3c52ebcad125d56953eb3ebe9d2def4dfb5eb06d722fd2e4c2f2613eb1efb"
EXPECTED_AMENDMENTS = ("AMD-001-EOD-PROBE-VALIDATION-RACE", "AMD-002-EOD-RECOVERY-SESSION-IDENTITY")
EXPECTED_PROTOCOL_SHA256 = "39be406f16cfcc0e94c869a4bb385638c77bc90aec665c0ab97671036d7a5d32"
MIN_ASSET_SESSIONS = 1566  # toplayıcı manifesti (önceden ilan edilmiş)
MIN_SESSIONS_PER_ASSET = 18  # toplayıcı manifesti (önceden ilan edilmiş)


def check(state: dict, *, manifest_path: Path = pr.MANIFEST_PATH, state_dir: Path = pr.STATE_DIR,
          payload: dict | None = None, live_rules: list[dict] | None = None, reanalysis: bool = False) -> dict:
    """Saf karar: her şart ayrı; biri bile sağlanmazsa BLOCKED. Eksik alan = sağlanmadı (fail closed)."""
    cov = state.get("dataset_coverage") or {}
    checks = {
        "holdout_full_sessions_ge_20": len(state.get("holdout_sessions") or []) >= pr.REQUIRED_FULL_SESSIONS,
        "dataset_asset_sessions_ge_1566": (cov.get("asset_sessions") or 0) >= MIN_ASSET_SESSIONS
        and cov.get("minimum_asset_sessions") == MIN_ASSET_SESSIONS,
        "every_primary_asset_ge_18_sessions": cov.get("minimum_sessions_per_primary_asset") == MIN_SESSIONS_PER_ASSET
        and cov.get("assets_below_minimum") == 0 and (cov.get("min_sessions_any_asset") or 0) >= MIN_SESSIONS_PER_ASSET,
        "archive_integrity": state.get("archive_integrity") is True,
        "amendment_chain_valid": state.get("amendment_chain_valid") is True
        and tuple(state.get("amendments") or ()) == EXPECTED_AMENDMENTS and not state.get("unapproved_changes"),
        "original_snapshot_intact": state.get("snapshot_sha256") == ORIGINAL_SNAPSHOT_SHA256
        and state.get("snapshot_file_sha256") == ORIGINAL_SNAPSHOT_FILE_SHA256,
        "raw_hash_integrity": (state.get("raw_requests") or 0) > 0 and state.get("raw_missing") == 0
        and state.get("raw_invalid") == 0,
        "label_v2_sha": state.get("label_v2_sha256") == pr.LABEL_V2_SHA256,
    }
    try:
        m = pr.load_manifest(manifest_path)
        checks["protocol_sha"] = m["protocol_sha256"] == EXPECTED_PROTOCOL_SHA256 if payload is None else True
        checks["protocol_matches_code"] = pr.manifest_matches_code(m, payload)
        live = {r["rule_id"]: r for r in (live_rules if live_rules is not None else pr.resolve_rules())}
        frozen = m["protocol"]["rules"]
        checks["frozen_rule_config_sha"] = bool(frozen) and all(
            r["status"] == pr.EVALUABLE and live.get(r["rule_id"], {}).get("status") == pr.EVALUABLE
            and live[r["rule_id"]].get("config_sha256") == r["config_sha256"] for r in frozen)
    except (pr.ProtocolError, KeyError) as e:
        checks.update(protocol_sha=False, protocol_matches_code=False, frozen_rule_config_sha=False)
        state = {**state, "_protocol_error": str(e)}
    consumed = (Path(state_dir) / "FINAL_HOLDOUT_CONSUMED").exists()
    started = (Path(state_dir) / "FINAL_HOLDOUT_STARTED.json").exists()
    checks["holdout_not_consumed"] = consumed if reanalysis else not (consumed or started)
    failed = [k for k, ok in checks.items() if not ok]
    return {"version": PREFLIGHT_VERSION, "status": READY if not failed else BLOCKED, "open": not failed,
            "checks": checks, "failed": failed, "coverage_dataset": cov,
            "coverage_holdout_only_report": state.get("holdout_coverage"),
            "protocol_error": state.get("_protocol_error")}


def collect_state() -> dict:
    """Salt-okunur meta veri toplama (fiyat/etiket/sonuç YOK)."""
    from collections import Counter

    from app.research.momentum_collector import amendments as am
    from app.research.momentum_collector import integrity as ig
    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_collector import snapshot as sn
    from app.research.momentum_label_v2 import experiment as lx
    from app.research.momentum_pilot import split as sp
    m = mm.load()
    c = m["config"]
    cutoff = sp.load_manifest()["manifest"]["pilot_cutoff_session"]
    a = am.readonly_archive()
    try:
        sess = ig.classify_sessions(a, c["benchmark"])
        full = sp.observed_full_sessions(sess, c["prospective_start_session"])
        hold = [d for d in full if d > cutoff and d >= pr.HOLDOUT_START]
        cov = ig.dataset_status(a, m)
        rows = a.validation_rows(m, "5m")
        bench = rows[rows["symbol"] == c["benchmark"]].groupby("session_date").size()
        per = rows[rows["symbol"].isin(c["universe"]) & rows["session_date"].isin(hold)].groupby(
            ["symbol", "session_date"]).size()
        valid = Counter(s for (s, d), n in per.items() if n >= ig.ASSET_BAR_SHARE * bench.get(d, 0))
        counts = {s: valid.get(s, 0) for s in c["universe"]}
        integ = ig.verify_archive(a, m)["ok"]
        reqs = a.db.execute("SELECT raw_path, response_hash FROM requests").fetchall()
        missing = sum(1 for p, _ in reqs if not p or not (a.root / p).exists())
        invalid = sum(1 for p, h in reqs if p and (a.root / p).exists() and not a.raw_hash_valid(p, h))
    finally:
        a.db.close()
    snap = sn.load()
    chain = am.verify_chain(snap)
    return {"holdout_sessions": hold, "dataset_coverage": cov,
            "holdout_coverage": {"holdout_full_sessions": len(hold), "asset_sessions": sum(counts.values()),
                                 "assets_with_all_holdout_sessions": sum(n == len(hold) for n in counts.values()),
                                 "assets_with_zero": sorted(s for s, n in counts.items() if n == 0),
                                 "note": "report only; no predeclared holdout-only threshold"},
            "archive_integrity": bool(integ), "raw_requests": len(reqs), "raw_missing": missing,
            "raw_invalid": invalid, "amendment_chain_valid": chain["approved_amendment_chain_valid"],
            "amendments": chain["amendments"], "unapproved_changes": chain["unapproved_changes"],
            "snapshot_sha256": snap["snapshot_sha256"],
            "snapshot_file_sha256": hashlib.sha256(sn.SNAPSHOT_PATH.read_bytes()).hexdigest(),
            "label_v2_sha256": lx.load_manifest()["sha256"]}


def run(reanalysis: bool = False) -> dict:
    return check(collect_state(), reanalysis=reanalysis)


def fingerprint(result: dict) -> str:
    return cd.sha256_of({k: result[k] for k in ("version", "status", "checks")})


# ------------------------------------------------------------------ protokol V2 ön kontrolü
def check_v2(state: dict, *, v1_path: Path = pr.MANIFEST_PATH, v2_path: Path | None = None,
             state_dir: Path = pr.STATE_DIR, live_rules: list[dict] | None = None, reanalysis: bool = False) -> dict:
    """V2 şartları (her biri ayrı, eksik alan = sağlanmadı). Uygunluk listesi V2 manifestinden; kapsam yalnız
    dondurulmuş EVALUABLE varlıklar üzerinden."""
    from app.research.momentum_final_holdout import protocol_v2 as p2
    v2_path = p2.MANIFEST_V2_PATH if v2_path is None else v2_path
    checks, info = {}, {}
    checks["holdout_full_sessions_ge_20"] = len(state.get("holdout_sessions") or []) >= pr.REQUIRED_FULL_SESSIONS
    evaluable, v2 = [], None
    try:
        v2 = p2.load_v2(v2_path)
        evaluable = list(v2["protocol"]["evaluable_universe"]["symbols"])
        checks["eligibility_policy_frozen"] = bool(evaluable) and p2.v2_matches_code(v2)
        info["protocol_v2_sha256"] = v2["protocol_sha256"]
    except (p2.ProtocolV2Error, pr.ProtocolError, KeyError) as e:
        checks["eligibility_policy_frozen"] = False
        info["protocol_v2_error"] = str(e)
    vs = state.get("valid_sessions") or {}
    per = {s: int(vs.get(s, 0)) for s in evaluable}
    checks["evaluable_coverage"] = bool(per) and min(per.values()) >= p2.MIN_VALID_SESSIONS \
        and sum(per.values()) >= p2.MIN_ASSET_SESSIONS
    info["evaluable_asset_sessions"] = sum(per.values())
    info["evaluable_min_valid_sessions"] = min(per.values()) if per else None
    checks["archive_integrity"] = state.get("archive_integrity") is True
    checks["raw_hash_integrity"] = (state.get("raw_requests") or 0) > 0 and state.get("raw_missing") == 0 \
        and state.get("raw_invalid") == 0 and bool(state.get("raw_fingerprint"))
    checks["amendment_chain_valid"] = state.get("amendment_chain_valid") is True \
        and tuple(state.get("amendments") or ()) == EXPECTED_AMENDMENTS and not state.get("unapproved_changes")
    checks["original_snapshot_intact"] = state.get("snapshot_sha256") == ORIGINAL_SNAPSHOT_SHA256 \
        and state.get("snapshot_file_sha256") == ORIGINAL_SNAPSHOT_FILE_SHA256
    checks["label_v2_sha"] = state.get("label_v2_sha256") == pr.LABEL_V2_SHA256
    try:
        m1 = pr.load_manifest(v1_path)
        checks["protocol_v1_sha"] = m1["protocol_sha256"] == EXPECTED_PROTOCOL_SHA256 and pr.manifest_matches_code(m1)
        live = {r["rule_id"]: r for r in (live_rules if live_rules is not None else pr.resolve_rules())}
        frozen = m1["protocol"]["rules"]
        same_v2 = v2 is not None and v2["protocol"]["rules"] == frozen
        checks["rule_config_sha"] = same_v2 and bool(frozen) and all(
            r["status"] == pr.EVALUABLE and live.get(r["rule_id"], {}).get("config_sha256") == r["config_sha256"]
            for r in frozen)
    except (pr.ProtocolError, KeyError) as e:
        checks["protocol_v1_sha"] = checks["rule_config_sha"] = False
        info["protocol_v1_error"] = str(e)
    checks["protocol_v2_sha"] = v2 is not None and v2["protocol"]["previous_protocol"]["protocol_sha256"] \
        == EXPECTED_PROTOCOL_SHA256
    consumed = (Path(state_dir) / "FINAL_HOLDOUT_CONSUMED").exists()
    started = (Path(state_dir) / "FINAL_HOLDOUT_STARTED.json").exists()
    checks["one_shot_not_consumed"] = consumed if reanalysis else not (consumed or started)
    failed = [k for k, ok in checks.items() if not ok]
    return {"version": PREFLIGHT_VERSION + "+V2", "status": READY if not failed else BLOCKED, "open": not failed,
            "checks": checks, "failed": failed, "info": info, "evaluable": evaluable,
            "excluded": sorted(v2["protocol"]["excluded_assets"]) if v2 else None,
            "holdout_sessions": sorted(state.get("holdout_sessions") or [])[:pr.REQUIRED_FULL_SESSIONS],
            "raw_fingerprint": state.get("raw_fingerprint")}


def collect_state_v2() -> dict:
    """`collect_state` + varlık başına geçerli seans ve holdout dönemi ham parmak izi (evaluator ile AYNI tanım)."""
    from app.research.momentum_final_holdout import evaluator as ev
    from app.research.momentum_final_holdout import protocol_v2 as p2
    s = collect_state()
    g = ev.collect_gate_state()
    s["valid_sessions"] = p2.collect_asset_coverage()["valid_sessions"]
    s["raw_fingerprint"] = g["raw_fingerprint"]
    return s


def run_v2(reanalysis: bool = False) -> dict:
    return check_v2(collect_state_v2(), reanalysis=reanalysis)
