"""Zamanlanmış toplama işletimi (yalnız araştırma): tekil kilit, başlangıç sınırı, idempotent EOD, kurtarma
semantiği, kayma tespiti, sağlık çıktısı, Windows komut satırı. Ağ YOK — sahte kaynak."""

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import collector as col
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import ops
from app.research.momentum_collector import snapshot as sn
from app.research.momentum_collector import storage as st
from app.research.momentum_final import candidate as cd

BACKEND = Path(__file__).resolve().parents[1]
FORBIDDEN = {"precision", "recall", "event", "events", "candidate", "score", "pass", "lead", "threshold", "verdict",
             "outcome", "label", "model"}  # "failures" = toplama (fetch) hatası, sonuç değil


def local(day: str, hm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=ISTANBUL_TZ)


def frame(day="2026-10-22", start="09:55", n=3):
    idx = pd.date_range(f"{day} {start}", periods=n, freq="5min", tz=ISTANBUL_TZ)
    o = 100 + np.arange(n, dtype=float)
    return pd.DataFrame({"Open": o, "High": o + 1, "Low": o - 1, "Close": o + 0.5, "Volume": 1000.0}, index=idx)


class FakeSource:
    def __init__(self, clock, day="2026-10-22", fail=()):
        self.clock, self.day, self.fail, self.calls = clock, day, set(fail), 0

    def fetch(self, symbol, interval, period):
        self.calls += 1
        if symbol in self.fail:
            raise col.EmptyResponse(f"'{symbol}' boş yanıt")
        return st.FetchResult(symbol, interval, f"{symbol}.IS", {"period": period}, self.clock(), frame(self.day),
                              "TRY", "IST", "MATCH")


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        c = mm.build_draft(local("2026-10-21", "12:27"))
        path = tmp / "manifest.json"
        mm.atomic_write_json(path, {"config": c, "sha256": mm.manifest_sha(c)})
        self.m = mm.start_study(path, now=local("2026-10-21", "12:28"))
        assert self.m["config"]["prospective_start_session"] == "2026-10-22"
        self.manifest_path, self.snapshot_path = path, tmp / "snapshot.json"
        self.write_snapshot()
        self.root, self.logs, self.locks = tmp / "primary", tmp / "logs", tmp / "locks"

    def write_snapshot(self, **override):
        snap = {"study_manifest_sha256": self.m["sha256"], "label_manifest_sha256": self.m["config"][
            "label_manifest_sha256"], "universe_sha256": self.m["config"]["universe_sha256"],
                "tracked_file_hashes": {}, **override}
        mm.atomic_write_json(self.snapshot_path, {"snapshot": snap, "snapshot_sha256": cd.sha256_of(snap)})

    def run(self, kind, at, source=None, **kw):
        clock = (lambda: at)
        return ops.scheduled_run(kind, source_factory=lambda: source or FakeSource(clock), now=clock,
                                 manifest_path=self.manifest_path, snapshot_path=self.snapshot_path,
                                 archive_root=self.root, log_dir=self.logs, lock_dir=self.locks,
                                 eod_kwargs={"pace_seconds": 0}, **kw)

    def archive(self):
        return st.Archive(self.root, "primary")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------ tekil kilit
def test_probe_singleton_skips_without_writing(env):
    with ops.SingletonLock(env.locks / "probe.lock"):
        code, rec = env.run("probe", local("2026-10-22", "10:30"))
    assert (code, rec["status"]) == (0, "SKIPPED_ALREADY_RUNNING") and not env.root.exists()
    assert rec["new_bars"] == 0


def test_eod_singleton_separate_from_probe(env):
    with ops.SingletonLock(env.locks / "eod.lock"):
        code, rec = env.run("eod", local("2026-10-22", "19:00"))
        assert rec["status"] == "SKIPPED_ALREADY_RUNNING" and not env.root.exists()
        code, rec = env.run("probe", local("2026-10-22", "10:30"))  # sonda kilidi ayrı
        assert rec["status"] == "COMPLETED"


