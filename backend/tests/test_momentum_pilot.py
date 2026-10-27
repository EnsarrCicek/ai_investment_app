"""Momentum PILOT bölmesi ve holdout koruması (yalnız araştırma): ilk 5 FULL seans pilot, sonrası holdout,
yükleyiciler gelecek seansı görürse HATA (süzme yok), Windows birincil / mobil yalnız gölge."""

import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import storage as st
from app.research.momentum_label_v2 import experiment as lx
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_pilot import analysis as an
from app.research.momentum_pilot import split as sp

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
DAYS = ["2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-30", "2026-11-02", "2026-11-03"]
STUDY = {"sha256": "s" * 64, "config": {"universe_sha256": "u" * 64, "prospective_start_session": "2026-10-22",
                                        "label_manifest_sha256": sp.LABEL_V2_SHA256}}


def sessions_frame(rows):
    return pd.DataFrame(rows, columns=["session_date", "session_class"])


# ------------------------------------------------------------------ bölme
def test_first_five_full_sessions_are_pilot_sixth_is_holdout():
    split = sp.resolve_split(DAYS[:6])
    assert split["pilot_sessions"] == DAYS[:5]
    assert split["status"] == sp.COMPLETE and split["pilot_cutoff_session"] == DAYS[4]
    assert split["holdout_sessions_observed"] == 1
    assert DAYS[5] not in split["pilot_sessions"]


def test_fewer_than_five_is_accumulating_without_cutoff():
    split = sp.resolve_split(DAYS[:3])
    assert split["status"] == sp.ACCUMULATING and split["pilot_cutoff_session"] is None


def test_incomplete_and_prestart_and_consumed_sessions_never_full():
    df = sessions_frame([("2026-10-14", "FULL"), ("2026-10-21", "FULL"), ("2026-10-22", "FULL"),
                         ("2026-10-23", "FULL"), ("2026-10-26", "FULL"), ("2026-10-27", "SHORT_SESSION")])
    assert sp.observed_full_sessions(df, "2026-10-22") == ["2026-10-22", "2026-10-23", "2026-10-26"]


def _bench_db(days_bars: dict[str, tuple[str, str]]):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE bars(symbol TEXT, interval TEXT, session_date TEXT, bar_start_local TEXT)")
    for d, (first, last) in days_bars.items():
        for hm in (first, last):
            db.execute("INSERT INTO bars VALUES ('XU100','5m',?,?)", (d, f"{d}T{hm}:00+03:00"))
    return type("A", (), {"db": db})()


def test_ongoing_session_is_not_full_in_collector_classification():
    a = _bench_db({"2026-10-26": ("09:55", "17:55"), "2026-10-27": ("09:55", "10:05")})
    full = sp.observed_full_sessions(ig.classify_sessions(a), "2026-10-22")
    assert full == ["2026-10-26"]


def test_manifest_and_sha_deterministic():
    a = sp.build_manifest(DAYS[:3], STUDY, NOW)
    b = sp.build_manifest(list(reversed(DAYS[:3])), STUDY, NOW)
    assert a == b and a["sha256"] == sp.cd.sha256_of(a["manifest"])
    for k in ("version", "study_manifest_sha256", "label_v2_sha256", "universe_sha256", "pilot_policy",
              "pilot_sessions", "holdout_policy", "pilot_cutoff_session", "created_at"):
        assert k in a["manifest"]
    assert a["manifest"]["pilot_policy"] == "first_5_full_observed_sessions"
    assert a["manifest"]["holdout_policy"] == "all_full_sessions_after_pilot_cutoff"


