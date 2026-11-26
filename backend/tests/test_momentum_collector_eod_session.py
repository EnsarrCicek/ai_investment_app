"""EOD kurtarma ↔ hedef seans kimliği (AMD-002) — ağsız, geçici arşivler. Sabah kurtarma EOD'si (D-1'i tamamlar) D
seansını tamamlanmış SAYMAZ; gerçekten tamamlanmış D için tekrar tetikleme hâlâ SKIPPED_ALREADY_COMPLETED."""

import inspect
import json
from datetime import date, time

import pandas as pd
import pytest

from app.research.momentum_collector import amendments as am
from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import ops
from app.research.momentum_collector import snapshot as sn
from app.research.momentum_collector import storage as st
from test_momentum_ops import Env, frame, local


class MultiDaySource:
    """Yuvarlanan 5 günlük pencere taklidi: verilen seansların barlarını birlikte döndürür."""

    def __init__(self, clock, days):
        self.clock, self.days = clock, list(days)

    def fetch(self, symbol, interval, period):
        df = pd.concat([frame(d, n=4) for d in self.days])
        return st.FetchResult(symbol, interval, f"{symbol}.IS", {"period": period}, self.clock(), df,
                              "TRY", "IST", "MATCH")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def run(env, day, hm, days):
    at = local(day, hm)
    return env.run("eod", at, source=MultiDaySource(lambda: at, days))


def bars(env):
    a = env.archive()
    try:
        return {r[0]: r[1:] for r in a.db.execute(
            "SELECT symbol||interval||bar_start_ns, bar_hash, first_seen_ns, session_date FROM bars")}
    finally:
        a.close()


def test_morning_recovery_for_previous_session_does_not_suppress_evening_eod(env):
    code, rec = run(env, "2026-10-23", "09:43", ["2026-10-22"])  # kurtarma: 22 Ekim seansını tamamlar
    assert rec["status"] == "COMPLETED" and rec["target_session_date"] == "2026-10-23"
    assert rec["run_finalizes_through"] == "2026-10-22"
    a = env.archive()
    assert ops.eod_already_ok(a, date(2026, 10, 22)) is True
    assert ops.eod_already_ok(a, date(2026, 10, 23)) is False  # ESKİ HATA: burada True dönüyordu
    a.close()
    before = bars(env)
    code, rec = run(env, "2026-10-23", "20:45", ["2026-10-22", "2026-10-23"])
    assert rec["status"] == "COMPLETED" and code == 0 and rec["new_bars"] > 0  # akşam D atlanmaz
    after = bars(env)
    assert all(after[k] == v for k, v in before.items())  # D-1 barları yeniden yazılmadı, first_seen aynı
    assert {v[2] for k, v in after.items() if k not in before} == {"2026-10-23"}


def test_completed_session_still_suppresses_duplicate(env):
    run(env, "2026-10-23", "19:00", ["2026-10-22", "2026-10-23"])
    code, rec = run(env, "2026-10-23", "19:15", ["2026-10-22", "2026-10-23"])
    assert (code, rec["status"]) == (0, "SKIPPED_ALREADY_COMPLETED") and rec["new_bars"] == 0
    a = env.archive()
    assert ops.eod_already_ok(a, date(2026, 10, 23)) and ops.eod_already_ok(a, date(2026, 10, 22))
    a.close()


def test_multi_day_catch_up_does_not_mark_today_complete(env):
    days = ["2026-10-22", "2026-10-23", "2026-10-26"]
    code, rec = run(env, "2026-10-27", "09:30", days)  # makine günlerce kapalıydı
    assert rec["status"] == "COMPLETED" and rec["run_finalizes_through"] == "2026-10-26"
    a = env.archive()
    assert all(ops.eod_already_ok(a, date.fromisoformat(d)) for d in days)
    assert ops.eod_already_ok(a, date(2026, 10, 27)) is False
    a.close()
    code, rec = run(env, "2026-10-27", "19:00", days + ["2026-10-27"])
    assert rec["status"] == "COMPLETED"


