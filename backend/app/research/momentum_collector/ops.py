"""Zamanlanmış toplama işletimi — Windows Görev Zamanlayıcı için tek seferlik, çökme güvenli çalıştırmalar
(YALNIZ araştırma; sonuç/model/PASS-FAIL YOK).

* Tekil kilit: işletim sistemi dosya kilidi (Windows `msvcrt.locking`, POSIX `flock`). Süreç ölünce kilit OS
  tarafından bırakılır → bayat kilit dosyası bir sonraki çalıştırmayı engellemez. Kilit tutuluyorsa yeni çağrı
  veri yazmaz, `SKIPPED_ALREADY_RUNNING` loglar, çıkış kodu 0.
* Başlangıç sınırı: yerel tarih < prospective_start_session → hiçbir depo açılmaz (`SKIPPED_BEFORE_START`).
* Sonda yalnız hafta içi 09:55–18:30 (`SKIPPED_OUTSIDE_WINDOW`; gecikmeli başlatmada bile).
* EOD: aynı gün doğrulanmış ve sembol hatası olmayan bir EOD varsa sonraki tetiklemeler `SKIPPED_ALREADY_COMPLETED`;
  aksi halde yeniden çalışır (idempotent). Sonrasında hafif bütünlük denetimi; hata → çıkış 2 (yeniden deneme).
* Loglar Git dışı `store/logs/` altında JSON satırları; gizli bilgi yazılmaz.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import collector as col
from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import snapshot as sn
from app.research.momentum_collector import storage as st
from app.research.momentum_collector import visibility_probe as vp

LOG_DIR = st.STORE / "logs"
LOCK_DIR = st.STORE / "locks"
GAP_DAYS = 5  # 1m saklama ~7 gün; EOD period=5d → 5 günden uzun kesinti = veri kaybı riski
EXIT_OK, EXIT_ERROR, EXIT_INTEGRITY, EXIT_PARTIAL = 0, 1, 2, 3


class AlreadyRunning(RuntimeError):
    pass


class SingletonLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.f = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            raise AlreadyRunning(str(self.path)) from None
        self.f = f
        holder = self.path.with_suffix(".holder")
        holder.write_text(json.dumps({"pid": os.getpid(), "since": datetime.now(timezone.utc).isoformat()}),
                          encoding="utf-8")
        return self

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()
        return False


def log_line(log_dir: Path, name: str, record: dict) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str, sort_keys=True) + "\n")
    return path


def _local(now: datetime) -> datetime:
    return now.astimezone(ISTANBUL_TZ)


def eod_already_ok(a: st.Archive, day: date) -> bool:
    rows = a.db.execute("SELECT r.started_at, r.summary FROM runs r JOIN eod_verifications v ON v.run_id = r.run_id "
                        "WHERE r.mode='EOD' AND r.status='COMPLETED' AND v.ok=1").fetchall()
    for started, summary in rows:
        if _local(datetime.fromisoformat(started)).date() == day and not json.loads(summary)["symbols_failed"]:
            return True
    return False


def verify_after_eod(a: st.Archive, m: dict, run_id: str, now: datetime, snap: dict) -> dict:
    """Hafif EOD sonrası denetim (sonuç değil): SQLite, çalıştırma tamam, ham hash'ler, kısmi bar yok, gelecekte
    first_seen yok, manifest/etiket/evren SHA'ları değişmemiş."""
    status = a.db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
    reqs = a.db.execute("SELECT raw_path, response_hash FROM requests WHERE run_id=?", (run_id,)).fetchall()
    base = ig.verify_archive(a, m)
    checks = {"sqlite_integrity": base["sqlite_integrity"], "run_completed": bool(status) and status[0] == "COMPLETED",
              "raw_hashes_valid": all(a.raw_hash_valid(p, h) for p, h in reqs),
              "no_partial_in_bars": base["no_partial_in_bars"],
              "no_future_first_seen": a.db.execute("SELECT COUNT(*) FROM bars WHERE first_seen_ns > ?",
                                                   (st.ts_ns(now),)).fetchone()[0] == 0,
              "append_only_triggers": base["append_only_triggers"],
              **{k: v for k, v in sn.anchors(m, snap).items() if k != "ok"}}
    out = {"ok": all(checks.values()), **checks}
    a.db.execute("INSERT INTO eod_verifications(run_id, verified_at, ok, details) VALUES (?,?,?,?)",
                 (run_id, now.astimezone(timezone.utc).isoformat(), int(out["ok"]), json.dumps(out, sort_keys=True)))
    return out


