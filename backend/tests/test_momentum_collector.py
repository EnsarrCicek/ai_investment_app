"""İleriye dönük momentum toplayıcısı (yalnız araştırma): manifest, append-only arşiv, first_seen, revizyon, kısmi
bar, kimlik, hata, çökme güvenliği, önyargısızlık. Ağ YOK — sahte kaynak."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import collector as col
from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import storage as st
from app.research.momentum_collector import visibility_probe as vp
from app.research.momentum_round2 import dataset as ds2

LABEL_SHA = "9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09"
T_CREATE = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def local(day: str, hm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=ISTANBUL_TZ)


def frame(day="2026-11-02", start="10:00", n=3, interval="5m", base=100.0, close_shift=0.0):
    freq = "5min" if interval == "5m" else "1min"
    idx = pd.date_range(f"{day} {start}", periods=n, freq=freq, tz=ISTANBUL_TZ)
    o = base + np.arange(n, dtype=float)
    return pd.DataFrame({"Open": o, "High": o + 1, "Low": o - 1, "Close": o + 0.5 + close_shift,
                         "Volume": np.full(n, 1000.0)}, index=idx)


def result(symbol="AKBNK", df=None, retrieved=None, interval="5m", identity="MATCH"):
    df = frame(interval=interval) if df is None else df
    retrieved = retrieved or local("2026-11-02", "19:00")
    return st.FetchResult(symbol, interval, f"{symbol}.IS" if identity != "UNVERIFIED" else None,
                          {"period": "1d", "interval": interval}, retrieved.astimezone(timezone.utc), df,
                          "TRY" if identity == "MATCH" else None, "IST" if identity == "MATCH" else None, identity)


@pytest.fixture
def draft():
    c = mm.build_draft(T_CREATE)
    return {"config": c, "sha256": mm.manifest_sha(c)}


@pytest.fixture
def started(tmp_path, draft):
    path = tmp_path / "m.json"
    mm.atomic_write_json(path, draft)
    return mm.start_study(path, now=local("2026-10-30", "20:00"))  # Cuma akşamı → 2 Kasım Pazartesi


@pytest.fixture
def arc(tmp_path):
    a = st.Archive(tmp_path / "primary", "primary")
    yield a
    a.close()


def ingest(a, res, m=None, run="r1", mode="EOD", role="PRIMARY"):
    return a.ingest(res, run, mode=mode, universe_role=role, manifest=m)


def count(a, table, where="1=1", args=()):
    return a.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]


# ------------------------------------------------------------------ manifest
def test_canonical_manifest_deterministic_and_label_sha_exact(tmp_path, draft):
    again = mm.build_draft(T_CREATE)
    assert again == draft["config"] and mm.manifest_sha(again) == draft["sha256"] and len(draft["sha256"]) == 64
    c = draft["config"]
    assert c["label_manifest_sha256"] == LABEL_SHA == mm.verified_label_sha() and len(LABEL_SHA) == 64
    assert c["manifest_status"] == "DRAFT" and c["prospective_start_session"] is None and c["frozen_at"] is None
    for k in ("study_version", "label_version", "universe", "universe_sha256", "benchmark", "intervals", "source",
              "timezone", "collection_policy", "visibility_probe_policy", "minimum_full_sessions",
              "minimum_asset_sessions", "start_policy", "end_policy", "revision_policy", "partial_bar_policy",
              "identity_policy", "created_at"):
        assert k in c
    path = tmp_path / "m.json"
    first = mm.write_draft(path, now=T_CREATE)
    assert mm.write_draft(path, now=T_CREATE + timedelta(days=1)) == first  # taslak sessizce yenilenmez
    data = json.loads(path.read_text(encoding="utf-8"))
    data["config"]["universe"] = data["config"]["universe"][:-1]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(mm.StudyManifestError):
        mm.load(path)


def test_universe_hash_deterministic_ktlev_excluded(draft):
    u = mm.primary_universe()
    assert u == sorted(set(ds2.REFERENCE_ASSETS) | set(ds2.UNTOUCHED_ASSETS)) and len(u) == 87
    assert mm.universe_sha256(list(reversed(u))) == mm.universe_sha256(u) == draft["config"]["universe_sha256"]
    assert "KTLEV" not in u and draft["config"]["descriptive_only_symbols"] == ["KTLEV"]
    assert "XU100" not in u and draft["config"]["benchmark"] == "XU100"
    assert draft["config"]["minimum_full_sessions"] == 20 and draft["config"]["minimum_asset_sessions"] == 1566
    p = draft["config"]["visibility_probe_policy"]
    assert p["subset_5m"] == mm.probe_subset(u) and len(p["subset_5m"]) == 10 and set(p["subset_1m"]) <= set(
        p["subset_5m"]) and "KTLEV" not in p["subset_5m"]


def test_prospective_start_boundary_and_single_start(tmp_path, draft):
    assert mm.next_session_after(local("2026-10-23", "12:00")) == date(2026, 10, 26)  # Cuma → Pazartesi
    assert mm.next_session_after(local("2026-10-21", "09:00")) == date(2026, 10, 21)  # açılıştan önce
    assert mm.next_session_after(local("2026-10-21", "09:40")) == date(2026, 10, 22)
    path = tmp_path / "m.json"
    mm.atomic_write_json(path, draft)
    s = mm.start_study(path, now=local("2026-10-30", "20:00"))
    assert s["config"]["manifest_status"] == "FINAL" and s["config"]["prospective_start_session"] == "2026-11-02"
    assert s["draft_sha256"] == draft["sha256"] and mm.load(path)["sha256"] == s["sha256"]
    with pytest.raises(mm.StudyManifestError):
        mm.start_study(path)
    assert ig.verify_study_manifest(s)["ok"]


def test_consumed_final_dates_never_validation_data(arc, started):
    assert mm.in_consumed_final(date(2026, 9, 28)) and mm.in_consumed_final(date(2026, 10, 15))
    assert not mm.in_consumed_final(date(2026, 10, 16))
    bad = {**started, "config": {**started["config"], "prospective_start_session": "2026-10-01"}}
    assert not ig.verify_study_manifest(bad)["start_after_consumed_final"]
    ingest(arc, result(df=frame(day="2026-10-01"), retrieved=local("2026-10-01", "19:00")), bad)
    assert count(arc, "bars", "data_phase='PROSPECTIVE'") == 3 and arc.validation_rows(bad).empty


# ------------------------------------------------------------------ arşiv
def test_duplicate_ignored_and_first_seen_immutable(arc):
    r1 = ingest(arc, result(retrieved=local("2026-11-02", "19:00")))
    r2 = ingest(arc, result(retrieved=local("2026-11-02", "20:00")), run="r2")
    assert (r1.new_bars, r2.new_bars, r2.duplicate_bars) == (3, 0, 3) and count(arc, "bars") == 3
    seen = {r[0] for r in arc.db.execute("SELECT first_seen_at FROM bars")}
    assert seen == {local("2026-11-02", "19:00").astimezone(timezone.utc).isoformat()}
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        arc.db.execute("UPDATE bars SET close = 1")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        arc.db.execute("DELETE FROM bars")


def test_revision_recorded_separately(arc):
    ingest(arc, result(retrieved=local("2026-11-02", "19:00")))
    rev = ingest(arc, result(df=frame(close_shift=0.25), retrieved=local("2026-11-02", "20:00")), run="r2")
    assert rev.revisions == 3 and rev.new_bars == 0
    assert {r[0] for r in arc.db.execute("SELECT close FROM bars")} == {100.5, 101.5, 102.5}  # orijinal korunur
    row = arc.db.execute("SELECT original_hash, previous_hash, new_hash, changed_fields FROM bar_revision "
                         "ORDER BY id LIMIT 1").fetchone()
    assert row[0] == row[1] != row[2] and json.loads(row[3]) == ["close"]
    again = ingest(arc, result(df=frame(close_shift=0.25), retrieved=local("2026-11-02", "21:00")), run="r3")
    assert again.revisions == 0 and again.duplicate_bars == 3  # aynı revizyon iki kez yazılmaz
    back = ingest(arc, result(retrieved=local("2026-11-02", "22:00")), run="r4")
    assert back.revisions == 3  # orijinale dönüş de gözlenen bir değişikliktir


def test_partial_then_final_relation(arc):
    early = result(retrieved=local("2026-11-02", "10:12"))  # 10:10 barı oluşuyor (ve günün son barı)
    c = ingest(arc, early, mode="PROBE")
    assert (c.new_bars, c.partial_observations) == (2, 1) and count(arc, "partial_bars") == 1
    assert count(arc, "bars", "is_partial != 0") == 0
    late = result(df=frame(close_shift=0.1), retrieved=local("2026-11-02", "19:00"))
    c2 = ingest(arc, late, run="r2")
    assert c2.new_bars == 1 and c2.finalizations == 1 and c2.revisions == 2
    fin = arc.db.execute("SELECT partial_observations, last_partial_hash != final_hash FROM bar_finalization"
                         ).fetchone()
    assert fin == (1, 1) and count(arc, "partial_bars") == 1  # kısmi gözlem silinmez
    # gecikmeli sağlayıcı: 18:30'dan önce yanıttaki son bar, bitmiş görünse bile kısmi sayılır
    flags = st.partial_flags(st._starts_ns(frame()), "5m", local("2026-11-02", "15:00"))
    assert flags.tolist() == [False, False, True]
    assert st.partial_flags(st._starts_ns(frame()), "5m", local("2026-11-02", "18:31")).tolist() == [False] * 3


def test_identity_mismatch_retained_but_gated(arc, started):
    ingest(arc, result("AKBNK", identity="MISMATCH"), started)
    ingest(arc, result("THYAO", identity="UNVERIFIED"), started)
    ingest(arc, result("GARAN"), started)
    assert count(arc, "bars", "identity_check='MISMATCH'") == 3 and count(arc, "bars", "currency IS NULL") == 6
    assert set(arc.validation_rows(started)["symbol"]) == {"GARAN"}


class FakeSource:
    def __init__(self, frames: dict, fail=(), retrieved=None):
        self.frames, self.fail, self.calls = frames, set(fail), []
        self.retrieved = retrieved or local("2026-11-02", "19:00")

    def fetch(self, symbol, interval, period):
        self.calls.append((symbol, interval, period))
        if symbol in self.fail:
            raise col.EmptyResponse(f"'{symbol}' {interval} boş yanıt")
        return result(symbol, self.frames.get((symbol, interval), frame(interval=interval)), self.retrieved,
                      interval)


def test_missing_fetch_never_fabricates(arc, started):
    src = FakeSource({}, fail={"GARAN"})
    plan = [("AKBNK", "5m", "5d", "PRIMARY"), ("GARAN", "5m", "5d", "PRIMARY")]
    s = col.collect(arc, src, plan, mode="EOD", manifest=started, now=lambda: local("2026-11-02", "19:00"))
    assert s["symbols_failed"] == ["GARAN"] and s["symbols_succeeded"] == ["AKBNK"] and s["errors"]
    assert count(arc, "bars", "symbol='GARAN'") == 0 and count(arc, "fetch_failures", "symbol='GARAN'") == 1
    gap = frame(n=4)
    gap.iloc[1, :4] = np.nan  # eksik bar: doldurulmaz, sıfır hacimli bar uydurulmaz
    c = ingest(arc, result("THYAO", gap), started, run="r2")
    assert c.invalid_rows == 1 and count(arc, "bars", "symbol='THYAO'") == 3
    assert count(arc, "bars", "volume = 0") == 0


def test_crash_restart_idempotent(arc, started, monkeypatch):
    calls = {"n": 0}
    real = mm.data_phase

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("çökme")
        return real(*a, **k)
    monkeypatch.setattr(mm, "data_phase", boom)
    with pytest.raises(RuntimeError):
        ingest(arc, result(retrieved=local("2026-11-02", "19:00")), started)
    assert count(arc, "bars") == 0 and count(arc, "requests") == 0  # işlem geri alındı
    monkeypatch.setattr(mm, "data_phase", real)
    ok = ingest(arc, result(retrieved=local("2026-11-02", "19:05")), started, run="r2")
    again = ingest(arc, result(retrieved=local("2026-11-02", "19:10")), started, run="r3")
    assert ok.new_bars == 3 and again.duplicate_bars == 3 and count(arc, "bars") == 3
    assert {r[0] for r in arc.db.execute("SELECT first_seen_at FROM bars")} == {
        local("2026-11-02", "19:05").astimezone(timezone.utc).isoformat()}
    assert ig.verify_archive(arc, started)["ok"]


def test_atomic_persistence(tmp_path, monkeypatch):
    path = tmp_path / "x.json"
    mm.atomic_write_json(path, {"a": 1})
    monkeypatch.setattr(mm.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        mm.atomic_write_json(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}  # eski içerik bozulmadı


def test_raw_response_content_addressed(arc):
    res = result()
    ingest(arc, res)
    rel = arc.db.execute("SELECT raw_path, response_hash FROM requests").fetchone()
    assert (arc.root / rel[0]).exists() and rel[1] in rel[0] and rel[1] == st.response_hash(res)
    assert not list(arc.root.rglob("*.tmp"))


def test_warmup_and_pre_start_excluded(arc, started, draft):
    ingest(arc, result(df=frame(day="2026-10-30"), retrieved=local("2026-10-30", "19:00")), started)
    ingest(arc, result(df=frame(day="2026-11-02"), retrieved=local("2026-11-02", "19:00")), started)
    phases = dict(arc.db.execute("SELECT session_date, data_phase FROM bars GROUP BY session_date"))
    assert phases == {"2026-10-30": "WARMUP_ONLY", "2026-11-02": "PROSPECTIVE"}
    v = arc.validation_rows(started)
    assert set(v["session_date"]) == {"2026-11-02"} and (v["session_date"] >= "2026-11-02").all()
    assert mm.data_phase(date(2026, 11, 5), draft) == "PRE_START" and arc.validation_rows(draft).empty


def test_first_seen_visibility_and_no_future_visibility(arc):
    ingest(arc, result(retrieved=local("2026-11-02", "10:40")), mode="PROBE")
    vis = arc.visibility("AKBNK", "5m")
    # 10:10 barı yanıtın son barı (18:30 öncesi) → kısmi; tamamlanmış barlar: 10:05 ve 10:10 bitişli
    assert sorted(vis["visibility_latency_seconds"]) == [30 * 60, 35 * 60]  # 10:40 − bar sonu
    ingest(arc, result(df=frame(close_shift=1.0), retrieved=local("2026-11-02", "19:00")), run="r2")
    assert arc.bars_as_of("AKBNK", "5m", local("2026-11-02", "10:39")).empty  # henüz görülmemiş
    first = arc.bars_as_of("AKBNK", "5m", local("2026-11-02", "12:00"), with_revisions=True)
    assert first["close"].tolist() == [100.5, 101.5]  # 19:00 revizyonu ve 10:10 barı geçmişe sızmaz
    later = arc.bars_as_of("AKBNK", "5m", local("2026-11-02", "19:30"), with_revisions=True)
    assert later["close"].tolist() == [101.5, 102.5, 103.5]
    assert arc.bars_as_of("AKBNK", "5m", local("2026-11-02", "19:30"))["close"].tolist() == [100.5, 101.5, 103.5]


def test_1m_and_5m_independent_keys(arc):
    ingest(arc, result(df=frame(n=1)))
    ingest(arc, result(df=frame(n=1, interval="1m"), interval="1m"), run="r2")
    assert count(arc, "bars") == 2 and count(arc, "bars", "interval='1m'") == 1


def test_preflight_isolated(tmp_path, arc):
    with pytest.raises(st.ArchiveError):
        ingest(arc, result(), mode="PREFLIGHT")
    arc.close()
    with pytest.raises(st.ArchiveError):
        st.Archive(tmp_path / "primary", "preflight")
    pre = st.Archive(tmp_path / "pre", "preflight")
    s = col.run_preflight(pre, FakeSource({}), now=lambda: local("2026-11-02", "19:00"))
    assert s["mode"] == "PREFLIGHT" and set(s["symbols_requested"]) == {"AKBNK", "THYAO", "XU100"}
    assert {r[0] for r in pre.db.execute("SELECT DISTINCT data_phase FROM bars")} == {"PREFLIGHT"}
    assert ig.verify_archive(pre)["ok"]
    pre.close()


def test_run_manifest_deterministic_for_audit(arc, started):
    src = FakeSource({})
    plan = col.eod_plan(started)
    assert len(plan) == (87 + 2) * 2 and plan == col.eod_plan(started)
    assert {p[3] for p in plan if p[0] == "KTLEV"} == {"DESCRIPTIVE_ONLY"}
    s = col.run_eod(arc, src, started, now=lambda: local("2026-11-02", "19:00"), pace_seconds=0)
    on_disk = json.loads((arc.root / "runs" / f"{s['run_id']}.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(s, default=str))
    for k in ("run_id", "started_at", "finished_at", "symbols_requested", "symbols_succeeded", "symbols_failed",
              "intervals", "request_count", "new_bars", "duplicate_bars", "revisions", "identity_failures", "errors"):
        assert k in s
    assert s["request_count"] == 178 and s["new_bars"] == 178 * 3
    s2 = col.run_eod(arc, src, started, now=lambda: local("2026-11-02", "19:05"), pace_seconds=0)
    assert s2["new_bars"] == 0 and s2["duplicate_bars"] == 178 * 3


def test_probe_observation_and_plan(arc, started):
    plan = vp.probe_plan(started)
    assert ("XU100", "5m") in plan and ("XU100", "1m") in plan and len(plan) == 11 + 5
    src = FakeSource({}, retrieved=local("2026-11-02", "10:12"))
    s = vp.probe_once(arc, src, started, now=lambda: local("2026-11-02", "10:12"))
    assert s["request_count"] == 16 and all(c[2] == "1d" for c in src.calls)
    row = arc.db.execute("SELECT latest_is_partial, latest_final_latency_seconds, new_final_bars FROM "
                         "probe_observations WHERE symbol='XU100' AND interval='5m'").fetchone()
    assert row == (1, 120.0, 2)  # 10:10 barı oluşuyor; son tamamlanmış bar 10:10'da bitti → 2 dk
    assert vp.in_window(local("2026-11-02", "10:00")) and not vp.in_window(local("2026-11-01", "11:00"))


def test_dataset_status_produces_no_outcome(arc, started, draft):
    assert ig.dataset_status(arc, draft)["status"].startswith("NOT STARTED")
    st_ = ig.dataset_status(arc, started)
    assert st_["status"].startswith("COLLECTING") and set(st_) == {
        "status", "full_sessions", "asset_sessions", "minimum_full_sessions", "minimum_asset_sessions",
        "minimum_sessions_per_primary_asset", "assets_below_minimum", "min_sessions_any_asset", "checks"}
    assert not {k for k in json.dumps(st_).lower().split('"') if k in ("pass", "fail", "precision", "recall")}


# ------------------------------------------------------------------ kapsam kuralı (START öncesi donduruldu)
def test_coverage_fields_in_manifest(draft):
    c = draft["config"]
    assert (c["minimum_full_sessions"], c["target_sessions"], c["minimum_asset_sessions"],
            c["minimum_sessions_per_primary_asset"]) == (20, 25, 1566, 18)
    assert "EVERY primary-universe asset" in c["coverage_policy"]


def test_one_asset_with_17_sessions_is_not_ready(draft):
    c = draft["config"]
    per = {s: 20 for s in c["universe"]}
    per[c["universe"][0]] = 17
    v = ig.coverage_verdict(20, per, c)
    assert v["asset_sessions"] >= 1566 and v["status"] != ig.READY and v["assets_below_minimum"] == 1
    assert v["checks"] == {"full_sessions": True, "asset_sessions": True, "per_asset_minimum": False}


def test_all_assets_at_least_18_and_aggregate_met_is_ready(draft):
    c = draft["config"]
    v = ig.coverage_verdict(20, {s: 18 for s in c["universe"]}, c)
    assert v["status"] == ig.READY and v["asset_sessions"] == 1566 and v["min_sessions_any_asset"] == 18
    assert ig.coverage_verdict(19, {s: 25 for s in c["universe"]}, c)["status"] != ig.READY
    missing = {s: 25 for s in c["universe"][1:]}  # bir varlık hiç yok → 0, evrenden düşmez
    v = ig.coverage_verdict(25, missing, c)
    assert v["status"] != ig.READY and v["min_sessions_any_asset"] == 0


def test_missing_asset_sessions_not_forward_filled(arc, started):
    c = {**started["config"], "universe": ["AKBNK", "GARAN"], "minimum_full_sessions": 2, "minimum_asset_sessions": 3,
         "minimum_sessions_per_primary_asset": 2}
    m = {**started, "config": c}
    full = frame(n=2).set_axis(pd.DatetimeIndex([local("2026-11-02", "10:00"), local("2026-11-02", "17:50")]))
    for day in ("2026-11-02", "2026-11-03"):
        f = full.set_axis(full.index + pd.Timedelta(days=int(day[-1]) - 2))
        for sym in ("XU100", "AKBNK"):
            ingest(arc, result(sym, f, local(day, "19:00")), m, run=f"{sym}{day}")
    ingest(arc, result("GARAN", full, local("2026-11-02", "19:00")), m, run="g")  # GARAN 3 Kasım'da yok
    v = ig.dataset_status(arc, m)
    assert v["full_sessions"] == 2 and v["asset_sessions"] == 3 and v["status"] != ig.READY
    assert v["assets_below_minimum"] == 1 and count(arc, "bars", "symbol='GARAN'") == 2  # doldurulmadı


def test_universe_cannot_change(tmp_path, draft, monkeypatch):
    path = tmp_path / "m.json"
    mm.atomic_write_json(path, draft)
    s = mm.start_study(path, now=local("2026-10-30", "20:00"))
    with pytest.raises(mm.StudyManifestError):
        mm.write_draft(path, regenerate=True)  # FINAL yeniden üretilemez
    data = json.loads(path.read_text(encoding="utf-8"))
    data["config"]["universe"] = data["config"]["universe"][1:]
    data["config"]["universe_count"] -= 1
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(mm.StudyManifestError):
        mm.load(path)  # SHA/evren hash'i bozulur
    assert ig.verify_study_manifest(s)["universe_unchanged"]
    d2 = tmp_path / "d.json"
    mm.atomic_write_json(d2, draft)
    monkeypatch.setattr(mm, "primary_universe", lambda: draft["config"]["universe"][1:])
    with pytest.raises(mm.StudyManifestError, match="evren"):
        mm.start_study(d2)


def test_draft_regenerate_only_before_start(tmp_path):
    path = tmp_path / "m.json"
    a = mm.write_draft(path, now=T_CREATE)
    b = mm.write_draft(path, now=T_CREATE, regenerate=True)
    assert a == b  # kanonik, deterministik