def test_refresh_appends_only_and_freezes_when_complete(tmp_path):
    path, hist = tmp_path / "m.json", tmp_path / "h"
    m1, ch = sp.refresh_manifest(DAYS[:3], STUDY, NOW, path, hist)
    assert ch and m1["manifest"]["development_access_cutoff"] == DAYS[2]
    same, ch = sp.refresh_manifest(DAYS[:3], STUDY, NOW, path, hist)
    assert not ch and same == m1
    m2, ch = sp.refresh_manifest(DAYS[:5], STUDY, NOW, path, hist)
    assert ch and m2["manifest"]["status"] == sp.COMPLETE and m2["manifest"]["previous_manifest_sha256"] == m1["sha256"]
    m3, ch = sp.refresh_manifest(DAYS, STUDY, NOW, path, hist)  # holdout seansları pilotu değiştirmez
    assert not ch and m3 == m2 and m3["manifest"]["pilot_cutoff_session"] == DAYS[4]
    assert len(list(hist.iterdir())) == 2  # önceki sürüm silinmez


def test_refresh_rejects_rewritten_prefix(tmp_path):
    path, hist = tmp_path / "m.json", tmp_path / "h"
    sp.refresh_manifest(DAYS[1:4], STUDY, NOW, path, hist)
    with pytest.raises(sp.PilotSplitError):
        sp.refresh_manifest(DAYS[:4], STUDY, NOW, path, hist)  # sonradan FULL olan daha eski seans


def test_tampered_manifest_rejected(tmp_path):
    path = tmp_path / "m.json"
    sp.refresh_manifest(DAYS[:3], STUDY, NOW, path, tmp_path / "h")
    path.write_text(path.read_text(encoding="utf-8").replace(DAYS[2], DAYS[3]), encoding="utf-8")
    with pytest.raises(sp.PilotSplitError):
        sp.load_manifest(path)


def test_label_v2_sha_fixed():
    assert sp.LABEL_V2_SHA256 == "9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09"
    assert lx.manifest_payload()["sha256"] == sp.LABEL_V2_SHA256 == lx.load_manifest()["sha256"]
    assert mm.load()["config"]["label_manifest_sha256"] == sp.LABEL_V2_SHA256


def test_repository_pilot_manifest_valid_and_bound_to_study():
    m = sp.load_manifest()
    b = m["manifest"]
    study = mm.load()
    assert b["study_manifest_sha256"] == study["sha256"] and b["universe_sha256"] == study["config"]["universe_sha256"]
    assert b["pilot_sessions"] == sorted(b["pilot_sessions"]) and len(b["pilot_sessions"]) <= 5
    assert all(d >= study["config"]["prospective_start_session"] for d in b["pilot_sessions"])


# ------------------------------------------------------------------ holdout koruması
def _guard(n=3):
    return sp.HoldoutGuard(sp.build_manifest(DAYS[:n], STUDY, NOW))


def _primary_db(days):
    db = sqlite3.connect(":memory:")
    db.executescript(st.SCHEMA)
    for i, d in enumerate(days):
        ns = pd.Timestamp(f"{d} 10:00", tz="Europe/Istanbul").value
        db.execute("INSERT INTO bars(symbol, interval, bar_start_ns, bar_start, bar_end_ns, bar_end, bar_start_local, "
                   "timezone, session_date, open, high, low, close, volume, bar_hash, study_version, "
                   "collector_version, source, identity_check, is_partial, retrieved_at_utc, first_seen_at, "
                   "first_seen_ns, request_hash, response_hash, collection_run_id, collection_mode, data_phase, "
                   "universe_role) VALUES ('AKBNK','5m',?,'',?,'','','',?,1,1,1,1,1,'h','v','c','y','MATCH',0,'','',"
                   "?,'q','r','run','EOD','PROSPECTIVE','PRIMARY')", (ns, ns + 300_000_000_000, d, ns + 10**12))
    return db


def test_holdout_loader_raises_before_querying():
    class NoQuery:
        def execute(self, *a, **k):
            raise AssertionError("future session must fail before any query")
    with pytest.raises(sp.HoldoutAccessError, match=sp.HOLDOUT_ERROR):
        sp.load_primary_bars(NoQuery(), _guard(), [DAYS[0], DAYS[3]], "5m")


def test_pilot_loader_returns_only_requested_pilot_sessions():
    db = _primary_db(DAYS)
    df = sp.load_primary_bars(db, _guard(), DAYS[:3], "5m")
    assert sorted(df["session_date"]) == DAYS[:3] and set(df["source"]) == {sp.PRIMARY_SOURCE}


