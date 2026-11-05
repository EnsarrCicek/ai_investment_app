"""Haber arşivi kaynak düzenlemesi (SOURCE_REVISION) semantiği ve hazırlık kapısı (ağsız): aynı düzenlemenin tekrarı
tek düzenleme sayılır, farklı düzenleme ayrıca izlenir, kanonik kayıt değişmez, SOURCE_REVISION hazırlığı düşürmez,
gerçek STORAGE_CONFLICT düşürür, eski çakışma satırlarına dokunulmaz, rapor durumları ayırır, çevrimdışı keşif
gecikmesi sağlayıcı gecikmesi olarak etiketlenmez, holdout sonucu okunamaz."""

import hashlib
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.research.momentum_pilot import split as sp
from app.research.momentum_sources import holdout
from app.research.momentum_sources.common import SECONDARY_ROLE, raw_hash
from app.research.momentum_sources.news_archive import health as hl
from app.research.momentum_sources.news_archive.models import NewsArchiveItem
from app.research.momentum_sources.storage import REVISION_KNOWN, SOURCE_REVISION_NEW, STORAGE_CONFLICT, SecondaryStore

UTC = timezone.utc
T = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
KEY = "foreks:6aeb125995131d72027d63ad"


def item(head, minutes=0, symbol="UNRESOLVED", key=KEY, pub=T, url="u"):
    return NewsArchiveItem(provider="foreks", source="Foreks", symbol=symbol, company=None, published_at=pub,
                           received_at=T + timedelta(minutes=minutes), headline=head, event_type="other",
                           event_importance=None, source_url_hash=hashlib.sha256(url.encode()).hexdigest(),
                           content_hash=hashlib.sha256(head.encode()).hexdigest(), raw_hash=raw_hash({"h": head}),
                           published_at_semantics="x", item_key=key)


def runs(s, n=3, start=T):
    for k in range(n):
        t = start + timedelta(minutes=5 * k)
        r = s.begin_run("foreks", "news_archive", {"k": k}, t)
        s.finish_run(r, t + timedelta(seconds=2), "COMPLETED", {"rss_items_in_feed": 1, "duplicates": 1})


def report(root):
    return hl.report(root, root / "noraw", now=T + timedelta(hours=1), with_scheduler=False, universe=set())


def test_identical_revision_20_times_is_one_revision_and_canonical_unchanged(tmp_path):
    s = SecondaryStore(tmp_path)
    assert s.add_news(item("Lagarde: iklim maliyetleri artıyor")) == "NEW"
    assert s.add_news(item("Lagarde: Avrupa acil önlem almalı", 5)) == SOURCE_REVISION_NEW
    for k in range(20):
        assert s.add_news(item("Lagarde: Avrupa acil önlem almalı", 10 + k)) == REVISION_KNOWN
    assert s.add_news(item("Lagarde: Avrupa'ya çağrı", 60)) == SOURCE_REVISION_NEW
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 2
    assert s.db.execute("SELECT headline, raw_hash FROM news_events").fetchall() == [
        ("Lagarde: iklim maliyetleri artıyor", raw_hash({"h": "Lagarde: iklim maliyetleri artıyor"}))]
    row = s.db.execute("SELECT original_raw_hash, revision_type, source_role FROM source_revisions LIMIT 1").fetchone()
    assert row == (raw_hash({"h": "Lagarde: iklim maliyetleri artıyor"}), "SOURCE_REVISION", SECONDARY_ROLE)
    with pytest.raises(Exception):
        s.db.execute("DELETE FROM source_revisions")
    s.close()


def test_source_revision_does_not_fail_readiness_and_report_distinguishes(tmp_path):
    s = SecondaryStore(tmp_path)
    runs(s)
    s.add_news(item("orijinal başlık"))
    s.add_news(item("düzenlenmiş başlık", 5))
    s.add_news(item("düzenlenmiş başlık", 10))
    s.close()
    r = report(tmp_path)
    rv = r["revision_quality"]
    assert rv["distinct_source_revisions"] == 1 and rv["storage_conflicts"] == 0
    assert rv["canonical_rows_immutable"] and rv["revision_tracking_deterministic"]
    assert {"duplicates", "distinct_source_revisions", "known_revision_repeats", "storage_conflicts"} <= set(rv)
    assert r["catalyst_readiness"]["checks"]["duplicate_revision_handling"] is True
    assert "duplicate_stability" not in r["catalyst_readiness"]["checks"]


