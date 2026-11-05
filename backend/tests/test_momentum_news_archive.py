"""Momentum ileriye dönük haber arşivi (ağsız, Firestore'suz): ilk canlı çalıştırma depolama semantiği (taklit RSS),
tekil kilit, tekrar/çakışma, tarihsel öğe gerçek received_at'i korur, holdout ham toplama serbest / sonuç yasak,
zamanlayıcı komutu ve DryRun, loglar Git dışı, Yahoo görevlerine dokunulmaz."""

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.research.momentum_collector.ops import SingletonLock
from app.research.momentum_pilot import split as sp
from app.research.momentum_sources import holdout
from app.research.momentum_sources.news_archive import adapters as ad
from app.research.momentum_sources.news_archive import archiver
from app.research.momentum_sources.storage import SecondaryStore

UTC = timezone.utc
BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def rss(*items) -> bytes:
    body = "".join(f"<item><title>{t}</title><link>https://www.foreks.com/x?haber_id={hid}</link>"
                   f"<pubDate>{pd}</pubDate><description>{d}</description></item>" for hid, t, pd, d in items)
    return f"<rss><channel>{body}</channel></rss>".encode()


FEED = rss(("aa01", "AKBNK yeni sözleşme imzaladı", "Wed, 04 Nov 2026 08:30:00 GMT", "AKBNK ve GARAN"),
           ("bb02", "Piyasalarda genel görünüm", "Wed, 04 Nov 2026 08:00:00 GMT", "endeks"),
           ("cc03", "THYAO bilanço açıkladı", "Tue, 20 Oct 2026 15:00:00 GMT", "THYAO"))


@pytest.fixture
def no_firestore(monkeypatch):
    import app.core.firebase as fb
    monkeypatch.setattr(fb, "get_firestore_client", lambda: (_ for _ in ()).throw(AssertionError("Firestore!")))


def serve(monkeypatch, content: bytes):
    from app.services.news import foreks_news_provider as fnp
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(content=content, raise_for_status=lambda: None))
    assert fnp.requests is requests


def call(tmp_path, adapters=None):
    return archiver.invoke(["foreks"], root=tmp_path / "store" / "momentum_secondary",
                           lock_path=tmp_path / "store" / "locks" / "news_archive.lock",
                           log_dir=tmp_path / "store" / "logs",
                           adapters=adapters or [ad.ForeksArchiveAdapter(["AKBNK", "GARAN", "THYAO"])])


def test_first_live_run_storage_semantics(tmp_path, monkeypatch, no_firestore):
    serve(monkeypatch, FEED)
    before = datetime.now(UTC)
    code, res = call(tmp_path)
    r = res["foreks"]
    assert code == 0 and r["status"] == "COMPLETED"
    assert (r["rss_items_in_feed"], r["items_received"], r["items_resolved_to_universe"]) == (3, 3, 2)
    assert r["symbols_unresolved"] == 1 and r["symbols_resolved"] == 3
    assert r["items_inserted"] == 4 and r["duplicates"] == 0  # 3 sembol satırı + 1 UNRESOLVED (sembol uydurulmaz)
    s = SecondaryStore(tmp_path / "store" / "momentum_secondary", readonly=True)
    rows = s.db.execute("SELECT provider, source_role, symbol, published_at, received_at, item_key, timestamp_status "
                        "FROM news_events ORDER BY symbol").fetchall()
    s.close()
    assert {x[0] for x in rows} == {"foreks"} and {x[1] for x in rows} == {"EXPERIMENTAL_SECONDARY"}
    thy = next(x for x in rows if x[2] == "THYAO")
    assert thy[3] == "2026-10-20T15:00:00+00:00"  # orijinal yayın zamanı korunur
    assert datetime.fromisoformat(thy[4]) >= before  # tarihsel öğe: received_at = gerçek alım (bugün)
    assert thy[3] != thy[4] and thy[5] == "foreks:cc03" and thy[6] == "PUBLISHED_AT_FROM_SOURCE"
    unres = next(x for x in rows if x[2] == "UNRESOLVED")
    assert unres[5] == "foreks:bb02" and unres[3] == "2026-11-04T08:00:00+00:00"
    log = (tmp_path / "store" / "logs").glob("news_archive_*.log")
    line = next(log).read_text(encoding="utf-8")
    for k in ("run_id", "provider", "started_at", "finished_at", "exit_code", "items_received", "items_inserted",
              "duplicates", "failures", "symbols_resolved", "symbols_unresolved"):
        assert f'"{k}"' in line