def test_no_silent_filtering_of_future_rows():
    g = _guard()
    frame = pd.DataFrame({"session_date": [DAYS[0], DAYS[4]]})
    with pytest.raises(sp.HoldoutAccessError):
        g.check_frame(frame)  # gelecek satırı görmek = hata; satır düşürülmez
    with pytest.raises(sp.HoldoutAccessError):
        sp.load_primary_revisions(_primary_db(DAYS), g, [DAYS[5]], "5m")


def test_complete_manifest_guard_uses_pilot_cutoff():
    g = _guard(6)
    assert g.complete and g.cutoff == DAYS[4]
    g.check_session(DAYS[4])
    with pytest.raises(sp.HoldoutAccessError):
        g.check_session(DAYS[5])


def test_repository_guard_blocks_today_and_later():
    g = sp.HoldoutGuard(sp.load_manifest())
    with pytest.raises(sp.HoldoutAccessError):
        g.check_session("2099-01-01")
    for d in g.pilot_sessions:
        g.check_session(d)


# ------------------------------------------------------------------ Windows birincil / mobil gölge
def _mobile_db(rows, role="MOBILE_SHADOW", eligible=0):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE bars(collection_role TEXT, primary_validation_eligible INTEGER, symbol TEXT, "
               "interval TEXT, bar_start_ns INTEGER, session_date TEXT, open REAL, high REAL, low REAL, close REAL, "
               "volume REAL, bar_hash TEXT, first_seen_ns INTEGER, identity_status TEXT)")
    db.execute("CREATE TABLE bar_revisions(symbol TEXT, interval TEXT, bar_start_ns INTEGER, original_hash TEXT, "
               "new_hash TEXT, changed_fields TEXT)")
    for r in rows:
        db.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (role, eligible, *r))
    return db


def test_mobile_shadow_cannot_replace_primary():
    g = _guard()
    with pytest.raises(sp.PilotSplitError):
        sp.load_mobile_bars(_mobile_db([("AKBNK", "5m", 1, DAYS[0], 1, 1, 1, 1, 1, "h", 2, "MATCH")],
                                       role="WINDOWS_PRIMARY"), g, DAYS[:1], "5m")
    with pytest.raises(sp.PilotSplitError):
        sp.load_mobile_bars(_mobile_db([("AKBNK", "5m", 1, DAYS[0], 1, 1, 1, 1, 1, "h", 2, "MATCH")], eligible=1),
                            g, DAYS[:1], "5m")
    with pytest.raises(sp.HoldoutAccessError):
        sp.load_mobile_bars(_mobile_db([]), g, [DAYS[4]], "5m")


def test_source_comparison_counts_without_merging():
    w = pd.DataFrame({"symbol": ["A", "A", "A"], "interval": "5m", "bar_start_ns": [1, 2, 3],
                      "open": [1.0, 1.0, 1.0], "high": 1.0, "low": 1.0, "close": [1.0, 1.0, 1.0],
                      "volume": [10.0, np.nan, 5.0], "bar_hash": ["a", "b", "c"], "identity_check": "MATCH"})
    m = pd.DataFrame({"symbol": ["A", "A", "A"], "interval": "5m", "bar_start_ns": [1, 2, 4],
                      "open": [1.0, 1.0, 1.0], "high": 1.0, "low": 1.0, "close": [1.0, 1.0, 2.0],
                      "volume": [11.0, np.nan, 5.0], "bar_hash": ["x", "b", "d"],
                      "identity_check": ["MATCH", "UNVERIFIED", "MATCH"]})
    before = w.copy()
    out = an.compare_sources(w, m)
    assert out == {"overlapping_bars": 2, "ohlcv_exact_matches": 1, "different_bars": 1, "hash_matches": 1,
                   "missing_mobile_bars": 1, "missing_windows_bars": 1, "identity_differences": 1,
                   "merged_into_primary": False}
    pd.testing.assert_frame_equal(w, before)