def test_storage_conflict_fails_readiness(tmp_path):
    s = SecondaryStore(tmp_path)
    runs(s)
    s.add_news(item("haber", symbol="AKBNK"))
    s.add_news(item("bambaşka içerik", symbol="GARAN"))  # aynı öğe kimliği, semboller arası farklı kanonik içerik
    s.db.execute("INSERT INTO source_revisions(provider, item_key, symbol, original_raw_hash, revision_raw_hash, "
                 "first_seen_revision_at, received_at, revision_type, evidence, source_role) "
                 "VALUES ('foreks','foreks:other','AKBNK','0','1',?,?, 'SOURCE_REVISION','OBSERVED',?)",
                 (T.isoformat(), T.isoformat(), SECONDARY_ROLE))  # kanonik kaydı olmayan düzenleme
    s.close()
    r = report(tmp_path)
    types = {c["type"] for c in r["revision_quality"]["storage_conflict_examples"]}
    assert {"SAME_ITEM_DIFFERENT_CANONICAL_CONTENT_ACROSS_SYMBOLS", "REVISION_PROVENANCE_MISMATCH"} <= types
    assert r["revision_quality"]["storage_conflicts"] >= 2
    assert r["catalyst_readiness"]["checks"]["duplicate_revision_handling"] is False
    assert r["catalyst_readiness"]["verdict"] == "NOT_READY"


def test_historical_conflict_rows_untouched_and_interpreted(tmp_path):
    s = SecondaryStore(tmp_path)
    runs(s)
    s.add_news(item("orijinal"))
    rev = item("düzenleme", 5)
    msg = f"DUPLICATE_CONFLICT: item_key={KEY} symbol=UNRESOLVED"
    for k in range(5):  # eski sürümün her getirmede yazdığı satırlar
        s.log_failure(None, "foreks", T + timedelta(minutes=5 + 5 * k), msg, T, rev.raw_hash)
    before = s.db.execute("SELECT * FROM source_failures ORDER BY id").fetchall()
    assert s.add_news(item("düzenleme", 40)) == REVISION_KNOWN  # eski kanıttan taşınır, yeni değil
    first = s.db.execute("SELECT first_seen_revision_at, evidence FROM source_revisions").fetchone()
    assert first == ((T + timedelta(minutes=5)).isoformat(), "LEGACY_DUPLICATE_CONFLICT_ROWS")
    assert s.db.execute("SELECT * FROM source_failures ORDER BY id").fetchall() == before
    s.close()
    rv = report(tmp_path)["revision_quality"]
    assert (rv["legacy_conflict_rows"], rv["distinct_revision_variants"],
            rv["legacy_known_revision_repeats"], rv["distinct_source_revisions"]) == (5, 1, 4, 1)
    assert rv["historical_rows_mutated"] is False and rv["storage_conflicts"] == 0


def test_offline_lag_separated_and_not_called_provider_latency(tmp_path):
    s = SecondaryStore(tmp_path)
    runs(s, n=3, start=T)  # 08:00–08:10 çevrimiçi
    runs(s, n=2, start=T + timedelta(hours=10))  # 10 saat çevrimdışı boşluk sonrası
    s.add_news(item("çevrimiçi yayımlanan", minutes=7, key="foreks:a", pub=T + timedelta(minutes=4)))
    s.add_news(item("gece yayımlanan", minutes=600, key="foreks:b", pub=T + timedelta(hours=3)))
    s.close()
    lag = report(tmp_path)["discovery_lag"]
    assert lag["collection_window_items"]["n"] == 1 and lag["collection_window_items"]["median"] == 3.0
    assert lag["offline_discovery_items"]["n"] == 1 and lag["offline_discovery_items"]["median"] == 420.0
    assert lag["collector_offline_gap_detected"] and lag["offline_gap_count"] == 1
    assert "ARCHIVAL DISCOVERY LAG" in lag["metric_definition"] and "NOT provider" in lag["metric_definition"]
    assert "NOT provider delay" in lag["offline_discovery_items"]["population"]


def test_no_holdout_outcome_access():
    for field in holdout.FORBIDDEN_NEWS_JOINS:
        with pytest.raises(sp.HoldoutAccessError):
            holdout.assert_news_join_allowed(["2026-11-05"], [field])
    src = inspect.getsource(hl)
    for w in ("session_events", "momentum_pilot.deep", "bars_as_of", "mfe_close"):
        assert w not in src


def test_uniqueness_50_same_then_second_and_third_distinct(tmp_path):
    s = SecondaryStore(tmp_path)
    assert s.add_news(item("orijinal")) == "NEW"
    assert s.add_news(item("düzenleme-1", 1)) == SOURCE_REVISION_NEW
    assert [s.add_news(item("düzenleme-1", 2 + k)) for k in range(49)] == [REVISION_KNOWN] * 49  # toplam 50
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
    assert s.add_news(item("düzenleme-2", 60)) == SOURCE_REVISION_NEW
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 2
    assert s.add_news(item("düzenleme-3", 70)) == SOURCE_REVISION_NEW
    assert s.add_news(item("düzenleme-2", 80)) == REVISION_KNOWN
    assert s.add_news(item("orijinal", 90)) == "DUPLICATE"  # kanoniğe dönüş düzenleme değildir
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 3
    assert s.db.execute("SELECT COUNT(*) FROM source_failures").fetchone()[0] == 0
    assert s.db.execute("SELECT headline FROM news_events").fetchall() == [("orijinal",)]
    s.close()


