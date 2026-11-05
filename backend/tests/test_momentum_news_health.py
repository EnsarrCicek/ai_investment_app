"""Momentum haber arşivi veri kalitesi raporu (ağsız, salt okunur): model metriği yok, ileriye dönük keşif gecikmesi
ilk RSS birikiminden ayrılır, çözümlenemeyen haberlere sembol uydurulmaz, şirket adı teşhisi depoyu değiştirmez ve
bulanık değildir, holdout haberleri sonuçla birleştirilemez, zamanlayıcı kontrolü salt okunur, istatistikler
deterministik."""

import gzip
import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.research.momentum_pilot import split as sp
from app.research.momentum_sources import holdout
from app.research.momentum_sources.news_archive import health as hl
from app.research.momentum_sources.news_archive.models import NewsArchiveItem
from app.research.momentum_sources.storage import SecondaryStore

UTC = timezone.utc
START = datetime(2026, 11, 4, 8, 15, tzinfo=UTC)


def _item(key, symbol, pub, rec, head):
    return NewsArchiveItem(provider="foreks", source="Foreks", symbol=symbol, company=None, published_at=pub,
                           received_at=rec, headline=head, event_type="other", event_importance=None,
                           source_url_hash=hashlib.sha256(key.encode()).hexdigest(),
                           content_hash=hashlib.sha256(head.encode()).hexdigest(),
                           raw_hash=hashlib.sha256((key + head).encode()).hexdigest(), published_at_semantics="t",
                           item_key=key)


def _rss(keys_heads):
    body = "".join(f"<item><title>{h}</title><link>https://www.foreks.com/haber/detay/{k}/PICNEWS/tr/s</link>"
                   f"<guid>g{k}</guid><description>{h}</description></item>" for k, h in keys_heads)
    return f"<rss><channel>{body}</channel></rss>".encode()


@pytest.fixture
def store(tmp_path):
    root, raw = tmp_path / "s", tmp_path / "raw"
    s = SecondaryStore(root)
    feeds = [[("aaaaaaaaaaaaaaaaaaaaaa01", "GARAN haberi"), ("aaaaaaaaaaaaaaaaaaaaaa02", "Petrol fiyatları arttı")],
             [("aaaaaaaaaaaaaaaaaaaaaa01", "GARAN haberi"), ("aaaaaaaaaaaaaaaaaaaaaa02", "Petrol fiyatları arttı"),
              ("aaaaaaaaaaaaaaaaaaaaaa03", "Coca-Cola İçecek büyüme beklentisini yükseltti")]]
    for n, feed in enumerate(feeds):
        t = START + timedelta(minutes=5 * n)
        body = _rss(feed)
        h = hashlib.sha256(body).hexdigest()
        (raw / h[:2]).mkdir(parents=True, exist_ok=True)
        with gzip.open(raw / h[:2] / f"{h}.xml.gz", "wb") as f:
            f.write(body)
        run = s.begin_run("foreks", "news_archive", {"n": n}, t)
        s.finish_run(run, t + timedelta(seconds=3), "COMPLETED",
                     {"rss_items_in_feed": len(feed), "items_inserted": 2 if n == 0 else 1,
                      "duplicates": 0 if n == 0 else 2, "duplicate_conflicts": 0, "raw_response_sha256": h})
    s.add_news(_item("foreks:aaaaaaaaaaaaaaaaaaaaaa01", "GARAN", START - timedelta(hours=10), START, "GARAN haberi"))
    s.add_news(_item("foreks:aaaaaaaaaaaaaaaaaaaaaa02", "UNRESOLVED", START - timedelta(hours=2), START,
                     "Petrol fiyatları arttı"))
    s.add_news(_item("foreks:aaaaaaaaaaaaaaaaaaaaaa03", "UNRESOLVED", START + timedelta(minutes=2),
                     START + timedelta(minutes=5), "Coca-Cola İçecek büyüme beklentisini yükseltti"))
    s.close()
    return root, raw


def report(store):
    return hl.report(store[0], store[1], now=START + timedelta(hours=1), with_scheduler=False,
                     universe={"GARAN", "CCOLA"})


def _keys(d):
    if isinstance(d, dict):
        for k, v in d.items():
            yield str(k).lower()
            yield from _keys(v)
    elif isinstance(d, list):
        for v in d:
            yield from _keys(v)


def test_health_has_no_model_metric_keys(store):
    keys = " ".join(_keys(report(store)))
    assert not any(k in keys for k in hl.FORBIDDEN_KEYS)