def test_repeated_recovery_is_idempotent(env):
    run(env, "2026-10-23", "09:43", ["2026-10-22"])
    before = bars(env)
    code, rec = run(env, "2026-10-23", "09:58", ["2026-10-22"])  # aynı sabah yeniden deneme
    assert rec["status"] == "COMPLETED" and rec["new_bars"] == 0 and rec["duplicates"] == len(before)
    assert bars(env) == before  # first_seen / bar_hash değişmez, satır eklenmez


def test_finalization_boundary_reuses_existing_constant():
    assert mm.FINAL_AFTER_LOCAL == time(18, 30)
    assert ops.finalized_through(local("2026-11-20", "09:43")) == date(2026, 11, 19)
    assert ops.finalized_through(local("2026-11-20", "18:29")) == date(2026, 11, 19)
    assert ops.finalized_through(local("2026-11-20", "18:30")) == date(2026, 11, 20)
    assert ops.finalized_through(local("2026-11-21", "09:00")) == date(2026, 11, 20)  # hafta sonu kurtarma


def test_full_short_rules_and_schedule_unchanged():
    assert (ig.FULL_FIRST_BAR_MAX, ig.FULL_LAST_BAR_MIN) == (time(10, 5), time(17, 50))
    snap = sn.load()
    now = sn.file_hashes()
    for f in ("backend/scripts/install_momentum_collection_tasks.ps1", "backend/scripts/momentum_collect.py",
              "backend/app/research/momentum_collector/collector.py",
              "backend/app/research/momentum_collector/storage.py",
              "backend/app/research/momentum_collector/integrity.py",
              "backend/app/research/momentum_collector/visibility_probe.py",
              "backend/app/research/momentum_collector/manifest.py"):
        assert now[f] == snap["snapshot"]["tracked_file_hashes"][f], f  # toplama/zamanlama kodu dokunulmadı


def test_amendment_chain_amd001_then_amd002(tmp_path):
    snap = sn.load()
    before = sn.SNAPSHOT_PATH.read_bytes()
    real = {d["record"]["amendment_id"]: d for d in am.load_chain()}
    if am.AMENDMENT_ID not in real:
        pytest.skip("canlı AMD-001 kaydı bu makinede yok")
    d = tmp_path / "amendments"
    am.write_record(real[am.AMENDMENT_ID], d)
    only1 = am.verify_chain(snap, d)
    assert only1["approved_amendment_chain_valid"] is False  # AMD-002 olmadan ops.py farkı onaysız
    rec = am.build_record(snap, "2026-11-23T00:00:00+00:00", real[am.AMENDMENT_ID]["record_sha256"], am.AMD002,
                          am.chain_file_hashes(snap, am.load_chain(d)))
    r = rec["record"]
    assert r["amendment_id"] == am.AMD002_ID and r["idempotency_fix"] is True
    for k in ("semantic_change", "data_collection_change", "bar_value_change", "first_seen_change",
              "schedule_change", "data_rewrite"):
        assert r[k] is False
    amd1_new = {f["path"]: f["new_file_sha256"] for f in real[am.AMENDMENT_ID]["record"]["affected_files"]}
    assert all(f["old_file_sha256"] == amd1_new[f["path"]] for f in r["affected_files"])
    assert "target market session rather than execution calendar date" in r["explanation"]
    am.write_record(rec, d)
    chain = am.verify_chain(snap, d)
    assert chain["approved_amendment_chain_valid"] is True and chain["original_snapshot_matches"] is False
    assert chain["amendments"] == [am.AMENDMENT_ID, am.AMD002_ID] and chain["unapproved_changes"] == []
    assert json.loads((d / f"{am.AMENDMENT_ID}.json").read_text(encoding="utf-8")) == real[am.AMENDMENT_ID]
    assert sn.SNAPSHOT_PATH.read_bytes() == before


def test_collector_never_touches_holdout_outcomes():
    src = inspect.getsource(ops) + inspect.getsource(am)
    for w in ("momentum_label_v2.labels", "momentum_final_holdout", "session_events", "momentum_pilot",
              "mfe_close", "build_events"):
        assert w not in src
