"""Momentum API + tarayıcı — sahte sağlayıcı, gerçek ağ/Firestore yok."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import momentum as momentum_api
from app.models import momentum_alert as ma
from app.models.asset import Asset
from app.services.assets import asset_catalog as ac
from app.services.market_data.bist_provenance_provider import ProviderIdentityError
from app.services.momentum import scanner
from app.services.momentum.intraday_provider import CachedIntradayProvider, IntradayBars
from tests.test_momentum_engine import DAY, DELAY, FLAT, PROV, STEP, build

STRONG_BARS = build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4)
FLAT_BARS = build(FLAT + [0.0002, -0.0001, 0.0001, 0.0])  # güçlü seriyle aynı uzunluk (aynı "şimdi"de taze)
NOW = STRONG_BARS[STRONG_BARS.index.date == DAY].index[-1].to_pydatetime() + STEP + DELAY


class FakeProvider:
    def __init__(self, plan=lambda s: "strong"):
        self.plan, self.release = plan, threading.Event()
        self.lock, self.running, self.peak, self.calls = threading.Lock(), 0, 0, []

    def get_intraday(self, symbol, interval="5m", period=None, start=None, end=None):
        with self.lock:
            self.calls.append(symbol)
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            kind = self.plan(symbol)
            if kind == "hang":
                self.release.wait(timeout=10)
            if kind == "error":
                raise ValueError("gün içi veri bulunamadı")
            if kind == "identity":
                raise ProviderIdentityError("kimlik uyuşmuyor")
            if kind == "boom":
                raise RuntimeError("bağlantı koptu")
            bars = STRONG_BARS if kind == "strong" else FLAT_BARS
            return IntradayBars(symbol, interval, bars, dict(PROV))
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture(autouse=True)
def no_firestore(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("momentum Firestore'a erişmemeli (bu testlerde)")
    monkeypatch.setattr("app.core.firebase.get_firestore_client", forbidden)
    monkeypatch.setattr(scanner, "load_events", lambda symbols, timeout: None)
    monkeypatch.setattr(scanner, "now_utc", lambda: NOW)


@pytest.fixture
def pool():
    pools = []

    def make(workers=scanner.MOMENTUM_MAX_WORKERS):
        p = ThreadPoolExecutor(max_workers=workers)
        pools.append(p)
        return p
    yield make
    for p in pools:
        p.shutdown(wait=True)


def client(monkeypatch, provider, symbols=("KTLEV",)):
    monkeypatch.setattr(scanner, "PROVIDER", provider)
    catalog = ac.AssetCatalog(lambda: [Asset(symbol=s, name=s, market="BIST", asset_type="STOCK", currency="TRY")
                                       for s in symbols])
    monkeypatch.setattr(momentum_api, "ASSET_CATALOG", catalog)
    app = FastAPI()
    app.include_router(momentum_api.router)
    return TestClient(app)


# --- tek sembol ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("plan,status", [("strong", ma.STATUS_OK), ("error", ma.STATUS_ERROR),
                                         ("identity", ma.STATUS_IDENTITY_UNVERIFIED), ("boom", ma.STATUS_ERROR)])
def test_single_symbol_statuses(monkeypatch, plan, status):
    body = client(monkeypatch, FakeProvider(lambda s: plan)).get("/momentum/ktlev").json()
    assert body["asset"] == "KTLEV" and body["status"] == status
    assert body["disclaimer"] == ma.DISCLAIMER
    if status == ma.STATUS_OK:
        assert body["level"] == ma.LEVEL_STRONG and body["detected"] is True
    else:
        assert body["momentum_score"] is None and body["detected"] is False


def test_single_symbol_stale(monkeypatch):
    monkeypatch.setattr(scanner, "now_utc", lambda: NOW + timedelta(minutes=45))
    body = client(monkeypatch, FakeProvider()).get("/momentum/KTLEV").json()
    assert body["status"] == ma.STATUS_STALE_DATA and body["momentum_score"] is None


def test_scan_route_not_captured_by_symbol_route(monkeypatch):
    provider = FakeProvider()
    r = client(monkeypatch, provider, symbols=("AAA",)).get("/momentum/scan")
    assert r.status_code == 200 and "alerts" in r.json() and "SCAN" not in provider.calls


# --- tarayıcı ----------------------------------------------------------------------------------------------------

SYMBOLS = [f"S{i:03d}" for i in range(100)]


def test_scan_100_symbols_valid_with_errors_and_cap(pool):
    provider = FakeProvider(lambda s: "error" if s == "S007" else ("strong" if int(s[1:]) % 10 == 0 else "flat"))
    out = scanner.scan(SYMBOLS, now=NOW, provider=provider, events_loader=lambda s, t: None, executor=pool(),
                       include_all=True)
    assert out["scanned_count"] == 100 and len(out["items"]) == 100
    assert out["strong_count"] == 10 and out["unavailable_count"] == 1
    assert {a["level"] for a in out["alerts"]} == {ma.LEVEL_STRONG} and len(out["alerts"]) == 10
    assert provider.peak <= scanner.MOMENTUM_MAX_WORKERS
    assert out["catalyst_context"] == "UNAVAILABLE" and out["disclaimer"] == ma.DISCLAIMER


def test_scan_several_hung_symbols_bounded_and_fail_visible(pool):
    provider = FakeProvider(lambda s: "hang" if s in ("S001", "S002") else "flat")
    started = time.monotonic()
    out = scanner.scan(SYMBOLS, now=NOW, provider=provider, events_loader=lambda s, t: None, executor=pool(8),
                       include_all=True, budget_seconds=1.0)
    assert time.monotonic() - started < 3
    by = {i["asset"]: i for i in out["items"]}
    assert by["S001"]["reason"] == scanner.SCAN_DEADLINE_EXCEEDED and by["S001"]["momentum_score"] is None
    assert out["deadline_exceeded_count"] >= 2 and out["scanned_count"] == 100
    provider.release.set()


def test_scan_all_hung_never_exceeds_cap_and_pending_cancelled(pool):
    provider = FakeProvider(lambda s: "hang")
    shared = pool()
    for _ in range(2):  # üst üste iki tarama
        out = scanner.scan(SYMBOLS, now=NOW, provider=provider, events_loader=lambda s, t: None, executor=shared,
                           budget_seconds=0.2)
        assert out["deadline_exceeded_count"] == 100
    assert provider.peak <= scanner.MOMENTUM_MAX_WORKERS
    provider.release.set()
    shared.shutdown(wait=True)
    assert len(provider.calls) == scanner.MOMENTUM_MAX_WORKERS  # iptal edilenler hiç başlamadı


def test_process_executor_cap():
    assert scanner.momentum_executor() is scanner.momentum_executor()
    assert scanner.momentum_executor()._max_workers == scanner.MOMENTUM_MAX_WORKERS == 4


def test_scan_events_passed_only_to_matching_symbol(pool):
    from app.services.momentum.early_momentum_engine import CatalystEvent

    seen = {}

    def provider_eval(symbol, now, provider, events):
        seen[symbol] = events
        return ma.MomentumAlert(asset=symbol, status=ma.STATUS_OK, evaluated_at=now, level=ma.LEVEL_NONE)

    ev = CatalystEvent(NOW, NOW, 50.0, 0.9)
    orig = scanner.evaluate_symbol
    scanner.evaluate_symbol = provider_eval
    try:
        scanner.scan(["AAA", "BBB"], now=NOW, events_loader=lambda s, t: {"AAA": [ev], "BBB": []}, executor=pool())
    finally:
        scanner.evaluate_symbol = orig
    assert seen == {"AAA": [ev], "BBB": []}


# --- önbellek ----------------------------------------------------------------------------------------------------

def test_intraday_cache_ttl_key_and_single_flight():
    clock = [0.0]
    inner = FakeProvider(lambda s: "flat")
    cache = CachedIntradayProvider(inner, ttl_seconds=60, clock=lambda: clock[0])
    cache.get_intraday("AAA", "5m", period="15d")
    cache.get_intraday("AAA", "5m", period="15d")
    cache.get_intraday("AAA", "1m", period="15d")  # farklı sözleşme → ayrı anahtar
    assert inner.calls == ["AAA", "AAA"]
    clock[0] = 61.0  # süresi dolan kayıt sunulmaz
    cache.get_intraday("AAA", "5m", period="15d")
    assert inner.calls == ["AAA", "AAA", "AAA"]

    slow = FakeProvider(lambda s: "hang")
    cache2 = CachedIntradayProvider(slow, ttl_seconds=60)
    threads = [threading.Thread(target=lambda: cache2.get_intraday("BBB", "5m", period="15d")) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    slow.release.set()
    for t in threads:
        t.join(timeout=5)
    assert slow.calls == ["BBB"]


def test_catalyst_events_skip_unresolved_raw_and_use_later_availability():
    from datetime import datetime, timezone

    from app.models.news_analysis import NewsAnalysis
    from app.models.news_raw import NewsRawItem

    t0 = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    a = NewsAnalysis(news_id="n1", asset="X", sentiment_score=60, confidence=0.8, importance=0.5, event_type="other",
                     reasoning="r", model_used="m", created_at=t0 + timedelta(hours=2))
    b = a.model_copy(update={"news_id": "missing"})
    raw = NewsRawItem(external_id="n1", title="t", summary="s", url="https://e.com", publisher="p",
                      source="google_news_rss", source_reliability=0.7, related_assets=["X"], published_at=t0,
                      received_at=t0 + timedelta(minutes=30))
    (event,) = scanner.catalyst_events([a, b], {"n1": raw, "missing": None})
    assert event.published_at == t0 and event.available_at == t0 + timedelta(hours=2) and event.reliability == 0.7