def scheduled_run(kind: str, *, source_factory: Callable[[], col.CollectorSource] = col.YahooCollectorSource,
                  now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                  manifest_path: Path = mm.MANIFEST_PATH, snapshot_path: Path = sn.SNAPSHOT_PATH,
                  archive_root: Path = st.PRIMARY_ROOT, log_dir: Path = LOG_DIR, lock_dir: Path = LOCK_DIR,
                  eod_kwargs: dict | None = None) -> tuple[int, dict]:
    """Tek zamanlanmış çağrı (probe | eod) → (çıkış kodu, log kaydı)."""
    assert kind in ("probe", "eod")
    t0, started = time.monotonic(), now()
    rec = {"timestamp": started.astimezone(timezone.utc).isoformat(), "command": kind, "run_id": None,
           "new_bars": 0, "duplicates": 0, "revisions": 0, "failures": [], "identity_failures": []}
    code = EXIT_OK
    try:
        with SingletonLock(lock_dir / f"{kind}.lock"):
            m = mm.load(manifest_path)
            c = m["config"]
            today = _local(started).date()
            if c["manifest_status"] != mm.FINAL:
                rec["status"] = "SKIPPED_NOT_STARTED"
            elif today < date.fromisoformat(c["prospective_start_session"]):
                rec["status"] = "SKIPPED_BEFORE_START"
            elif kind == "probe" and not vp.in_window(started):
                rec["status"] = "SKIPPED_OUTSIDE_WINDOW"
            else:
                anchors = sn.anchors(m, sn.load(snapshot_path))
                if not anchors["ok"]:
                    rec.update(status="ANCHOR_DRIFT", anchors=anchors)
                    code = EXIT_INTEGRITY
                else:
                    code = _collect(kind, m, sn.load(snapshot_path), rec, source_factory, now, archive_root,
                                    today, eod_kwargs or {})
    except AlreadyRunning:
        rec["status"] = "SKIPPED_ALREADY_RUNNING"
    except Exception as exc:
        rec.update(status="ERROR", error=f"{type(exc).__name__}: {exc}"[:500],
                   traceback=traceback.format_exc(limit=8)[-4000:])
        code = EXIT_ERROR
    rec["exit_code"] = code
    rec["duration_seconds"] = round(time.monotonic() - t0, 3)
    log_line(log_dir, f"{kind}_{_local(started).date()}.log", rec)
    return code, rec


def _collect(kind, m, snap, rec, source_factory, now, archive_root, today, eod_kwargs) -> int:
    a = st.Archive(archive_root, "primary")
    try:
        if kind == "eod" and eod_already_ok(a, today):
            rec["status"] = "SKIPPED_ALREADY_COMPLETED"
            return EXIT_OK
        source = source_factory()
        if kind == "probe":
            s = vp.probe_once(a, source, m, now)
        else:
            s = col.run_eod(a, source, m, now=now, **eod_kwargs)
        rec.update(run_id=s["run_id"], new_bars=s["new_bars"], duplicates=s.get("duplicate_bars", 0),
                   revisions=s.get("revisions", 0), failures=s["symbols_failed"],
                   identity_failures=s.get("identity_failures", []), request_count=s["request_count"],
                   status="COMPLETED")
        if kind == "probe":
            return EXIT_OK
        v = verify_after_eod(a, m, s["run_id"], now(), snap)
        rec["verification"] = v
        if not v["ok"]:
            rec["status"] = "INTEGRITY_FAILED"
            return EXIT_INTEGRITY
        return EXIT_PARTIAL if s["symbols_failed"] else EXIT_OK
    finally:
        a.close()


# ------------------------------------------------------------------ sağlık (yalnız toplama; sonuç YOK)
HEALTH_KEYS = ("manifest_status", "prospective_start", "days_elapsed", "sessions_observed", "assets_seen_today",
               "bars_5m_today", "bars_1m_today", "latest_probe", "latest_eod", "probe_failures_today",
               "eod_failures_today", "identity_mismatches", "archive_integrity", "anchors_ok", "code_matches_snapshot",
               "coverage_status", "collection_gaps", "no_session_observed", "visibility_latency_probe_only")