def test_replay_duplicates_and_conflicts_never_overwrite(tmp_path, monkeypatch, no_firestore):
    serve(monkeypatch, FEED)
    call(tmp_path)
    _, res = call(tmp_path)
    assert res["foreks"]["items_inserted"] == 0 and res["foreks"]["duplicates"] == 4
    changed = rss(("aa01", "AKBNK yeni sözleşme imzaladı (güncellendi)", "Wed, 04 Nov 2026 08:30:00 GMT",
                   "AKBNK ve GARAN"))
    serve(monkeypatch, changed)
    code, res = call(tmp_path)
    assert res["foreks"]["source_revisions_new"] == 2 and res["foreks"]["items_inserted"] == 0 and code == 0
    _, res = call(tmp_path)  # aynı düzenleme tekrar görülür → yeni düzenleme değil
    assert res["foreks"]["source_revisions_new"] == 0 and res["foreks"]["source_revisions_known"] == 2
    assert res["foreks"]["storage_conflicts"] == 0 and res["foreks"]["failures"] == 0  # bilinen düzenleme hata değil
    s = SecondaryStore(tmp_path / "store" / "momentum_secondary", readonly=True)
    assert s.db.execute("SELECT DISTINCT headline FROM news_events WHERE item_key='foreks:aa01'").fetchall() == \
        [("AKBNK yeni sözleşme imzaladı",)]
    assert s.db.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 2  # iki sembol × bir düzenleme
    assert s.db.execute("SELECT COUNT(*) FROM source_failures").fetchone()[0] == 0  # düzenleme hata değildir
    s.close()


def test_current_foreks_link_format_and_raw_response_saved(tmp_path, monkeypatch, no_firestore):
    """Güncel Foreks bağlantısı `/haber/detay/<id>/…` (haber_id= yok): üretim filtresi 0 öğe döndürse de
    araştırma ayrıştırması aynı yanıttaki tüm öğeleri, guid'siz/kimliksiz uydurma olmadan saklar."""
    body = ("<rss><channel>"
            "<item><title>GARAN yeni kredi paketi</title>"
            "<link>https://www.foreks.com/haber/detay/6aeae54a95131d72027d620e/PICNEWS/tr/garan</link>"
            "<guid>https://www.foreks.com/haber/detay/6aeae54a95131d72027d620e/PICNEWS/tr/garan</guid>"
            "<pubDate>Wed, 04 Nov 2026 07:56:58 +0000</pubDate><description>GARAN</description></item>"
            "<item><title>Petrol fiyatları yükseldi</title><link>https://www.foreks.com/x/y</link>"
            "<guid>g-123</guid><description>x</description></item>"
            "</channel></rss>").encode()
    serve(monkeypatch, body)
    a = ad.ForeksArchiveAdapter(["GARAN"], raw_dir=tmp_path / "raw")
    items = a.fetch()
    assert a.last_stats["production_provider_items"] == 1  # üretim sağlayıcısı güncel bağlantı biçimini artık okur
    assert [(i.symbol, i.item_key) for i in items] == [("GARAN", "foreks:6aeae54a95131d72027d620e"),
                                                       ("UNRESOLVED", items[1].item_key)]
    assert items[1].item_key.startswith("foreks:guid-") and items[1].published_at is None
    assert items[1].timestamp_status == "UNVERIFIED"
    import hashlib
    h = hashlib.sha256(body).hexdigest()
    assert a.last_stats["raw_response_sha256"] == h and (tmp_path / "raw" / h[:2] / f"{h}.xml.gz").exists()


def test_raw_hash_and_content_hash_deterministic(monkeypatch, no_firestore):
    serve(monkeypatch, FEED)
    a = ad.ForeksArchiveAdapter(["AKBNK", "GARAN", "THYAO"]).fetch()
    b = ad.ForeksArchiveAdapter(["AKBNK", "GARAN", "THYAO"]).fetch()
    assert [(x.raw_hash, x.content_hash) for x in a] == [(x.raw_hash, x.content_hash) for x in b]