def test_stale_lock_file_does_not_block(env):
    env.locks.mkdir(parents=True)
    (env.locks / "probe.lock").write_bytes(b"x")
    (env.locks / "probe.holder").write_text(json.dumps({"pid": 999999, "since": "2026-10-21T00:00:00+00:00"}))
    code, rec = env.run("probe", local("2026-10-22", "10:30"))
    assert code == 0 and rec["status"] == "COMPLETED"


def test_no_two_probe_instances_overlap_across_processes(env):
    holder = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, r"{BACKEND}")
        from app.research.momentum_collector import ops
        import os
        with ops.SingletonLock(__import__("pathlib").Path(r"{env.locks / 'probe.lock'}")):
            print("locked", flush=True)
            sys.stdin.readline()
            os._exit(1)  # kilidi bırakmadan çökme
    """)
    p = subprocess.Popen([sys.executable, "-c", holder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "locked"
        code, rec = env.run("probe", local("2026-10-22", "10:30"))
        assert rec["status"] == "SKIPPED_ALREADY_RUNNING" and not env.root.exists()
    finally:
        p.stdin.write("go\n")
        p.stdin.flush()
        assert p.wait(timeout=30) == 1
    code, rec = env.run("probe", local("2026-10-22", "10:35"))  # süreç ölünce kilit OS tarafından bırakılır
    assert rec["status"] == "COMPLETED"


# ------------------------------------------------------------------ başlangıç sınırı / pencere
def test_pre_start_invocation_excluded(env):
    for kind, at in (("probe", local("2026-10-21", "14:00")), ("eod", local("2026-10-21", "19:00"))):
        code, rec = env.run(kind, at)
        assert (code, rec["status"]) == (0, "SKIPPED_BEFORE_START")
    assert not env.root.exists()  # birincil depo oluşturulmadı
    a = env.archive()  # yanlışlıkla yazılsa bile: 21 Ekim WARMUP_ONLY, kapsama girmez
    clock = lambda: local("2026-10-21", "19:00")  # noqa: E731
    col.collect(a, FakeSource(clock, day="2026-10-21"), [("AKBNK", "5m", "1d", "PRIMARY")], mode="EOD",
                manifest=env.m, now=clock)
    assert {r[0] for r in a.db.execute("SELECT data_phase FROM bars")} == {"WARMUP_ONLY"}
    assert a.validation_rows(env.m).empty
    from app.research.momentum_collector import integrity as ig
    assert ig.dataset_status(a, env.m)["full_sessions"] == 0
    a.close()


def test_scheduler_start_boundary_and_window(env):
    assert env.run("probe", local("2026-10-22", "09:00"))[1]["status"] == "SKIPPED_OUTSIDE_WINDOW"
    assert env.run("probe", local("2026-10-24", "11:00"))[1]["status"] == "SKIPPED_OUTSIDE_WINDOW"  # Cumartesi
    assert env.run("probe", local("2026-10-22", "21:00"))[1]["status"] == "SKIPPED_OUTSIDE_WINDOW"  # geç başlatma
    code, rec = env.run("probe", local("2026-10-22", "09:55"))
    assert rec["status"] == "COMPLETED" and rec["request_count"] == 16


# ------------------------------------------------------------------ EOD idempotent / kurtarma
def test_duplicate_eod_idempotent_and_retry_keeps_first_seen(env):
    at1 = local("2026-10-22", "19:00")
    code, rec = env.run("eod", at1, source=FakeSource(lambda: at1, fail={"GARAN"}))
    assert code == ops.EXIT_PARTIAL and rec["failures"] == ["GARAN"] and rec["verification"]["ok"]
    a = env.archive()
    seen = dict(a.db.execute("SELECT symbol||interval||bar_start_ns, first_seen_at FROM bars"))
    a.close()
    at2 = local("2026-10-22", "19:15")
    code, rec = env.run("eod", at2, source=FakeSource(lambda: at2))
    assert code == 0 and rec["status"] == "COMPLETED" and rec["duplicates"] == len(seen)
    assert rec["new_bars"] == 2 * 3  # yalnız eksik GARAN (5m + 1m)
    a = env.archive()
    again = dict(a.db.execute("SELECT symbol||interval||bar_start_ns, first_seen_at FROM bars"))
    a.close()
    assert all(again[k] == v for k, v in seen.items())  # yeniden deneme first_seen değiştirmez
    code, rec = env.run("eod", local("2026-10-22", "19:30"))
    assert rec["status"] == "SKIPPED_ALREADY_COMPLETED" and code == 0


def test_recovered_old_bar_uses_recovery_first_seen(env):
    at = local("2026-10-27", "19:00")  # 22 Ekim barları 5 gün sonra EOD ile kurtarılıyor
    env.run("eod", at, source=FakeSource(lambda: at, day="2026-10-22"))
    a = env.archive()
    rows = set(a.db.execute("SELECT session_date, first_seen_at, collection_mode, data_phase FROM bars"))
    assert rows == {("2026-10-22", at.astimezone(timezone.utc).isoformat(), "EOD", "PROSPECTIVE")}
    assert a.visibility(collection_mode="PROBE").empty  # gecikme ölçümüne EOD kurtarması girmez
    a.close()
    h = ops.health(at, env.manifest_path, env.snapshot_path, env.root)
    assert h["visibility_latency_probe_only"] == {"n": 0}


# ------------------------------------------------------------------ bütünlük / kayma
def test_integrity_failure_gives_nonzero_exit(env, monkeypatch):
    monkeypatch.setattr(st.Archive, "raw_hash_valid", lambda self, p, h: False)
    code, rec = env.run("eod", local("2026-10-22", "19:00"))
    assert code == ops.EXIT_INTEGRITY and rec["status"] == "INTEGRITY_FAILED"
    assert not rec["verification"]["raw_hashes_valid"]
    monkeypatch.undo()
    code, rec = env.run("eod", local("2026-10-22", "19:15"))  # doğrulanmamış EOD atlanmaz → yeniden dener
    assert rec["status"] == "COMPLETED" and code == 0


def test_raw_hash_validation_detects_tampering(env):
    env.run("eod", local("2026-10-22", "19:00"))
    a = env.archive()
    rel, h = a.db.execute("SELECT raw_path, response_hash FROM requests LIMIT 1").fetchone()
    assert a.raw_hash_valid(rel, h)
    import gzip
    with gzip.open(a.root / rel, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"symbol": "X", "provider_symbol": None, "interval": "5m", "currency": None,
                            "exchange": None, "identity_check": "MATCH", "source": "s", "bars": []}))
    assert not a.raw_hash_valid(rel, h)
    a.close()


def test_manifest_hash_drift_detected(env):
    env.write_snapshot(study_manifest_sha256="0" * 64)
    code, rec = env.run("eod", local("2026-10-22", "19:00"))
    assert code == ops.EXIT_INTEGRITY and rec["status"] == "ANCHOR_DRIFT" and not env.root.exists()
    assert rec["anchors"]["manifest_sha_unchanged"] is False


def test_label_hash_drift_detected(env, monkeypatch):
    monkeypatch.setattr(mm, "verified_label_sha", lambda: "f" * 64)
    code, rec = env.run("probe", local("2026-10-22", "10:30"))
    assert code == ops.EXIT_INTEGRITY and rec["anchors"]["label_sha_unchanged"] is False


def test_universe_hash_drift_detected(env, monkeypatch):
    monkeypatch.setattr(mm, "primary_universe", lambda: ["AKBNK"])
    code, rec = env.run("probe", local("2026-10-22", "10:30"))
    assert code == ops.EXIT_INTEGRITY and rec["anchors"]["universe_sha_unchanged"] is False


def test_snapshot_write_once(tmp_path):
    path = tmp_path / "s.json"
    mm.atomic_write_json(path, {"snapshot": {"a": 1}, "snapshot_sha256": cd.sha256_of({"a": 1})})
    assert sn.write_once(path)["snapshot"] == {"a": 1}  # var olan asla yeniden yazılmaz
    path.write_text(json.dumps({"snapshot": {"a": 2}, "snapshot_sha256": cd.sha256_of({"a": 1})}), encoding="utf-8")
    with pytest.raises(sn.SnapshotError):
        sn.load(path)


# ------------------------------------------------------------------ sağlık / loglar
def test_health_has_no_outcome_or_model_keys(env):
    env.run("probe", local("2026-10-22", "10:30"))
    h = ops.health(local("2026-10-22", "11:00"), env.manifest_path, env.snapshot_path, env.root)
    assert set(h) == set(ops.HEALTH_KEYS)
    text = json.dumps(h).lower()
    tokens = {t for k in h for t in k.lower().split("_")}
    assert not tokens & FORBIDDEN and "pass" not in text and "precision" not in text and "recall" not in text
    assert h["archive_integrity"] is True and h["anchors_ok"] is True and h["manifest_status"] == "FINAL"
    assert h["latest_probe"]["status"] == "COMPLETED" and h["bars_5m_today"] > 0


def test_health_gap_and_holiday_semantics(env):
    h = ops.health(local("2026-10-30", "12:00"), env.manifest_path, env.snapshot_path, env.root)
    assert h["archive_integrity"] == "NOT CREATED YET"
    assert [g["date"] for g in h["collection_gaps"]] == ["2026-10-22", "2026-10-23"]  # > 5 gün, hiç toplanmadı
    # 23 Ekim'de bar yok ama kapsayan EOD tamamlandı → tatil olası (NO_SESSION_OBSERVED), veri boşluğu değil
    at = local("2026-10-23", "19:00")
    env.run("eod", at, source=FakeSource(lambda: at, day="2026-10-22"))
    h = ops.health(local("2026-10-30", "12:00"), env.manifest_path, env.snapshot_path, env.root)
    assert h["no_session_observed"] == ["2026-10-23"] and h["collection_gaps"] == []


def test_log_record_fields_and_location(env):
    code, rec = env.run("probe", local("2026-10-22", "10:30"))
    line = json.loads((env.logs / "probe_2026-10-22.log").read_text(encoding="utf-8").splitlines()[-1])
    for k in ("timestamp", "command", "run_id", "exit_code", "duration_seconds", "new_bars", "duplicates",
              "revisions", "failures", "identity_failures", "status"):
        assert k in line
    assert ops.LOG_DIR.is_relative_to(st.STORE) and ops.LOCK_DIR.is_relative_to(st.STORE)
    r = subprocess.run(["git", "check-ignore", "-q", str(ops.LOG_DIR / "probe_2026-10-22.log")], cwd=BACKEND)
    assert r.returncode == 0  # Git dışı


# ------------------------------------------------------------------ Windows komut satırı
@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler")
def test_windows_command_quoting_and_working_directory(tmp_path):
    script = BACKEND / "scripts" / "install_momentum_collection_tasks.ps1"
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-DryRun",
                          "-Json", "-LogDir", str(tmp_path)], capture_output=True, text=True, check=True).stdout
    plan = json.loads(out[:out.rindex("]") + 1])
    assert [t["name"] for t in plan] == ["MomentumProspectiveProbe", "MomentumProspectiveEOD"]
    probe, eod = plan
    assert probe["working_directory"] == str(BACKEND) and probe["execute"] == "cmd.exe"
    assert f'""{BACKEND}\\.venv\\Scripts\\python.exe" -X utf8 scripts\\momentum_collect.py probe >> "' in probe["argument"]
    assert probe["start_boundary"] == "2026-10-22T09:55" and probe["repetition_minutes"] == 5
    assert probe["repetition_duration"] == "08:35" and probe["settings"]["MultipleInstances"] == "IgnoreNew"
    assert eod["trigger_times"] == ["19:00", "19:15", "19:30", "19:45"] and eod["settings"]["RestartCount"] >= 3
    assert all(t["settings"]["StartWhenAvailable"] for t in plan)
    # Aynı komut satırını zararsız `ping` ile gerçekten çalıştır: tırnaklar + çalışma dizini + log yönlendirme
    arg = probe["argument"].replace(" probe >> ", " ping >> ")
    subprocess.run(f"cmd.exe {arg}", cwd=probe["working_directory"], check=True)
    log = (tmp_path / "task_probe_stdout.log").read_text(encoding="utf-8")
    got = json.loads(log)
    assert got["ok"] is True and Path(got["cwd"]) == BACKEND
