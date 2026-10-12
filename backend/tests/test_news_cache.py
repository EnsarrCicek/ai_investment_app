"""Haber önbelleği soğuk başlangıç: toplu ilk yükleme, artımlı güncelleme, değişiklik güvenliği, tek uçuş ve eski
yükleyiciyle karar eşitliği. Gerçek Firestore yok."""

import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import DecisionEngine
from app.services.decisions import dashboard as db
from tests.test_dashboard_quota import NOW, SYMBOLS, Config, Macro, News, Raw, deps, doc_id, news, raw


def build(symbols, news_repo, raw_repo, cache, **kw):
    return db.build_dashboard(symbols, "FIRESTORE", deps(news_repo, raw_repo, cache=cache, **kw), now=NOW)


# --- A–I ---------------------------------------------------------------------------------------------------------

def test_A_cold_100_assets_single_bulk_load():
    news_repo = News({s: [news(s, f"{s}-n{i}", 10.0, NOW - timedelta(hours=i + 1)) for i in range(5)] for s in SYMBOLS})
    raw_repo = Raw({})
    out = build(SYMBOLS, news_repo, raw_repo, db.NewsReadCache())
    assert len(out["items"]) == 100
    assert news_repo.full_calls == 1 and news_repo.incremental_calls == 0 and not news_repo.list_calls
    assert news_repo.docs_read == 500 and raw_repo.batch_calls == 1 and len(raw_repo.calls) == 500