def test_singleton_skips_and_stale_lock_does_not_block(tmp_path, monkeypatch, no_firestore):
    serve(monkeypatch, FEED)
    lock = tmp_path / "store" / "locks" / "news_archive.lock"
    with SingletonLock(lock):
        code, res = call(tmp_path)
    assert code == 0 and res["status"] == "SKIPPED_ALREADY_RUNNING"
    assert not (tmp_path / "store" / "momentum_secondary" / "secondary.sqlite").exists()
    assert lock.exists()  # bayat kilit dosyası kalsa da
    code, res = call(tmp_path)
    assert code == 0 and res["foreks"]["status"] == "COMPLETED"


def test_provider_failure_logged_exit_partial(tmp_path, monkeypatch, no_firestore):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", boom)
    code, res = call(tmp_path)  # sağlayıcı hatayı [] ile yutar; adaptör bunu hata olarak yüzeye çıkarır
    assert code == 3 and res["foreks"]["status"] == "FAILED" and "FOREKS_FEED_UNAVAILABLE" in res["foreks"]["error"]
    s = SecondaryStore(tmp_path / "store" / "momentum_secondary", readonly=True)
    assert s.db.execute("SELECT error_type FROM source_failures").fetchall() == [("FeedUnavailable",)]
    s.close()
    code, res = call(tmp_path, adapters=[ad.KapArchiveAdapter()])
    assert code == 3 and "KAP_SOURCE_NOT_CONFIGURED" in res["kap"]["error"]


def test_holdout_raw_news_allowed_but_outcomes_forbidden(tmp_path, monkeypatch, no_firestore):
    serve(monkeypatch, FEED)  # 2026-11-04 tarihli (holdout) haber
    code, res = call(tmp_path)
    assert code == 0 and res["foreks"]["items_inserted"] == 4
    assert holdout.raw_collection_allowed(date(2026, 11, 4))
    for kind in holdout.OUTCOME_KINDS:
        with pytest.raises(sp.HoldoutAccessError):
            holdout.assert_outcome_analysis_allowed(["2026-11-04"], kind)


def test_archiver_module_has_no_outcome_logic():
    import inspect
    src = inspect.getsource(archiver).lower()
    for word in ("label", "precision", "recall", "fpr", "session_events", "momentum_pilot.deep", "ranking"):
        assert word not in src


def test_logs_and_store_outside_git():
    for p in ("app/research/momentum_sources/store/logs/news_archive_2026-11-04.log",
              "app/research/momentum_sources/store/locks/news_archive.lock",
              "app/research/momentum_sources/store/momentum_secondary/secondary.sqlite"):
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=BACKEND)
        assert r.returncode == 0, p
    assert archiver.LOG_DIR == BACKEND / "app/research/momentum_sources/store/logs"
    assert archiver.LOCK_PATH == BACKEND / "app/research/momentum_sources/store/locks/news_archive.lock"


def test_scheduler_command_and_working_directory():
    ps1 = (BACKEND / "scripts" / "install_momentum_news_archive_task.ps1").read_text(encoding="utf-8")
    vbs = (BACKEND / "scripts" / "run_hidden_news_archive_task.vbs").read_text(encoding="utf-8")
    cmd = "-X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks"
    assert cmd in ps1 and cmd in vbs and "google" not in vbs.lower() and "yahoo" not in vbs.lower()
    assert '$TaskName = "MomentumProspectiveNewsArchive"' in ps1 and "-WorkingDirectory $BackendDir" in ps1
    assert '$WindowStart = "09:30"' in ps1 and '$WindowEnd = "18:40"' in ps1 and "$CadenceMinutes = 5" in ps1
    assert '$CatchUp = "19:10"' in ps1 and "IgnoreNew" in ps1 and "-StartWhenAvailable" in ps1
    assert "task_news_stdout.log" in vbs and 'sh.CurrentDirectory = backend' in vbs


def _export(name: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
                        "if ($t) { Export-ScheduledTask -TaskName $t.TaskName } else { 'ABSENT' }"],
                       capture_output=True, text=True)
    return r.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler")
def test_dry_run_creates_or_changes_no_task_and_yahoo_untouched():
    names = ("MomentumProspectiveNewsArchive", "MomentumProspectiveProbe", "MomentumProspectiveEOD")
    before = {n: _export(n) for n in names}
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(BACKEND / "scripts" / "install_momentum_news_archive_task.ps1"), "-DryRun", "-Json"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "DRY RUN" in r.stdout
    assert {n: _export(n) for n in names} == before