def health(now: datetime | None = None, manifest_path: Path = mm.MANIFEST_PATH,
           snapshot_path: Path = sn.SNAPSHOT_PATH, archive_root: Path = st.PRIMARY_ROOT) -> dict:
    now = now or datetime.now(timezone.utc)
    m = mm.load(manifest_path)
    c = m["config"]
    today = _local(now).date()
    start = date.fromisoformat(c["prospective_start_session"]) if c["prospective_start_session"] else None
    out = dict.fromkeys(HEALTH_KEYS)
    out.update(manifest_status=c["manifest_status"], prospective_start=str(start) if start else None,
               days_elapsed=(today - start).days if start else None)
    try:
        snap = sn.load(snapshot_path)
        out["anchors_ok"] = sn.anchors(m, snap)["ok"]
        out["code_matches_snapshot"] = sn.code_matches(snap)["code_matches_snapshot"]
    except sn.SnapshotError as exc:
        out["anchors_ok"] = False
        out["code_matches_snapshot"] = str(exc)
    if not (Path(archive_root) / "archive.sqlite").exists():
        out["archive_integrity"] = "NOT CREATED YET"
        out["collection_gaps"] = _gaps(None, start, today)[0] if start else []
        return out
    a = st.Archive(archive_root, "primary")
    try:
        q = lambda sql, *args: a.db.execute(sql, args).fetchone()[0]  # noqa: E731
        d = str(today)
        out["assets_seen_today"] = q("SELECT COUNT(DISTINCT symbol) FROM bars WHERE session_date=?", d)
        out["bars_5m_today"] = q("SELECT COUNT(*) FROM bars WHERE session_date=? AND interval='5m'", d)
        out["bars_1m_today"] = q("SELECT COUNT(*) FROM bars WHERE session_date=? AND interval='1m'", d)
        for mode, key in (("PROBE", "latest_probe"), ("EOD", "latest_eod")):
            row = a.db.execute("SELECT run_id, started_at, status FROM runs WHERE mode=? ORDER BY started_at DESC "
                               "LIMIT 1", (mode,)).fetchone()
            out[key] = dict(zip(("run_id", "started_at", "status"), row)) if row else None
        fails = a.db.execute("SELECT r.mode, f.attempted_at FROM fetch_failures f JOIN runs r ON r.run_id=f.run_id"
                             ).fetchall()
        out["probe_failures_today"] = sum(md == "PROBE" and _local(datetime.fromisoformat(t)).date() == today
                                          for md, t in fails)
        out["eod_failures_today"] = sum(md == "EOD" and _local(datetime.fromisoformat(t)).date() == today
                                        for md, t in fails)
        out["identity_mismatches"] = q("SELECT COUNT(DISTINCT symbol) FROM bars WHERE identity_check='MISMATCH'")
        out["archive_integrity"] = ig.verify_archive(a, m)["ok"]
        sess = ig.classify_sessions(a, c["benchmark"])
        out["sessions_observed"] = (int(((sess["session_class"] == "FULL") & (sess["session_date"] >= str(start))
                                         ).sum()) if start and len(sess) else 0)
        cov = ig.dataset_status(a, m)
        out["coverage_status"] = {k: cov[k] for k in ("status", "full_sessions", "asset_sessions",
                                                      "assets_below_minimum") if k in cov}
        out["collection_gaps"], out["no_session_observed"] = _gaps(a, start, today) if start else ([], [])
        lat = a.visibility(interval="5m", collection_mode="PROBE")["visibility_latency_seconds"]
        out["visibility_latency_probe_only"] = ({"n": int(len(lat)), "median_seconds": float(lat.median())}
                                                if len(lat) else {"n": 0})
    finally:
        a.close()
    return out


def _gaps(a: st.Archive | None, start: date, today: date) -> tuple[list, list]:
    """Başlangıçtan dünə kadar hafta içi günler: gösterge barı yoksa → kapsayan (gün+5 içinde) tamamlanmış EOD
    varsa NO_SESSION_OBSERVED (tatil olası), yoksa ve 5 günden eskiyse DATA_COLLECTION_GAP."""
    gaps, none_seen = [], []
    eod_days = []
    if a is not None:
        eod_days = [_local(datetime.fromisoformat(s)).date() for s, in a.db.execute(
            "SELECT started_at FROM runs WHERE mode='EOD' AND status='COMPLETED'")]
    d = start
    while d < today:
        if d.weekday() < 5:
            seen = a is not None and a.db.execute("SELECT 1 FROM bars WHERE symbol=? AND session_date=? LIMIT 1",
                                                  (mm.BENCHMARK, str(d))).fetchone() is not None
            if not seen:
                covered = any(d <= e <= d + timedelta(days=GAP_DAYS) for e in eod_days)
                if covered:
                    none_seen.append(str(d))
                elif (today - d).days > GAP_DAYS:
                    gaps.append({"date": str(d), "status": "DATA_COLLECTION_GAP"})
        d += timedelta(days=1)
    return gaps, none_seen
