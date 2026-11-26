"""EOD ↔ Probe doğrulama yarışı (ağsız, geçici arşiv): eşzamanlı meşru Probe satırı EOD bütünlük doğrulamasını
düşürmemeli; doğrulama anlık görüntüsünde zaten var olan gerçekten gelecek tarihli first_seen hâlâ yakalanmalı.
first_seen asla yeniden yazılmaz; asıl çalışma anlık görüntüsü değişmez; değişiklik kaydı zinciri geçerli."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import ops
from app.research.momentum_collector import snapshot as sn
from app.research.momentum_collector import storage as st

UTC = timezone.utc
NS = 1_000_000_000


def _ns(t: datetime) -> int:
    return int(t.timestamp() * NS)


def insert_bar(path, symbol: str, start: datetime, first_seen: datetime, run_id: str, mode: str = "PROBE"):
    """Bağımsız bağlantıdan (ayrı yazar, Probe gibi) tamamlanmış bar ekler."""
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    try:
        s = _ns(start)
        db.execute(
            "INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (symbol, "5m", s, start.isoformat(), s + 300 * NS, (start + timedelta(minutes=5)).isoformat(),
             start.isoformat(), mm.TIMEZONE, str(start.date()), 1.0, 1.0, 1.0, 1.0, 10.0, "h" * 64, mm.STUDY_VERSION,
             mm.COLLECTOR_VERSION, f"{symbol}.IS", "yahoo_finance", "IST", "TRY", "MATCH", 0, first_seen.isoformat(),
             first_seen.isoformat(), _ns(first_seen), "q" * 64, "r" * 64, run_id, mode, "PROSPECTIVE", "PRIMARY"))
    finally:
        db.close()


@pytest.fixture
def arch(tmp_path):
    a = st.Archive(tmp_path / "primary", "primary")
    t0 = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)
    run = a.begin_run("EOD", {"t": 1}, t0)
    a.finish_run(run, {"n": 0}, t0 + timedelta(minutes=1))
    insert_bar(a.root / "archive.sqlite", "AKBNK", datetime(2026, 11, 3, 7, 0, tzinfo=UTC), t0, run, "EOD")
    yield a, run
    a.close()


def _check_hook(monkeypatch, action):
    """`ig.verify_archive` (yavaş hash/bütünlük adımlarını temsil eder) çağrıldığında `action` çalışır."""
    real = ig.verify_archive

    def hooked(a, m=None):
        action()
        return real(a, m)
    monkeypatch.setattr(ops.ig, "verify_archive", hooked)


def test_race_cause_reproduced_legit_row_is_newer_than_captured_now(arch, monkeypatch):
    """Eski davranışın nedeni: yakalanan `now` sonrasında meşru Probe yazımı → `first_seen_ns > now`."""
    a, run = arch
    captured_now = datetime.now(UTC)
    insert_bar(a.root / "archive.sqlite", "GARAN", captured_now - timedelta(minutes=20),
               captured_now + timedelta(seconds=20), "PROBE-x")
    naive = a.db.execute("SELECT COUNT(*) FROM bars WHERE first_seen_ns > ?", (_ns(captured_now),)).fetchone()[0]
    assert naive == 1  # eski sorgu bu meşru satırı "gelecek" sayardı


def test_concurrent_probe_row_does_not_fail_validation(arch, monkeypatch):
    a, run = arch
    m, snap = mm.load(), sn.load()
    now = datetime.now(UTC)
    written = []

    def probe_writes():
        t = datetime.now(UTC) + timedelta(seconds=20)  # doğrulama sırasında, yakalanan sınırdan SONRA
        insert_bar(a.root / "archive.sqlite", "GARAN", t - timedelta(minutes=20), t, "PROBE-concurrent")
        written.append(t)
    _check_hook(monkeypatch, probe_writes)
    v = ops.verify_after_eod(a, m, run, now, snap)
    assert written and v["no_future_first_seen"] is True and v["ok"] is True
    # satır gerçekten yazıldı ve first_seen değişmedi
    row = a.db.execute("SELECT first_seen_ns FROM bars WHERE collection_run_id='PROBE-concurrent'").fetchone()
    assert row[0] == _ns(written[0])


def test_genuine_future_first_seen_still_fails(arch):
    a, run = arch
    future = datetime.now(UTC) + timedelta(hours=2)
    insert_bar(a.root / "archive.sqlite", "THYAO", datetime(2026, 11, 3, 8, 0, tzinfo=UTC), future, "BAD")
    v = ops.verify_after_eod(a, mm.load(), run, datetime.now(UTC), sn.load())
    assert v["no_future_first_seen"] is False and v["ok"] is False
    assert a.db.execute("SELECT first_seen_ns FROM bars WHERE collection_run_id='BAD'").fetchone()[0] == _ns(future)


def test_validation_only_check_writes_nothing(arch):
    a, run = arch
    before = a.db.execute("SELECT COUNT(*) FROM eod_verifications").fetchone()[0]
    v = ops.consistent_integrity_check(a, mm.load(), run, sn.load())
    assert v["ok"] and a.db.execute("SELECT COUNT(*) FROM eod_verifications").fetchone()[0] == before
    assert "validation_boundary" in v and "visible_high_watermark_rowid" in v


@pytest.mark.parametrize("rep", range(12))
def test_stress_concurrent_writers_never_false_fail(arch, monkeypatch, rep):
    a, run = arch
    path = a.root / "archive.sqlite"
    stop = threading.Event()
    errors = []

    def writer():
        k = 0
        try:
            while not stop.is_set() and k < 40:
                t = datetime.now(UTC)
                insert_bar(path, f"S{rep}_{k}", t - timedelta(minutes=30), t, f"PROBE-{rep}-{k}")
                k += 1
        except Exception as e:  # pragma: no cover
            errors.append(e)
    th = threading.Thread(target=writer)
    _check_hook(monkeypatch, lambda: (th.start(), th.join(timeout=10)))
    try:
        v = ops.verify_after_eod(a, mm.load(), run, datetime.now(UTC), sn.load())
    finally:
        stop.set()
        if th.is_alive():
            th.join()
    assert not errors and v["no_future_first_seen"] is True and v["ok"] is True


@pytest.mark.parametrize("rep", range(5))
def test_stress_injected_future_always_detected(arch, monkeypatch, rep):
    a, run = arch
    insert_bar(a.root / "archive.sqlite", "BAD", datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
               datetime.now(UTC) + timedelta(minutes=30 + rep), f"BAD-{rep}")
    _check_hook(monkeypatch, lambda: insert_bar(a.root / "archive.sqlite", "OK", datetime.now(UTC),
                                                datetime.now(UTC), f"PROBE-ok-{rep}"))
    v = ops.verify_after_eod(a, mm.load(), run, datetime.now(UTC), sn.load())
    assert v["no_future_first_seen"] is False


def test_original_snapshot_immutable_and_amendment_chain(tmp_path):
    from app.research.momentum_collector import amendments as am
    before = sn.SNAPSHOT_PATH.read_bytes()
    snap = sn.load()
    assert snap["snapshot_sha256"] == "6d4e814b18f14e930fa4f08d2913ccd9e8a6d57bba0c056a0c03fb4b87b11163"
    rec_a = am.build_record(snap, "2026-11-04T10:00:00+00:00", previous_sha256=None)
    rec_b = am.build_record(snap, "2026-11-04T10:00:00+00:00", previous_sha256=None)
    assert rec_a == rec_b and rec_a["record_sha256"] == sn.cd.sha256_of(rec_a["record"])
    r = rec_a["record"]
    assert r["reason"] == "EOD_PROBE_VALIDATION_RACE" and r["old_snapshot_sha256"] == snap["snapshot_sha256"]
    for k in ("semantic_change", "data_collection_change", "data_rewrite", "first_seen_change", "schedule_change"):
        assert r[k] is False
    files = {f["path"]: f for f in r["affected_files"]}
    assert "backend/app/research/momentum_collector/ops.py" in files
    ops_entry = files["backend/app/research/momentum_collector/ops.py"]
    assert ops_entry["old_file_sha256"] == snap["snapshot"]["tracked_file_hashes"][
        "backend/app/research/momentum_collector/ops.py"]
    d = tmp_path / "amendments"
    am.write_record(rec_a, d)
    am.write_record(rec_a, d)  # aynı kayıt idempotent
    assert len(list(d.glob("*.json"))) == 1
    with pytest.raises(am.AmendmentError):
        am.write_record({**rec_a, "record": {**rec_a["record"], "reason": "x"}}, d)
    chain = am.verify_chain(snap, d)
    assert chain["approved_amendment_chain_valid"] is True and chain["original_snapshot_matches"] is False
    assert sn.SNAPSHOT_PATH.read_bytes() == before  # asıl anlık görüntü değişmedi


def test_chain_invalid_if_unrecorded_change(tmp_path, monkeypatch):
    from app.research.momentum_collector import amendments as am
    snap = sn.load()
    d = tmp_path / "amendments"
    am.write_record(am.build_record(snap, "2026-11-04T10:00:00+00:00", None), d)
    real = sn.file_hashes

    def tampered():
        h = dict(real())
        h["backend/app/research/momentum_collector/collector.py"] = "0" * 64
        return h
    monkeypatch.setattr(am.sn, "file_hashes", tampered)
    assert am.verify_chain(snap, d)["approved_amendment_chain_valid"] is False


def test_no_collection_semantic_change():
    import inspect
    src = inspect.getsource(ops)
    assert "first_seen_ns > ?" in src  # gelecek-zaman denetimi duruyor
    for unchanged in ("vp.probe_once(a, source, m, now)", "col.run_eod(a, source, m, now=now, **eod_kwargs)",
                      "eod_already_ok(a, target_session)"):
        assert unchanged in src


def test_health_reports_snapshot_distinction():
    h = ops.health()
    assert h["code_matches_snapshot"] is False or h["code_matches_snapshot"] is True
    assert "original_snapshot_matches" in h and "approved_amendment_chain_valid" in h
    assert set(h) == set(ops.HEALTH_KEYS)
    assert not any(k in json.dumps(list(h)).lower() for k in ("precision", "recall", "alert", "lead", "label"))
