"""Dashboard Firestore kota optimizasyonu — sahte depolarla okuma/yazma sayımı, sonuç eşitliği, 503 ve yerel mod.
Gerçek Firestore'a ERİŞİLMEZ."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.api_core.exceptions import ResourceExhausted

from app.api import assets as assets_api
from app.api import decisions as decisions_api
from app.api import portfolio as portfolio_api
from app.core import firestore_errors
from app.core.auth import get_current_user_id
from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, DecisionEngine
from app.engines.technical.engine import TECHNICAL_CACHE_TTL_SECONDS
from app.models.asset import Asset
from app.models.macro_snapshot import MacroSnapshot
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.services.assets import asset_catalog as ac
from app.services.decisions import dashboard as db

UTC = timezone.utc
NOW = datetime.now(UTC)
SYMBOLS = [f"S{i:03d}" for i in range(100)]
TECH_KEYS = ("technical_indicator_weights", "technical_family_weights")


@pytest.fixture(autouse=True)
def _production_env(monkeypatch):
    monkeypatch.delenv("LOCAL_LAN_DEV", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)


def local_mode(monkeypatch):
    monkeypatch.setenv("LOCAL_LAN_DEV", "1")


class Config:
    def __init__(self):
        self.reads = Counter()

    def get_raw(self, key):
        self.reads[key] += 1
        return {"decision_weights": dict(DEFAULT_WEIGHTS), "decision_thresholds": dict(DEFAULT_THRESHOLDS)}.get(
            key, {"w": 1.0})


class Macro:
    def __init__(self, error=None):
        self.reads, self.error = 0, error

    def get_latest_with_id(self):
        self.reads += 1
        if self.error:
            raise self.error
        return MacroSnapshot(macro_score=-20.0, confidence=0.8, components={}, indicators={},
                             created_at=NOW - timedelta(days=1)), "macro-1"


class TechRepo:
    def __init__(self, records=(), error=None):
        self.calls, self.records, self.error = [], list(records), error

    def list_created_since(self, cutoff):
        self.calls.append(cutoff)
        if self.error:
            raise self.error
        return list(self.records)


class Benchmark:
    def __init__(self):
        self.reads, self.writes = 0, 0

    def get(self):
        self.reads += 1
        return None

    def set(self, *_a):
        self.writes += 1


def news(asset, news_id, sentiment, created_at=None):
    return NewsAnalysis(news_id=news_id, asset=asset, sentiment_score=sentiment, confidence=0.8, importance=0.5,
                        event_type="other", reasoning="r", model_used="gpt-5.6-luna",
                        created_at=created_at or NOW - timedelta(hours=2))


def raw(external_id, title, published_at):
    return NewsRawItem(external_id=external_id, title=title, summary="özet", url=f"https://e.com/{external_id}",
                       publisher="Reuters", source="google_news_rss", source_reliability=0.8, related_assets=["X"],
                       published_at=published_at, received_at=published_at)


class News:
    def __init__(self, by_asset, count=None, fail_assets=()):
        self.by_asset, self.count, self.fail_assets = by_asset, count, set(fail_assets)
        self.list_calls, self.count_calls, self.marker_calls = Counter(), 0, 0

    def count_all(self):
        self.count_calls += 1
        return self.count if self.count is not None else sum(len(v) for v in self.by_asset.values())

    def latest_marker(self):
        self.marker_calls += 1
        records = [a for v in self.by_asset.values() for a in v]
        if not records:
            return None
        latest = max(records, key=lambda a: (a.created_at, a.news_id))
        return latest.news_id, latest.created_at

    def list_for_asset(self, asset, limit=None):
        self.list_calls[asset] += 1
        if asset in self.fail_assets:
            raise ResourceExhausted("quota")
        return list(self.by_asset.get(asset, []))


class Raw:
    def __init__(self, raws):
        self.raws, self.calls = raws, Counter()

    def get_by_external_id(self, external_id):
        self.calls[external_id] += 1
        return self.raws.get(external_id)


class FakeTechnical:
    """Gerçek motorun okuduğu ortak bağımlılıkları aynı şekilde okur: 2 config anahtarı, cache, benchmark."""

    def __init__(self, config_repo, analysis_repo, benchmark_repo, score):
        self.config_repo, self.analysis_repo, self.benchmark_repo, self.score = (config_repo, analysis_repo,
                                                                                 benchmark_repo, score)

    def analyze_with_id(self, symbol, persist=True):
        assert persist is False
        for key in TECH_KEYS:
            self.config_repo.get_raw(key)
        self.analysis_repo.get_latest_with_id(symbol)
        self.benchmark_repo.get()
        return SimpleNamespace(technical_score=self.score(symbol)), None


def score_of(symbol):
    return float(int(symbol[1:]) - 50) if symbol[1:].isdigit() else 10.0


def deps(news_repo=None, raw_repo=None, cache=None, **kw):
    return db.DashboardDependencies(
        config_repo=kw.get("config") or Config(), macro_repo=kw.get("macro") or Macro(),
        technical_repo=kw.get("tech") or TechRepo(), benchmark_cache_repo=kw.get("bench") or Benchmark(),
        news_repo=news_repo or News({}), news_raw_repo=raw_repo or Raw({}),
        technical_engine_factory=lambda c, a, b: FakeTechnical(c, a, b, kw.get("score", score_of)),
        news_cache=cache or db.NewsReadCache())


@pytest.fixture(autouse=True)
def _no_real_decision_repo(monkeypatch):
    # Dashboard hiçbir koşulda gerçek AIDecisionRepository kurmamalı (yazma yolu yok).
    monkeypatch.setattr("app.engines.decision.engine.AIDecisionRepository",
                        lambda: (_ for _ in ()).throw(AssertionError("AIDecisionRepository kurulmamalı")))


# --- okuma/yazma sayıları ----------------------------------------------------------------------------------------

def test_100_symbols_global_reads_once_and_no_writes():
    config, macro, tech, bench = Config(), Macro(), TechRepo(), Benchmark()
    news_repo = News({s: [news(s, f"{s}-n1", 40.0)] for s in SYMBOLS})
    raw_repo = Raw({f"{s}-n1": raw(f"{s}-n1", f"{s} haber", NOW - timedelta(hours=3)) for s in SYMBOLS})
    out = db.build_dashboard(SYMBOLS, "FIRESTORE", deps(news_repo, raw_repo, config=config, macro=macro, tech=tech,
                                                        bench=bench), now=NOW)
    assert len(out["items"]) == 100 and {i["status"] for i in out["items"]} == {"OK"}
    assert out["mode"] == "NORMAL" and out["reason"] is None
    # Global bağımlılıklar O(1): her config anahtarı bir kez, makro/benchmark/teknik pencere/sayım bir kez.
    assert config.reads == Counter({"decision_weights": 1, "decision_thresholds": 1,
                                    TECH_KEYS[0]: 1, TECH_KEYS[1]: 1})
    assert macro.reads == 1 and bench.reads == 1 and len(tech.calls) == 1
    assert news_repo.count_calls == 1 and news_repo.marker_calls == 1  # istek başına, varlık başına değil
    # Varlık başına: haber listesi bir kez; ham kayıt analiz başına bir kez (eskiden iki kez).
    assert set(news_repo.list_calls.values()) == {1} and len(news_repo.list_calls) == 100
    assert set(raw_repo.calls.values()) == {1}
    assert bench.writes == 0  # yazma yok (karar yazımı fixture ile ayrıca engelli)
    # Teknik cache penceresi: TTL + pay kadar geri.
    assert tech.calls[0] == NOW - timedelta(seconds=TECHNICAL_CACHE_TTL_SECONDS) - db.TECHNICAL_WINDOW_MARGIN
    scores = [i["final_score"] for i in out["items"]]
    assert scores == sorted(scores, reverse=True)


def test_second_request_reuses_news_cache_and_count_change_invalidates():
    cache = db.NewsReadCache()
    news_repo = News({"AAA": [news("AAA", "a1", 30.0)]})
    raw_repo = Raw({"a1": raw("a1", "AAA kâr", NOW - timedelta(hours=3))})
    for _ in range(3):
        db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, raw_repo, cache=cache), now=NOW)
    assert news_repo.list_calls["AAA"] == 1 and raw_repo.calls["a1"] == 1 and news_repo.count_calls == 3
    news_repo.by_asset["AAA"].append(news("AAA", "a2", -30.0))  # yeni analiz → sayı değişti
    out = db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, raw_repo, cache=cache), now=NOW)
    assert news_repo.list_calls["AAA"] == 2
    assert out["items"][0]["news_score"] is not None


def test_news_cache_expires_by_ttl():
    clock = [0.0]
    cache = db.NewsReadCache(ttl_seconds=10, clock=lambda: clock[0])
    news_repo = News({"AAA": [news("AAA", "a1", 30.0)]})
    db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, Raw({}), cache=cache), now=NOW)
    clock[0] = 11.0
    db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, Raw({}), cache=cache), now=NOW)
    assert news_repo.list_calls["AAA"] == 2


def test_dashboard_result_equals_single_symbol_engine():
    """Aynı veriyle tekil `decide_for_asset` ile birebir aynı karar (dedup + kaynak güvenilirliği dahil)."""
    analyses = [news("AAA", "a1", 60.0, NOW - timedelta(hours=5)), news("AAA", "a2", 50.0, NOW - timedelta(hours=4)),
                news("AAA", "a3", -40.0, NOW - timedelta(hours=1))]
    raws = {"a1": raw("a1", "AAA rekor kâr açıkladı", NOW - timedelta(hours=6)),
            "a2": raw("a2", "AAA rekor kâr açıkladı", NOW - timedelta(hours=5)),  # a1 ile aynı olay
            "a3": raw("a3", "AAA yatırım planını erteledi", NOW - timedelta(hours=2))}
    out = db.build_dashboard(["AAA"], "FIRESTORE", deps(News({"AAA": analyses}), Raw(raws), score=lambda _s: 25.0),
                             now=NOW)
    (item,) = out["items"]

    class Tech:
        def analyze_with_id(self, symbol, persist=True):
            return SimpleNamespace(technical_score=25.0), None

    class Plain:
        def list_for_asset(self, asset, limit=None):
            return list(analyses)

    single = DecisionEngine(config_repo=Config(), decision_repo=SimpleNamespace(add=None)).decide_for_asset(
        "AAA", technical_engine=Tech(), macro_repo=Macro(), news_repo=Plain(), news_raw_repo=Raw(raws), persist=False)
    for key in ("final_score", "news_score", "technical_score", "macro_score", "confidence", "channel_completeness"):
        assert item[key] == pytest.approx(getattr(single, key))
    assert item["decision"] == single.decision


def test_user_data_never_read_and_no_notification(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dashboard kullanıcı verisi/bildirim kullanmamalı")

    monkeypatch.setattr(decisions_api, "PortfolioRepository", boom)
    monkeypatch.setattr(decisions_api, "notify_if_strong_decision", boom)
    monkeypatch.setattr(decisions_api, "notify_if_new_opportunity", boom)
    client, _ = dashboard_client(monkeypatch)
    assert client.get("/decisions/dashboard").status_code == 200


def test_windowed_technical_repo_returns_latest_per_asset():
    a_old = SimpleNamespace(asset="AAA", created_at=NOW - timedelta(minutes=10))
    a_new = SimpleNamespace(asset="AAA", created_at=NOW - timedelta(minutes=2))
    repo = db.WindowedTechnicalAnalysisRepository([("x", a_old), ("y", a_new)])
    assert repo.get_latest_with_id("AAA") == (a_new, "y")
    assert repo.get_latest_with_id("BBB") == (None, None)


def test_benchmark_set_is_request_local_and_not_written():
    inner = Benchmark()
    repo = db.RequestBenchmarkCacheRepository(inner)
    repo.set({"2026-01-01": 1.0}, NOW)
    assert repo.get() == ({"2026-01-01": 1.0}, NOW) and inner.writes == 0 and inner.reads == 0


def test_row_level_value_error_does_not_fail_request():
    def score(symbol):
        if symbol == "BAD":
            raise ValueError("fiyat alınamadı")
        return 10.0

    out = db.build_dashboard(["BAD", "OK1"], "FIRESTORE", deps(score=score), now=NOW)
    by = {i["asset"]: i for i in out["items"]}
    assert by["BAD"]["status"] == "ERROR" and "fiyat alınamadı" in by["BAD"]["reason"]
    assert by["BAD"]["final_score"] is None and by["OK1"]["status"] == "OK"
    assert out["items"][-1]["asset"] == "BAD"  # karar üretilemeyen en altta


# --- kota hatası: üretim 503, yerel açık işaretli eksik veri ----------------------------------------------------

def test_quota_in_production_raises():
    with pytest.raises(ResourceExhausted):
        db.build_dashboard(SYMBOLS, "FIRESTORE", deps(tech=TechRepo(error=ResourceExhausted("q"))), now=NOW)
    with pytest.raises(ResourceExhausted):
        db.build_dashboard(["AAA"], "FIRESTORE", deps(News({}, fail_assets={"AAA"})), now=NOW)


def test_local_degraded_mode_marks_unavailable_without_numbers(monkeypatch):
    local_mode(monkeypatch)
    out = db.build_dashboard(SYMBOLS, "LOCAL_SEED_FALLBACK", deps(macro=Macro(error=ResourceExhausted("q"))), now=NOW)
    assert out["mode"] == "LOCAL_DEGRADED" and out["reason"] == "FIRESTORE_QUOTA_EXHAUSTED"
    assert len(out["items"]) == 100
    for item in out["items"]:
        assert item["status"] == "UNAVAILABLE" and item["reason"] == "FIRESTORE_QUOTA_EXHAUSTED"
        assert all(item[k] is None for k in ("decision", "final_score", "technical_score", "news_score", "macro_score",
                                             "confidence", "channel_completeness"))


def test_local_row_quota_marks_only_that_row(monkeypatch):
    local_mode(monkeypatch)
    out = db.build_dashboard(["AAA", "BBB"], "FIRESTORE", deps(News({}, fail_assets={"AAA"})), now=NOW)
    by = {i["asset"]: i for i in out["items"]}
    assert by["AAA"]["status"] == "UNAVAILABLE" and by["AAA"]["final_score"] is None
    assert by["BBB"]["status"] == "OK" and out["mode"] == "LOCAL_DEGRADED"


def test_cloud_run_never_degrades_even_with_flag(monkeypatch):
    local_mode(monkeypatch)
    monkeypatch.setenv("K_SERVICE", "ai-investment-backend")
    with pytest.raises(ResourceExhausted):
        db.build_dashboard(["AAA"], "FIRESTORE", deps(macro=Macro(error=ResourceExhausted("q"))), now=NOW)


# --- varlık kataloğu ---------------------------------------------------------------------------------------------

ASSETS = [Asset(symbol="AAA", name="A", market="BIST", asset_type="STOCK", currency="TRY")]


def test_asset_catalog_ttl_cache_and_no_stale_on_error():
    clock, calls, fail = [0.0], [0], [False]

    def load():
        calls[0] += 1
        if fail[0]:
            raise ResourceExhausted("q")
        return list(ASSETS)

    catalog = ac.AssetCatalog(load, ttl_seconds=60, clock=lambda: clock[0])
    assert catalog.list_active() == (ASSETS, "FIRESTORE") and catalog.list_active()[1] == "FIRESTORE"
    assert calls[0] == 1
    clock[0], fail[0] = 61.0, True
    with pytest.raises(ResourceExhausted):  # süresi dolmuş önbellek sessizce sunulmaz
        catalog.list_active()
    returned, _ = ac.AssetCatalog(lambda: list(ASSETS)).list_active()
    returned[0].name = "değişti"
    assert ASSETS[0].name == "A"


def test_asset_catalog_local_fallback_only_on_quota(monkeypatch):
    def quota():
        raise ResourceExhausted("q")

    with pytest.raises(ResourceExhausted):
        ac.AssetCatalog(quota).list_active()
    local_mode(monkeypatch)
    assets, source = ac.AssetCatalog(quota).list_active()
    assert source == "LOCAL_SEED_FALLBACK" and len(assets) == 100
    assert {a.symbol for a in assets} >= {"TUPRS", "THYAO"} and all(a.currency == "TRY" for a in assets)

    def other():
        raise RuntimeError("bağlantı")

    with pytest.raises(RuntimeError):  # yalnız kota hatası yedeğe düşer
        ac.AssetCatalog(other).list_active()
    monkeypatch.setenv("K_SERVICE", "svc")
    with pytest.raises(ResourceExhausted):
        ac.AssetCatalog(quota).list_active()


def test_fallback_is_not_cached(monkeypatch):
    local_mode(monkeypatch)
    state = {"fail": True}

    def load():
        if state["fail"]:
            raise ResourceExhausted("q")
        return list(ASSETS)

    catalog = ac.AssetCatalog(load)
    assert catalog.list_active()[1] == "LOCAL_SEED_FALLBACK"
    state["fail"] = False
    assert catalog.list_active() == (ASSETS, "FIRESTORE")


# --- API ---------------------------------------------------------------------------------------------------------

def dashboard_client(monkeypatch, catalog_load=lambda: list(ASSETS), dependencies=None):
    app = FastAPI()
    firestore_errors.register(app)
    app.include_router(decisions_api.router)
    app.include_router(assets_api.router)
    catalog = ac.AssetCatalog(catalog_load)
    monkeypatch.setattr(decisions_api, "ASSET_CATALOG", catalog)
    monkeypatch.setattr(assets_api, "ASSET_CATALOG", catalog)
    real_build = db.build_dashboard
    monkeypatch.setattr(decisions_api, "build_dashboard",
                        lambda symbols, source: real_build(symbols, source, dependencies or deps(), now=NOW))
    return TestClient(app), catalog


def test_api_dashboard_contract_and_single_symbol_route_kept(monkeypatch):
    client, _ = dashboard_client(monkeypatch)
    body = client.get("/decisions/dashboard").json()
    assert set(body) == {"generated_at", "mode", "asset_source", "reason", "items"}
    assert set(body["items"][0]) == {"asset", "status", "reason", "decision", "final_score", "confidence",
                                     "channel_completeness", "technical_score", "news_score", "macro_score",
                                     "decision_as_of", "decision_engine_version"}

    class Engine:
        def decide_for_asset(self, symbol):
            return {"asset": symbol, "decision": "HOLD"}

    monkeypatch.setattr(decisions_api, "DecisionEngine", Engine)
    assert client.get("/decisions/THYAO").json() == {"asset": "THYAO", "decision": "HOLD"}


def test_api_quota_is_503_in_production(monkeypatch):
    client, _ = dashboard_client(monkeypatch, dependencies=deps(tech=TechRepo(error=ResourceExhausted("q"))))
    r = client.get("/decisions/dashboard")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "FIRESTORE_QUOTA_EXHAUSTED"
    assert r.headers["Retry-After"] == str(firestore_errors.RETRY_AFTER_SECONDS)


def test_api_assets_header_and_quota(monkeypatch):
    client, _ = dashboard_client(monkeypatch)
    r = client.get("/assets")
    assert r.status_code == 200 and r.headers["X-Asset-Source"] == "FIRESTORE"

    def quota():
        raise ResourceExhausted("q")

    client, _ = dashboard_client(monkeypatch, catalog_load=quota)
    assert client.get("/assets").status_code == 503
    local_mode(monkeypatch)
    r = client.get("/assets")
    assert r.status_code == 200 and r.headers["X-Asset-Source"] == "LOCAL_SEED_FALLBACK" and len(r.json()) == 100


@pytest.mark.parametrize("path,method", [("/portfolio/positions", "get"), ("/portfolio/history", "get")])
def test_user_specific_endpoints_have_no_fallback_even_locally(monkeypatch, path, method):
    local_mode(monkeypatch)

    class Quota:
        def __getattr__(self, _name):
            def fail(*_a, **_k):
                raise ResourceExhausted("q")
            return fail

    monkeypatch.setattr(portfolio_api, "PortfolioRepository", Quota)
    monkeypatch.setattr(portfolio_api, "PortfolioLedgerRepository", Quota)
    monkeypatch.setattr(portfolio_api, "PortfolioTransactionRepository", Quota)
    app = FastAPI()
    firestore_errors.register(app)
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    r = getattr(TestClient(app), method)(path)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "FIRESTORE_QUOTA_EXHAUSTED"


def test_sell_quota_is_503_without_write(monkeypatch):
    local_mode(monkeypatch)

    class Ledger:
        def execute_sale(self, *_a, **_k):
            raise ResourceExhausted("q")

    monkeypatch.setattr(portfolio_api, "PortfolioLedgerRepository", Ledger)
    app = FastAPI()
    firestore_errors.register(app)
    app.include_router(portfolio_api.router)
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    r = TestClient(app).post("/portfolio/positions/AAA/sell",
                             json={"quantity": 1, "sell_price": 10.0, "position_version": "v"})
    assert r.status_code == 503


# --- final audit: önbellek anahtarı, teknik pencere, gerçek motorla eşitlik, hata eşlemesi, rota ------------------

def test_delete_plus_add_with_same_count_invalidates_news_cache():
    cache = db.NewsReadCache()
    news_repo = News({"AAA": [news("AAA", "a1", 30.0, NOW - timedelta(hours=3))]})
    db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, Raw({}), cache=cache), now=NOW)
    news_repo.by_asset["AAA"] = [news("AAA", "a2", -30.0, NOW - timedelta(hours=1))]  # sayı aynı (1)
    out = db.build_dashboard(["AAA"], "FIRESTORE", deps(news_repo, Raw({}), cache=cache), now=NOW)
    assert news_repo.list_calls["AAA"] == 2 and out["items"][0]["news_score"] == pytest.approx(-30.0)


def test_windowed_latest_matches_full_history_latest_for_cache_decision():
    """Penceredeki en yeni kayıt, tüm geçmişin en yenisiyle aynıdır (pencere içindeyse); pencere dışındaysa ikisi de
    cache isabeti üretemez. Aynı varlığın birden çok taze kaydında en yenisi; gelecek tarihli kayıt eski yolla aynı
    (en büyük created_at) seçilir."""
    from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository as Real

    def full_latest(records, asset):
        rows = sorted([r for r in records if r[1].asset == asset], key=lambda r: r[1].created_at, reverse=True)
        return (rows[0][1], rows[0][0]) if rows else (None, None)

    cutoff = NOW - timedelta(seconds=TECHNICAL_CACHE_TTL_SECONDS) - db.TECHNICAL_WINDOW_MARGIN
    rec = lambda i, asset, delta: (f"d{i}", SimpleNamespace(asset=asset, created_at=NOW + delta))  # noqa: E731
    records = [rec(1, "AAA", -timedelta(days=3)), rec(2, "AAA", -timedelta(minutes=9)), rec(3, "AAA", -timedelta(minutes=2)),
               rec(4, "BBB", -timedelta(hours=2)), rec(5, "CCC", timedelta(minutes=5)), rec(6, "CCC", -timedelta(minutes=1))]
    windowed = db.WindowedTechnicalAnalysisRepository([r for r in records if r[1].created_at >= cutoff])
    for asset in ("AAA", "CCC"):
        assert windowed.get_latest_with_id(asset) == full_latest(records, asset)
    assert windowed.get_latest_with_id("AAA")[1] == "d3" and windowed.get_latest_with_id("CCC")[1] == "d5"
    assert windowed.get_latest_with_id("BBB") == (None, None)  # tam geçmişteki en yeni de TTL dışı → isabet yok
    assert full_latest(records, "BBB")[0].created_at < cutoff
    assert hasattr(Real, "list_created_since")


def test_real_technical_engine_same_result_through_dashboard():
    """Gerçek TechnicalAnalysisEngine (cache kaçışı → hesaplama) dashboard sarmalayıcılarıyla, tekil yolla birebir."""
    from app.engines.technical.engine import DEFAULT_WEIGHTS as TECH_WEIGHTS, TechnicalAnalysisEngine
    from tests.test_breakout_notification_integration import _FakeProvider, _build_strong_bullish_df

    df = _build_strong_bullish_df()

    class TechConfig(Config):
        def get_raw(self, key):
            self.reads[key] += 1
            if key == "technical_indicator_weights":
                return dict(TECH_WEIGHTS)
            return {"decision_weights": dict(DEFAULT_WEIGHTS),
                    "decision_thresholds": dict(DEFAULT_THRESHOLDS)}.get(key)

    def factory(c, a, b):
        return TechnicalAnalysisEngine(provider=_FakeProvider(df), config_repo=c, analysis_repo=a, benchmark_cache_repo=b)

    d = deps(config=TechConfig())
    d.technical_engine_factory = factory
    (item,) = db.build_dashboard(["TEST"], "FIRESTORE", d, now=NOW)["items"]

    class NoCache:
        def get_latest_with_id(self, asset):
            return None, None

    class NoBench:
        def get(self):
            return None

        def set(self, *_a):
            pass

    single_tech = TechnicalAnalysisEngine(provider=_FakeProvider(df), config_repo=TechConfig(), analysis_repo=NoCache(),
                                          benchmark_cache_repo=NoBench())
    try:
        single = DecisionEngine(config_repo=TechConfig(), decision_repo=SimpleNamespace(add=None)).decide_for_asset(
            "TEST", technical_engine=single_tech, macro_repo=Macro(), news_repo=News({}), news_raw_repo=Raw({}),
            persist=False)
    except ValueError as exc:
        assert item["status"] == "ERROR" and item["reason"] == str(exc)
        return
    assert item["status"] == "OK"
    for key in ("final_score", "technical_score", "news_score", "macro_score", "confidence", "channel_completeness"):
        assert item[key] == pytest.approx(getattr(single, key))
    assert item["decision"] == single.decision


@pytest.mark.parametrize("exc_name", ["PermissionDenied", "Unauthenticated", "ServiceUnavailable", "InvalidArgument"])
def test_only_resource_exhausted_maps_to_503(monkeypatch, exc_name):
    from google.api_core import exceptions as gexc

    err = getattr(gexc, exc_name)("x")
    client, _ = dashboard_client(monkeypatch, dependencies=deps(tech=TechRepo(error=err)))
    client = TestClient(client.app, raise_server_exceptions=False)
    r = client.get("/decisions/dashboard")
    assert r.status_code == 500 and "FIRESTORE_QUOTA_EXHAUSTED" not in r.text


def test_dashboard_route_not_captured_by_symbol_route(monkeypatch):
    class Never:
        def __init__(self, *_a, **_k):
            raise AssertionError("/decisions/{symbol} handler'ı çağrılmamalı")

    monkeypatch.setattr(decisions_api, "DecisionEngine", Never)
    client, _ = dashboard_client(monkeypatch)
    r = client.get("/decisions/dashboard")
    assert r.status_code == 200 and "items" in r.json()