def test_prospective_lag_separated_from_initial_backlog(store):
    ts = report(store)["timestamp_quality"]
    assert ts["archive_effective_start"] == START.isoformat()
    allv = ts["archival_discovery_lag_minutes_all_items"]
    assert allv["n"] == 3 and allv["max"] == 600.0 and "NOT provider network latency" in allv["metric_definition"]
    pro = ts["archival_discovery_lag_minutes_published_after_start"]
    assert pro["n"] == 1 and pro["median"] == 3.0 and ts["initial_backlog_items"] == 2


def test_unresolved_never_gets_invented_symbol(store):
    r = report(store)
    assert r["symbol_resolution"]["resolved_items"] == 1 and r["symbol_resolution"]["unresolved_items"] == 2
    assert r["symbol_resolution"]["top_resolved_symbols"] == [["GARAN", 1]] or \
        r["symbol_resolution"]["top_resolved_symbols"] == [("GARAN", 1)]
    s = SecondaryStore(store[0], readonly=True)
    assert s.db.execute("SELECT COUNT(*) FROM news_events WHERE symbol='CCOLA'").fetchone()[0] == 0
    s.close()


def test_company_name_diagnostic_does_not_mutate_store(store):
    path = store[0] / "secondary.sqlite"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    diag = report(store)["unresolved"]["company_name_diagnostic"]
    assert diag["potentially_resolvable_strict (FULL_NAME/SHORT_NAME)"] == 1 and diag["stored_records_mutated"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_name_matching_is_exact_not_fuzzy():
    forms = hl.name_forms({"AKBNK": "Akbank T.A.S.", "THYAO": "Türk Hava Yollari Anonim Ortakligi",
                           "TTKOM": "Türk Telekomünikasyon Anonim Sirketi"})
    assert hl.company_name_match("Akbank kâr açıkladı", forms)["SHORT_NAME"] == ["AKBNK"]
    for typo in ("Akbankk kâr açıkladı", "Akban kâr", "Ak bank kar"):
        assert not any(hl.company_name_match(typo, forms).values())
    assert hl.company_name_match("Türk Hava Yolları yolcu", forms)["SHORT_NAME"] == ["THYAO"]
    assert hl.company_name_match("Türk ekonomisi", forms)["AMBIGUOUS_FIRST_TOKEN"] == ["THYAO", "TTKOM"]


def test_company_names_read_without_executing_seed_script(monkeypatch):
    import app.repositories.asset_repository as ar
    monkeypatch.setattr(ar.AssetRepository, "__init__", lambda self: (_ for _ in ()).throw(AssertionError("ran")))
    names = hl.load_company_names()
    assert len(names) == 100 and names["AKBNK"].startswith("Akbank")


def test_holdout_raw_news_readable_but_outcome_join_forbidden(store):
    r = report(store)  # 2026-11-04 (holdout tarihli) ham haber veri kalitesi için okunur
    assert r["timestamp_quality"]["logical_items"] == 3
    holdout.assert_news_join_allowed(["2026-11-04"], [])  # birleştirme yok → serbest
    for field in holdout.FORBIDDEN_NEWS_JOINS:
        with pytest.raises(sp.HoldoutAccessError):
            holdout.assert_news_join_allowed(["2026-11-04"], [field])
    holdout.assert_news_join_allowed(["2026-10-30"], ["peak"])  # pilot tarihi
    src = inspect.getsource(hl)
    for forbidden in ("momentum_pilot import deep", "momentum_pilot import redesign", "ranking",
                      "momentum_collector import storage", "bars_as_of", "session_events"):
        assert forbidden not in src


def test_scheduler_health_is_read_only():
    src = inspect.getsource(hl.scheduler_health)
    assert "Get-ScheduledTask" in src and "Get-ScheduledTaskInfo" in src
    for verb in ("Register-ScheduledTask", "Set-ScheduledTask", "Unregister-ScheduledTask", "Start-ScheduledTask",
                 "Stop-ScheduledTask", "Disable-ScheduledTask", "Enable-ScheduledTask"):
        assert verb not in src


def test_statistics_deterministic(store):
    a, b = report(store), report(store)
    a.pop("generated_at"), b.pop("generated_at")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_duplicate_quality_from_raw_responses(store):
    d = report(store)["duplicate_quality"]
    assert d["fetches_with_raw_response"] == 2 and d["item_keys_seen_in_multiple_fetches"] == 2
    assert d["same_content_hash_different_item_key"] == 0 and d["records_rewritten"] is False
    c = report(store)["foreks_health"]
    assert c["raw_response_files"] == 2 == c["raw_response_files_hash_valid"] and c["raw_sha_all_present_on_disk"]
