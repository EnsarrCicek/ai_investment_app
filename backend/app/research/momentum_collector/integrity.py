"""Toplayıcı bütünlük denetimleri ve veri kümesi durumu (YALNIZ araştırma; sonuç/PASS-FAIL üretmez)."""

from __future__ import annotations

from datetime import date, time

import pandas as pd

from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector.storage import APPEND_ONLY, Archive

FULL_FIRST_BAR_MAX = time(10, 5)
FULL_LAST_BAR_MIN = time(17, 50)
ASSET_BAR_SHARE = 0.80
READY = "DATASET READY FOR PROSPECTIVE AUDIT"


def verify_label() -> dict:
    sha = mm.verified_label_sha()
    return {"label_manifest_sha256": sha, "sha_length": len(sha), "manifest_canonical": True, "freeze_valid": True}


def verify_study_manifest(m: dict) -> dict:
    c = m["config"]
    checks = {
        "sha_matches": mm.manifest_sha(c) == m["sha256"],
        "label_sha_matches_frozen_label": c["label_manifest_sha256"] == mm.verified_label_sha(),
        "universe_sha_matches": c["universe_sha256"] == mm.universe_sha256(c["universe"]),
        "universe_sorted_unique": c["universe"] == sorted(set(c["universe"])),
        "universe_unchanged": c["universe"] == mm.primary_universe(),
        "coverage_fields_present": all(k in c for k in ("minimum_full_sessions", "target_sessions",
                                                        "minimum_asset_sessions",
                                                        "minimum_sessions_per_primary_asset")),
        "ktlev_not_primary": "KTLEV" not in c["universe"],
        "benchmark_not_primary": c["benchmark"] not in c["universe"],
        "start_after_consumed_final": (c["prospective_start_session"] is None
                                       or date.fromisoformat(c["prospective_start_session"])
                                       > mm.CONSUMED_FINAL_RANGE[1]),
    }
    return {"ok": all(checks.values()), **checks}


def verify_archive(a: Archive, m: dict | None = None) -> dict:
    db = a.db
    trig = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    need = {f"{t}_no_{op}" for t in APPEND_ONLY for op in ("update", "delete")}
    checks = {
        "sqlite_integrity": db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
        "append_only_triggers": need <= trig,
        "no_partial_in_bars": db.execute("SELECT COUNT(*) FROM bars WHERE is_partial != 0").fetchone()[0] == 0,
        "unique_keys": db.execute("SELECT COUNT(*) FROM (SELECT symbol, interval, bar_start_ns, COUNT(*) c FROM bars "
                                  "GROUP BY 1,2,3 HAVING c > 1)").fetchone()[0] == 0,
        "first_seen_not_before_bar_end": db.execute("SELECT COUNT(*) FROM bars WHERE first_seen_ns < bar_end_ns"
                                                    ).fetchone()[0] == 0,
        "preflight_isolated": (db.execute("SELECT COUNT(*) FROM bars WHERE data_phase='PREFLIGHT'").fetchone()[0] == 0
                               if a.role == "primary" else
                               db.execute("SELECT COUNT(*) FROM bars WHERE data_phase!='PREFLIGHT'").fetchone()[0]
                               == 0),
    }
    if m is not None and m["config"]["manifest_status"] == mm.FINAL:
        start = m["config"]["prospective_start_session"]
        checks["prospective_rows_on_or_after_start"] = db.execute(
            "SELECT COUNT(*) FROM bars WHERE data_phase='PROSPECTIVE' AND session_date < ?", (start,)).fetchone()[0] == 0
    return {"ok": all(checks.values()), **checks}


def classify_sessions(a: Archive, benchmark: str = mm.BENCHMARK) -> pd.DataFrame:
    """Gözlenen gösterge 5m barlarından seans sınıfı: FULL / SHORT_SESSION (yarım gün varsayımı yok)."""
    df = pd.read_sql_query("SELECT session_date, MIN(bar_start_local) first, MAX(bar_start_local) last, COUNT(*) n "
                           "FROM bars WHERE symbol=? AND interval='5m' GROUP BY session_date ORDER BY session_date",
                           a.db, params=(benchmark,))
    if df.empty:
        return df.assign(session_class=[])
    first = pd.to_datetime(df["first"].str[:19]).dt.time
    last = pd.to_datetime(df["last"].str[:19]).dt.time
    df["session_class"] = ["FULL" if f <= FULL_FIRST_BAR_MAX and lt >= FULL_LAST_BAR_MIN else "SHORT_SESSION"
                           for f, lt in zip(first, last)]
    return df


def coverage_verdict(full_sessions: int, per_asset: dict[str, int], config: dict) -> dict:
    """Saf kapsam kararı (sonuç/PASS-FAIL değil). `per_asset`: birincil varlık → geçerli seans sayısı; evrende olup
    sözlükte olmayan varlık 0 sayılır (eksik veri doldurulmaz, varlık evrenden düşmez)."""
    counts = {s: int(per_asset.get(s, 0)) for s in config["universe"]}
    total = sum(counts.values())
    short = sorted(s for s, n in counts.items() if n < config["minimum_sessions_per_primary_asset"])
    checks = {"full_sessions": full_sessions >= config["minimum_full_sessions"],
              "asset_sessions": total >= config["minimum_asset_sessions"],
              "per_asset_minimum": not short}
    ready = all(checks.values())
    return {"status": READY if ready else f"COLLECTING ({full_sessions}/{config['minimum_full_sessions']} full "
                                          f"sessions)",
            "full_sessions": full_sessions, "asset_sessions": total,
            "minimum_full_sessions": config["minimum_full_sessions"],
            "minimum_asset_sessions": config["minimum_asset_sessions"],
            "minimum_sessions_per_primary_asset": config["minimum_sessions_per_primary_asset"],
            "assets_below_minimum": len(short), "min_sessions_any_asset": min(counts.values()) if counts else 0,
            "checks": checks}


def dataset_status(a: Archive, m: dict) -> dict:
    c = m["config"]
    if c["manifest_status"] != mm.FINAL:
        return {"status": "NOT STARTED (manifest DRAFT)", "full_sessions": 0, "asset_sessions": 0}
    rows = a.validation_rows(m, "5m")
    sess = classify_sessions(a, c["benchmark"])
    full = set(sess.loc[(sess["session_class"] == "FULL") & (sess["session_date"] >= c["prospective_start_session"]),
                        "session_date"]) if len(sess) else set()
    full = {d for d in full if not mm.in_consumed_final(date.fromisoformat(d))}
    per_asset: dict[str, int] = {}
    if len(rows) and full:
        bench = rows[rows["symbol"] == c["benchmark"]].groupby("session_date").size()
        per = rows[rows["symbol"].isin(c["universe"]) & rows["session_date"].isin(full)].groupby(
            ["symbol", "session_date"]).size()
        for (sym, d), n in per.items():
            if n >= ASSET_BAR_SHARE * bench.get(d, 0):
                per_asset[sym] = per_asset.get(sym, 0) + 1
    return coverage_verdict(len(full), per_asset, c)