class SlowNews(News):
    """İlk toplu yüklemeyi bir Event'e kadar bekletir (tek uçuşu sınamak için)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.gate, self.entered = threading.Event(), threading.Event()

    def list_all_with_ids(self):
        self.entered.set()
        self.gate.wait(timeout=5)
        return super().list_all_with_ids()


def test_B_concurrent_cold_access_loads_once():
    news_repo, raw_repo, cache = SlowNews({"AAA": [news("AAA", "a1", 10.0)]}), Raw({}), db.NewsReadCache()
    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.prepare(news_repo, raw_repo, ["AAA"], timeout=5)))
               for _ in range(8)]
    for t in threads:
        t.start()
    assert news_repo.entered.wait(timeout=5)
    news_repo.gate.set()
    for t in threads:
        t.join(timeout=5)
    assert len(results) == 8 and news_repo.full_calls == 1
    assert all(r.analyses("AAA")[0].news_id == "a1" for r in results)


def test_C_two_concurrent_dashboard_requests_fill_once():
    news_repo, raw_repo, cache = SlowNews({"AAA": [news("AAA", "a1", 10.0)]}), Raw({}), db.NewsReadCache()
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(build(["AAA"], news_repo, raw_repo, cache)))
               for _ in range(2)]
    for t in threads:
        t.start()
    assert news_repo.entered.wait(timeout=5)
    news_repo.gate.set()
    for t in threads:
        t.join(timeout=10)
    assert len(outs) == 2 and news_repo.full_calls == 1
    assert outs[0]["items"][0]["news_score"] == outs[1]["items"][0]["news_score"]


def test_D_warm_request_reads_no_history():
    news_repo, raw_repo, cache = News({"AAA": [news("AAA", "a1", 10.0)]}), Raw({}), db.NewsReadCache()
    build(["AAA"], news_repo, raw_repo, cache)
    before = news_repo.docs_read
    build(["AAA"], news_repo, raw_repo, cache)
    assert news_repo.docs_read == before and news_repo.full_calls == 1 and news_repo.incremental_calls == 0
    assert news_repo.count_calls == 2 and news_repo.marker_calls == 2  # yalnız anahtar (2 okuma/istek)


def test_E_append_reads_only_new_docs():
    old = [news("AAA", f"a{i}", 10.0, NOW - timedelta(hours=10 + i)) for i in range(20)]
    news_repo, raw_repo, cache = News({"AAA": list(old), "BBB": []}), Raw({}), db.NewsReadCache()
    build(["AAA", "BBB"], news_repo, raw_repo, cache)
    read_after_full = news_repo.docs_read
    news_repo.by_asset["BBB"].append(news("BBB", "b1", -20.0, NOW - timedelta(minutes=5)))
    out = build(["AAA", "BBB"], news_repo, raw_repo, cache)
    assert news_repo.full_calls == 1 and news_repo.incremental_calls == 1
    assert news_repo.docs_read - read_after_full == 2  # sınır kaydı (en yeni eski kayıt) + yeni kayıt
    assert {i["asset"]: i["news_score"] for i in out["items"]}["BBB"] == pytest.approx(-20.0)


def test_F_same_timestamp_inserts_are_not_missed():
    t = NOW - timedelta(hours=1)
    news_repo, raw_repo, cache = News({"AAA": [news("AAA", "a1", 10.0, t)]}), Raw({}), db.NewsReadCache()
    build(["AAA"], news_repo, raw_repo, cache)
    # iki yeni kayıt: biri mevcut en yeniyle AYNI zaman damgasında, biri daha yeni ama ikisi de aynı anda
    news_repo.by_asset["AAA"] += [news("AAA", "a2", 20.0, t), news("AAA", "a3", 30.0, t)]
    build(["AAA"], news_repo, raw_repo, cache)
    assert news_repo.full_calls == 1 and news_repo.incremental_calls == 1
    snap = cache.prepare(news_repo, raw_repo, ["AAA"], timeout=1)
    assert {a.news_id for a in snap.analyses("AAA")} == {"a1", "a2", "a3"}


def test_G_late_old_timestamp_insert_triggers_full_rebuild():
    news_repo, raw_repo, cache = News({"AAA": [news("AAA", "a1", 10.0, NOW - timedelta(hours=1))]}), Raw({}), \
        db.NewsReadCache()
    build(["AAA"], news_repo, raw_repo, cache)
    # başka bir yazıcı saati geride: yeni kayıt mevcut en yeniden ESKİ zaman damgalı → artımlı okuma göremez
    news_repo.by_asset["AAA"].append(news("AAA", "late", -50.0, NOW - timedelta(hours=5)))
    build(["AAA"], news_repo, raw_repo, cache)
    assert news_repo.incremental_calls == 1 and news_repo.full_calls == 2  # sayı tutmadı → tam yeniden yükleme
    assert "late" in {a.news_id for a in cache.prepare(news_repo, raw_repo, ["AAA"], timeout=1).analyses("AAA")}


def test_H_admin_mutation_and_reseed_do_not_stay_stale():
    clock = [0.0]
    cache = db.NewsReadCache(clock=lambda: clock[0], reconcile_seconds=3600)
    news_repo, raw_repo = News({"AAA": [news("AAA", "a1", 10.0, NOW - timedelta(hours=1))]}), Raw({})
    build(["AAA"], news_repo, raw_repo, cache)
    # konsoldan yerinde güncelleme: sayı/işaret aynı → anahtar değişmez; uzlaştırmaya kadar eski değer
    news_repo.by_asset["AAA"][0] = news("AAA", "a1", -90.0, NOW - timedelta(hours=1))
    assert build(["AAA"], news_repo, raw_repo, cache)["items"][0]["news_score"] == pytest.approx(10.0)
    clock[0] = 3600.0
    assert build(["AAA"], news_repo, raw_repo, cache)["items"][0]["news_score"] == pytest.approx(-90.0)
    # yeniden yükleme (reseed): tamamen farklı küme, aynı sayı → işaret değişir → tam yeniden yükleme
    news_repo.by_asset["AAA"] = [news("AAA", "z9", 40.0, NOW - timedelta(minutes=1))]
    out = build(["AAA"], news_repo, raw_repo, cache)
    assert out["items"][0]["news_score"] == pytest.approx(40.0) and news_repo.full_calls == 3


def test_I_raw_shared_by_multiple_analyses_read_once():
    shared = "shared-1"
    news_repo = News({"AAA": [news("AAA", shared, 10.0)], "BBB": [news("BBB", shared, 20.0)]})
    raw_repo = Raw({shared: raw(shared, "Ortak haber", NOW - timedelta(hours=3))})
    build(["AAA", "BBB"], news_repo, raw_repo, db.NewsReadCache())
    assert raw_repo.calls[shared] == 1 and raw_repo.batch_calls == 1


def test_news_load_wait_respects_dashboard_deadline():
    """Başka isteğin süren yüklemesi bütçeyi aşarsa bu istek hiçbir iş başlatmadan açık deadline satırları döner."""
    news_repo, raw_repo, cache = SlowNews({"AAA": [news("AAA", "a1", 10.0)]}), Raw({}), db.NewsReadCache()
    holder = threading.Thread(target=lambda: cache.prepare(news_repo, raw_repo, ["AAA"], timeout=5))
    holder.start()
    assert news_repo.entered.wait(timeout=5)
    calls = []
    d = deps(news_repo, raw_repo, cache=cache)
    d.technical_engine_factory = lambda *a: calls.append(1)
    started = time.monotonic()
    out = db.build_dashboard(["AAA", "BBB"], "FIRESTORE", d, now=NOW, budget_seconds=0.2)
    assert time.monotonic() - started < 2 and calls == []
    assert {(i["status"], i["reason"]) for i in out["items"]} == {("ERROR", db.DEADLINE_EXCEEDED)}
    news_repo.gate.set()
    holder.join(timeout=5)


# --- J: eski yükleyiciyle karar eşitliği -------------------------------------------------------------------------

class FirestoreLikeNews:
    """Gerçek `NewsAnalysisRepository.list_for_asset` sırası: where(asset) akışı belge kimliğine göre artan, sonra
    created_at azalan kararlı sıralama. Eski (varlık başına) yükleyici budur."""

    def __init__(self, news_repo):
        self._repo = news_repo

    def list_for_asset(self, asset, limit=None):
        docs = sorted((d for d in self._repo._docs() if d[1].asset == asset), key=lambda d: d[0])
        records = [a for _, a in docs]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records if limit is None else records[:limit]


H = lambda h: NOW - timedelta(hours=h)  # noqa: E731

SCENARIOS = {
    "no_news": ({"AAA": []}, {}),
    "one_news": ({"AAA": [news("AAA", "a1", 40.0, H(2))]}, {"a1": raw("a1", "AAA kâr açıkladı", H(3))}),
    "duplicate_same_event": (
        {"AAA": [news("AAA", "a1", 60.0, H(5)), news("AAA", "a2", 50.0, H(4))]},
        {"a1": raw("a1", "AAA rekor kâr açıkladı", H(6)), "a2": raw("a2", "AAA rekor kâr açıkladı", H(5))}),
    "many_old_and_new": (
        {"AAA": [news("AAA", f"o{i}", float((-1) ** i * (10 + i)), H(24 * i + 1)) for i in range(25)]},
        {f"o{i}": raw(f"o{i}", f"AAA olay {i} duyurusu", H(24 * i + 2)) for i in range(25)}),
    "unreliable_source": (
        {"AAA": [news("AAA", "u1", 80.0, H(2)), news("AAA", "r1", -20.0, H(3))]},
        {"u1": raw("u1", "AAA söylenti", H(3)).model_copy(update={"source_reliability": 0.1}),
         "r1": raw("r1", "AAA resmi açıklama", H(4))}),
    "multiple_assets_shared_news_id": (
        {"AAA": [news("AAA", "s1", 30.0, H(2))], "BBB": [news("BBB", "s1", -30.0, H(2))],
         "CCC": [news("CCC", "c1", 5.0, H(1))]},
        {"s1": raw("s1", "Sektör haberi", H(3)), "c1": raw("c1", "CCC haberi", H(2))}),
    "duplicate_news_id_same_asset": (  # aynı haber aynı varlık için iki kez analiz edilmiş: sıra duyarlı
        {"AAA": [news("AAA", "d1", 10.0, H(3)), news("AAA", "d1", 70.0, H(1))]},
        {"d1": raw("d1", "AAA tekrar analiz", H(4))}),
    "missing_raw": ({"AAA": [news("AAA", "m1", 25.0, H(2))]}, {}),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_J_decision_equivalence_with_per_asset_loader(name):
    by_asset, raws = SCENARIOS[name]
    if name == "duplicate_news_id_same_asset":  # aynı news_id'li iki belge: kimlikleri ayrı olmalı
        by_asset = {"AAA": [by_asset["AAA"][0], by_asset["AAA"][1].model_copy(update={"asset": "AAA"})]}
    news_repo = News({k: list(v) for k, v in by_asset.items()})
    if name == "duplicate_news_id_same_asset":
        docs = [("doc-x1", by_asset["AAA"][0]), ("doc-x0", by_asset["AAA"][1])]
        news_repo._docs = lambda: list(docs)
    symbols = sorted(by_asset)
    out = build(symbols, news_repo, Raw(raws), db.NewsReadCache(), score=lambda _s: 12.0)
    dash = {i["asset"]: i for i in out["items"]}
    for symbol in symbols:
        class Tech:
            def analyze_with_id(self, s, persist=True):
                return SimpleNamespace(technical_score=12.0), None

        single = DecisionEngine(config_repo=Config(), decision_repo=SimpleNamespace(add=None)).decide_for_asset(
            symbol, technical_engine=Tech(), macro_repo=Macro(), news_repo=FirestoreLikeNews(news_repo),
            news_raw_repo=Raw(raws), persist=False)
        item = dash[symbol]
        assert item["decision"] == single.decision
        for key in ("final_score", "news_score", "confidence", "channel_completeness", "technical_score", "macro_score"):
            assert item[key] == pytest.approx(getattr(single, key)), (name, symbol, key)
        # seçilen haber kimlikleri aynı (dashboard yanıtı kimlik taşımadığından aynı girdilerle yeniden seçilir)
        snap = db.NewsReadCache().prepare(news_repo, Raw(raws), [symbol], timeout=1)
        from app.services.news.news_selection import select_recent_unique_news_analyses
        dash_ids = [w.analysis.news_id for w in select_recent_unique_news_analyses(
            symbol, db.CachedNewsRepository(snap), db.CachedNewsRawRepository(snap), as_of=NOW)]
        old_ids = [w.analysis.news_id for w in select_recent_unique_news_analyses(
            symbol, FirestoreLikeNews(news_repo), Raw(raws), as_of=NOW)]
        assert dash_ids == old_ids
        assert single.news_analysis_ids == old_ids or single.news_score is None


def test_doc_id_helper_matches_marker():
    repo = News({"AAA": [news("AAA", "a1", 1.0)]})
    assert repo.latest_marker()[0] == doc_id(repo.by_asset["AAA"][0])