# ------------------------------------------------------------------ 1m ↔ 5m
def _bars(minutes: int, closes, start="2026-10-22 10:00"):
    t0 = pd.Timestamp(start, tz="Europe/Istanbul").value
    c = np.asarray(closes, float)
    return pd.DataFrame({"bar_start_ns": t0 + np.arange(len(c)) * minutes * an.au.MIN_NS, "close": c,
                         "high": c, "low": c, "volume": np.full(len(c), 100.0), "symbol": "A",
                         "session_date": "2026-10-22"})


def test_timing_uses_archived_bars_and_same_definition():
    one = _bars(1, [100] * 10 + [100 + 0.3 * k for k in range(1, 21)])  # 10:10'dan sonra dakikada +0.3
    five = _bars(5, [100, 100, 101.5, 103.0, 104.5, 106.0])  # 1m barların 5 dk özeti
    start = one["bar_start_ns"].iloc[0]
    end = start + 30 * an.au.MIN_NS
    t1 = an.first_evidence_times(one, 1, None, start, end)
    t5 = an.first_evidence_times(five, 5, None, start, end)
    assert t1["price"] < t5["price"]  # %2: 1m bar 10:16 (bitiş 10:17), 5m bar 10:15 (bitiş 10:20)
    assert (t5["price"] - t1["price"]) / an.au.MIN_NS == 3
    assert t1["volume"] is None and t5["volume"] is None  # taban yoksa hacim kanıtı uydurulmaz


def test_timing_skips_events_without_real_1m_bars():
    ev = lv.Swing(0, 3, 100.0, 106.0, int(_bars(5, [1])["bar_start_ns"].iloc[0]),
                  int(_bars(5, [1])["bar_start_ns"].iloc[0]) + 15 * an.au.MIN_NS, 0.06, True, lv.INTRADAY_EVALUABLE)
    rec = {"symbol": "A", "session": "2026-10-22", "event_k": 0, "event_class": ev.event_class, "event_start": "10:00",
           "event_peak": "10:15", "runup_pct": 6.0}
    five = _bars(5, [100, 102, 104, 106, 105])
    sparse = _bars(1, [100, 101, 102])  # pencerenin %80'inden az gerçek 1m bar
    out = an.timing_comparison([rec], {("A", "2026-10-22", 0): ev}, five, sparse)
    assert out["events"] == [] and out["skipped"] == {"1m_window_coverage_below_80pct": 1}
    out = an.timing_comparison([rec], {("A", "2026-10-22", 0): ev}, five, sparse.iloc[0:0])
    assert out["skipped"] == {"no_1m_bars_for_session": 1}


# ------------------------------------------------------------------ erken hareket grupları
def _swing(low_bar, peak_bar, peak_min, cls=lv.INTRADAY_EVALUABLE):
    return lv.Swing(low_bar, peak_bar, 100.0, 106.0, 0, peak_min * an.au.MIN_NS, 0.06, True, cls)


def test_early_groups_follow_v2_semantics():
    assert an.early_group(_swing(0, 0, 0, lv.PRE_OBSERVATION), False, None) == an.OPENING
    assert an.early_group(_swing(0, 6, 30), True, 0.1) == an.OPENING  # boşluk + dip ilk barda
    assert an.early_group(_swing(10, 16, 30), True, 0.1) == an.EARLY  # boşluk seansında sonraki gün içi olay
    assert an.early_group(_swing(4, 4, 0, lv.INTRABAR), False, 0.9) == an.VERTICAL
    assert an.early_group(_swing(4, 6, 10), False, 0.2) == an.VERTICAL
    assert an.early_group(_swing(4, 12, 40), False, None) == an.NO_SIGNAL
    assert an.early_group(_swing(4, 12, 40), False, 0.5) == an.EARLY
    assert an.early_group(_swing(4, 12, 40), False, 0.51) == an.LATE


def test_pilot_metrics_are_labelled_development_only():
    assert sp.PILOT_LABEL == "PILOT / DEVELOPMENT ONLY"
    assert "PROSPECTIVE FINAL" not in sp.PILOT_LABEL