def test_schema_compatible_with_pre_revision_db_and_reopen_is_additive(tmp_path):
    import sqlite3
    s = SecondaryStore(tmp_path)
    s.add_news(item("orijinal"))
    path = s.path if hasattr(s, "path") else None
    s.close()
    path = path or next(tmp_path.rglob("*.sqlite"))
    db = sqlite3.connect(path)  # kontrollü test yolu: revizyon öncesi şemayı taklit et (canlı DB'ye dokunulmaz)
    db.execute("DROP TRIGGER IF EXISTS source_revisions_no_update")
    db.execute("DROP TRIGGER IF EXISTS source_revisions_no_delete")
    db.execute("DROP TABLE source_revisions")
    msg = f"DUPLICATE_CONFLICT: item_key={KEY} symbol=UNRESOLVED"
    rh = item("düzenleme").raw_hash
    db.executemany("INSERT INTO source_failures(provider, received_at, error_type, message, raw_hash, source_role) "
                   "VALUES ('foreks', ?, 'DUPLICATE_CONFLICT', ?, ?, ?)",
                   [((T + timedelta(minutes=5 * k)).isoformat(), msg, rh, SECONDARY_ROLE) for k in range(1, 4)])
    db.commit()
    before = {t: db.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in ("news_events", "source_failures")}
    db.close()
    s = SecondaryStore(tmp_path)  # yeniden açılış yalnız eksik tabloyu ekler
    assert {t: s.db.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in before} == before
    assert s.add_news(item("düzenleme", 30)) == REVISION_KNOWN  # eski kanıttan bir kez taşınır
    sql1 = s.db.execute("SELECT sql FROM sqlite_master WHERE name='source_revisions'").fetchone()[0]
    rows1 = s.db.execute("SELECT * FROM source_revisions").fetchall()
    s.close()
    s = SecondaryStore(tmp_path)  # ikinci açılış: drop/recreate yok, satırlar aynı
    assert s.db.execute("SELECT sql FROM sqlite_master WHERE name='source_revisions'").fetchone()[0] == sql1
    assert s.db.execute("SELECT * FROM source_revisions").fetchall() == rows1 and len(rows1) == 1
    assert rows1[0][6] == (T + timedelta(minutes=5)).isoformat()
    s.close()


def test_storage_conflict_at_write_logged_once_without_mutation(tmp_path):
    s = SecondaryStore(tmp_path)
    # kontrollü test: kanonik eklemeyi yok sayan tetikleyici → kanonik satır yok → STORAGE_CONFLICT
    s.db.execute("CREATE TRIGGER t_ignore BEFORE INSERT ON news_events BEGIN SELECT RAISE(IGNORE); END")
    assert s.add_news(item("x")) == STORAGE_CONFLICT
    assert s.add_news(item("x", 5)) == STORAGE_CONFLICT
    assert s.db.execute("SELECT error_type, COUNT(*) FROM source_failures GROUP BY 1").fetchall() == [
        ("STORAGE_CONFLICT", 1)]
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 0
    s.close()
    rv = report(tmp_path)["revision_quality"]
    assert rv["storage_conflicts"] >= 1


def test_archiver_counts_new_vs_known_and_ecb_not_double_counted(tmp_path):
    s = SecondaryStore(tmp_path)
    runs(s)
    s.add_news(item("orijinal"))
    msg = f"DUPLICATE_CONFLICT: item_key={KEY} symbol=UNRESOLVED"
    rev = item("düzenleme", 5)
    for k in range(3):  # eski sürüm satırları (ECB benzeri)
        s.log_failure(None, "foreks", T + timedelta(minutes=5 + k), msg, T, rev.raw_hash)
    s.add_news(item("düzenleme", 30))  # taşınır (bilinen)
    r = s.begin_run("foreks", "news_archive", {}, T + timedelta(minutes=31))
    s.finish_run(r, T + timedelta(minutes=31), "COMPLETED", {"source_revisions_new": 0, "source_revisions_known": 1,
                                                            "storage_conflicts": 0, "failures": 0})
    s.close()
    rv = report(tmp_path)["revision_quality"]
    assert rv["distinct_source_revisions"] == 1 and rv["source_revision_rows"] == 1  # ECB tek sayılır
    assert (rv["legacy_conflict_rows"], rv["distinct_revision_variants"], rv["legacy_known_revision_repeats"]) == (3, 1, 2)
    assert rv["legacy_revisions_migrated"] == 1 and rv["known_revision_repeats"] == 2 + 1


def test_continuity_threshold_stays_five_days(tmp_path):
    assert hl.READINESS["continuity_days_min"] == 5
    assert hl.READINESS["source_revisions_fail_readiness"] is False
    s = SecondaryStore(tmp_path)
    runs(s)
    s.add_news(item("haber"))
    s.close()
    rd = report(tmp_path)["catalyst_readiness"]
    assert rd["checks"]["source_continuity_days"] is False and rd["verdict"] != "READY"
