"""Momentum ikincil kaynak altyapısı (ağsız): gizli değer sızmaz, yetenek varsayılanı UNKNOWN, rol hep
EXPERIMENTAL_SECONDARY, zaman damgası semantiği, sahte agresör yok, Yahoo deposundan ayrılık, tekrar işleme,
defter seviyeleri, haber published_at, holdout politikası, sağlayıcılar birleştirilmez."""

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.news_raw import NewsRawItem
from app.research.momentum_sources import holdout, status
from app.research.momentum_sources.common import (SECONDARY_ROLE, TS_UNVERIFIED, TS_VERIFIED, CapabilitySet,
                                                  SourceContractError, raw_hash)
from app.research.momentum_sources.matriks import field_mapping as fm
from app.research.momentum_sources.matriks import models as mx
from app.research.momentum_sources.matriks.adapter import MatriksAdapter, default_capabilities
from app.research.momentum_sources.matriks.config import MatriksConfig, MatriksConfigurationRequired
from app.research.momentum_sources.news_archive import adapters as ad
from app.research.momentum_sources.news_archive import archiver
from app.research.momentum_sources.news_archive.models import NewsArchiveItem, classify_headline, from_raw_item
from app.research.momentum_sources.storage import SecondaryStore, YAHOO_STORE
from app.research.momentum_pilot import split as sp

UTC = timezone.utc
T = datetime(2026, 11, 5, 7, 30, tzinfo=UTC)
SECRET = "s3cr3t-value-should-never-leak"


def tick(**kw):
    base = dict(provider="matriks", symbol="AKBNK", received_at=T + timedelta(milliseconds=300), price=60.1,
                quantity=100.0, raw_hash=raw_hash({"p": 60.1, "q": 100}), source_timestamp=T, trade_id="t1")
    return mx.TradeTick(**{**base, **kw})


# ------------------------------------------------------------------ gizli değerler / yapılandırma
def test_no_secrets_in_repr_status_errors_or_logs(monkeypatch, caplog):
    for k in ("PASSWORD", "API_KEY", "USERNAME"):
        monkeypatch.setenv(f"MATRIKS_{k}", SECRET)
    monkeypatch.setenv("MATRIKS_TRANSPORT", "REST")
    cfg = MatriksConfig.from_env()
    a = MatriksAdapter(cfg)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("t").info("config %s adapter %r", cfg, a)
    with pytest.raises(MatriksConfigurationRequired) as e:
        a.connect()
    blob = " ".join([str(cfg), repr(cfg), repr(a), json.dumps(a.status()), str(e.value), caplog.text])
    assert SECRET not in blob
    assert cfg.api_key.reveal() == SECRET  # değer okunabilir ama yalnız açıkça


def test_all_connection_methods_require_documentation_even_with_credentials(monkeypatch):
    monkeypatch.setenv("MATRIKS_TRANSPORT", "MQTT")
    monkeypatch.setenv("MATRIKS_API_KEY", SECRET)
    a = MatriksAdapter()
    assert not a.config.is_configured()
    for call in (a.connect, lambda: a.subscribe_trades(["AKBNK"]), lambda: a.trades("AKBNK", T, T),
                 lambda: a.snapshots("AKBNK", T, T, 5), lambda: a.bars("AKBNK", "1m", T, T),
                 lambda: a.events(T, T)):
        with pytest.raises(MatriksConfigurationRequired):
            call()


def test_capabilities_default_unknown_and_need_documentation():
    caps = default_capabilities()
    assert set(s["state"] for s in caps.as_dict().values()) == {"UNKNOWN"}
    assert {"aggressor_side", "level25", "kap", "historical_depth"} <= set(caps.names)
    with pytest.raises(SourceContractError):
        caps.declare("aggressor_side", "SUPPORTED", "")
    caps.declare("aggressor_side", "SUPPORTED", "vendor doc v1.2 §4")
    assert caps.as_dict()["aggressor_side"] == {"state": "SUPPORTED", "evidence": "vendor doc v1.2 §4"}


def test_field_mapping_all_unknown_no_guessing():
    assert set(fm.unknown_fields()) == set(fm.CANONICAL_FIELDS)
    with pytest.raises(MatriksConfigurationRequired):
        fm.resolve("aggressor_side")
    with pytest.raises(MatriksConfigurationRequired):
        fm.map_record({"anything": 1}, ("price",))


# ------------------------------------------------------------------ işlem modeli
def test_role_always_experimental_secondary():
    assert tick().source_role == SECONDARY_ROLE
    with pytest.raises(SourceContractError):
        tick(source_role="REFERENCE_PRIMARY")


def test_received_not_backdated_and_timestamp_preserved():
    with pytest.raises(SourceContractError):
        tick(received_at=T - timedelta(seconds=5))
    t = tick()
    assert t.source_timestamp == T and t.timestamp_status == TS_VERIFIED
    assert t.provider_latency == timedelta(milliseconds=300)
    with pytest.raises(SourceContractError):
        tick(source_timestamp=datetime(2026, 11, 5, 10, 30))  # saat dilimsiz


def test_missing_timestamp_stays_unverified():
    t = tick(source_timestamp=None)
    assert t.timestamp_status == TS_UNVERIFIED and t.provider_latency is None


def test_no_fake_aggressor_and_members_do_not_imply_side():
    with pytest.raises(SourceContractError):
        tick(aggressor_side="BUY")  # belgelenmiş sağlayıcı alanı olmadan
    t = tick(buyer_member="X", seller_member="Y")
    assert t.aggressor_side == "UNKNOWN"
    with pytest.raises(SourceContractError):
        mx.aggressor_from_members("X", "Y")
    ok = tick(aggressor_side="BUY", aggressor_provenance=mx.PROVIDER_FIELD)
    assert ok.aggressor_side == "BUY"


def test_identity_not_assumed():
    t = tick()
    assert t.identity_status == "UNVERIFIED" and t.currency is None and t.exchange is None
    with pytest.raises(SourceContractError):
        tick(identity_status="TRY")


def test_raw_hash_deterministic():
    p = {"b": 2, "a": [1, 2.5, None]}
    assert raw_hash(p) == raw_hash({"a": [1, 2.5, None], "b": 2}) and len(raw_hash(p)) == 64


# ------------------------------------------------------------------ emir akışı
def test_order_flow_unsupported_without_provider_aggressor():
    snap = mx.OrderFlowSnapshot.from_ticks([tick(), tick(trade_id="t2", raw_hash=raw_hash("t2"))], T, T)
    assert snap.status == "UNSUPPORTED" and all(v is None for v in snap.fields().values())
    with pytest.raises(SourceContractError):
        mx.OrderFlowSnapshot.from_ticks([], T, T)


def test_order_flow_from_real_provider_sides_only():
    ticks = [tick(trade_id="a", aggressor_side="BUY", aggressor_provenance=mx.PROVIDER_FIELD, quantity=300,
                  source_timestamp=T - timedelta(seconds=30), raw_hash=raw_hash("a")),
             tick(trade_id="b", aggressor_side="SELL", aggressor_provenance=mx.PROVIDER_FIELD, quantity=100,
                  source_timestamp=T - timedelta(minutes=4), raw_hash=raw_hash("b")),
             tick(trade_id="c", aggressor_side="BUY", aggressor_provenance=mx.PROVIDER_FIELD, quantity=50,
                  source_timestamp=T + timedelta(minutes=1), received_at=T + timedelta(minutes=1, seconds=1),
                  raw_hash=raw_hash("c"))]  # gelecekte: hesaba girmez
    s = mx.OrderFlowSnapshot.from_ticks(ticks, T, T + timedelta(seconds=1))
    assert s.status == "COMPUTED_FROM_PROVIDER_TICKS"
    assert (s.buy_volume, s.sell_volume, s.net_aggressive_volume) == (300, 100, 200)
    assert s.ofi_1m == 1.0 and s.ofi_5m == 0.5 and s.large_buy_count is None  # eşik verilmedi → None


# ------------------------------------------------------------------ emir defteri
def test_order_book_optional_levels_and_features():
    L = [mx.BookLevel(10.0, 100, 10.02, 50)]
    b1 = mx.OrderBookSnapshot("matriks", "AKBNK", T, 1, tuple(L), raw_hash("b1"), T)
    assert mx.microprice(b1) == pytest.approx((10.02 * 100 + 10.0 * 50) / 150)
    assert mx.spread_bps(b1) == pytest.approx(0.02 / 10.01 * 1e4)
    assert mx.book_imbalance(b1, 5) is None and mx.depth_slope(b1) is None  # yetersiz seviye → None
    b25 = mx.OrderBookSnapshot("matriks", "AKBNK", T, 25, tuple(L * 3), raw_hash("b25"), T)
    assert mx.book_imbalance(b25, 1) == pytest.approx(50 / 150)
    with pytest.raises(SourceContractError):
        mx.OrderBookSnapshot("matriks", "AKBNK", T, 7, tuple(L), raw_hash("x"), T)
    with pytest.raises(SourceContractError):
        mx.OrderBookSnapshot("matriks", "AKBNK", T, 1, tuple(L * 2), raw_hash("x"), T)
    empty = mx.OrderBookSnapshot("matriks", "AKBNK", T, 5, (mx.BookLevel(),), raw_hash("e"), T)
    assert mx.microprice(empty) is None and mx.spread_bps(empty) is None


# ------------------------------------------------------------------ depolama
def test_secondary_store_separate_from_yahoo(tmp_path):
    with pytest.raises(SourceContractError):
        SecondaryStore(YAHOO_STORE / "momentum_secondary")
    s = SecondaryStore(tmp_path)
    tables = {r[0] for r in s.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"trade_ticks", "order_flow", "order_book", "news_events", "source_runs", "source_failures",
            "source_metadata"} <= tables and "bars" not in tables
    with pytest.raises(sqlite3.IntegrityError):
        s.db.execute("INSERT INTO source_failures(provider, received_at, error_type, message, source_role) "
                     "VALUES ('x','t','e','m','REFERENCE_PRIMARY')")
    assert s.integrity()["ok"]
    s.close()


def test_duplicate_handling_deterministic_and_timestamps_roundtrip(tmp_path):
    s = SecondaryStore(tmp_path)
    t = tick()
    assert s.add_trade(t) == "NEW" and s.add_trade(t) == "DUPLICATE"
    changed = tick(price=61.0, raw_hash=raw_hash({"p": 61.0}))
    assert s.add_trade(changed) == "DUPLICATE_CONFLICT"
    row = s.db.execute("SELECT price, source_timestamp, received_at, timestamp_status FROM trade_ticks").fetchall()
    assert row == [(60.1, T.isoformat(), t.received_at.isoformat(), TS_VERIFIED)]  # ilk görülen korunur
    assert s.db.execute("SELECT COUNT(*) FROM source_failures WHERE error_type='DUPLICATE_CONFLICT'").fetchone()[0] == 1
    s.add_trade(tick(trade_id="t9", source_timestamp=None, raw_hash=raw_hash("t9")))
    assert s.db.execute("SELECT source_timestamp, timestamp_status FROM trade_ticks WHERE trade_id='t9'").fetchone() == \
        (None, TS_UNVERIFIED)
    with pytest.raises(sqlite3.IntegrityError):
        s.db.execute("UPDATE trade_ticks SET price=1")
    s.close()


def test_no_provider_silently_merged(tmp_path):
    s = SecondaryStore(tmp_path)
    assert s.add_trade(tick(provider="matriks")) == "NEW"
    assert s.add_trade(tick(provider="other_vendor")) == "NEW"  # aynı trade_id, farklı sağlayıcı → ayrı satır
    st = s.stats()["trade_ticks"]
    assert set(st) == {"matriks", "other_vendor"} and all(v["rows"] == 1 for v in st.values())
    s.close()


def test_unsupported_order_flow_fields_stored_as_null(tmp_path):
    s = SecondaryStore(tmp_path)
    snap = mx.OrderFlowSnapshot.from_ticks([tick()], T, T)
    s.add_order_flow(snap)
    fields = json.loads(s.db.execute("SELECT fields FROM order_flow").fetchone()[0])
    assert set(fields.values()) == {None}
    s.close()


# ------------------------------------------------------------------ haber
def raw_news(published=T, **kw):
    return NewsRawItem(external_id="foreks:abc", title="AKBNK yeni sözleşme imzaladı", summary="x",
                       url="https://example.invalid/n", publisher="Foreks", source="foreks", source_reliability=None,
                       related_assets=kw.get("assets", ["AKBNK", "GARAN"]), published_at=published,
                       received_at=T + timedelta(minutes=2))


def test_news_published_at_preserved_and_unverified_when_missing(tmp_path):
    items = from_raw_item(raw_news(), "foreks", "rss pubDate")
    assert [i.symbol for i in items] == ["AKBNK", "GARAN"] and len({i.raw_hash for i in items}) == 1
    assert all(i.published_at == T and i.received_at == T + timedelta(minutes=2) for i in items)
    assert items[0].event_type == "contract" and classify_headline("Temettü dağıtım kararı") == "dividend"
    s = SecondaryStore(tmp_path)
    for i in items:
        s.add_news(i)
    assert s.db.execute("SELECT DISTINCT published_at, source_timestamp FROM news_events").fetchall() == \
        [(T.isoformat(), T.isoformat())]
    s.close()
    no_pub = NewsArchiveItem("kap", None, "AKBNK", None, None, T, "h", "other", None, None, "c" * 64, "r" * 64, "n/a")
    assert no_pub.timestamp_status == TS_UNVERIFIED and no_pub.source_timestamp is None


def test_existing_providers_reused_without_firestore(monkeypatch):
    import app.core.firebase as fb
    monkeypatch.setattr(fb, "get_firestore_client", lambda: (_ for _ in ()).throw(AssertionError("Firestore!")))
    rss = ("<rss><channel><item><title>AKBNK bedelsiz sermaye artırımı</title>"
           "<link>https://www.foreks.com/x?haber_id=abc123</link><pubDate>Mon, 02 Nov 2026 07:00:00 GMT</pubDate>"
           "<description>AKBNK</description></item></channel></rss>").encode()
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(content=rss, raise_for_status=lambda: None))
    items = ad.ForeksArchiveAdapter(["AKBNK", "GARAN"]).fetch()
    assert [(i.symbol, i.event_type) for i in items] == [("AKBNK", "capital_increase")]
    assert items[0].published_at == datetime(2026, 11, 2, 7, 0, tzinfo=UTC)  # orijinal yayın zamanı korunur
    assert items[0].received_at >= items[0].published_at
    assert items[0].timestamp_status == "PUBLISHED_AT_FROM_SOURCE"


def test_news_published_after_received_is_flagged_not_rewritten():
    item = from_raw_item(raw_news(published=T + timedelta(hours=1), assets=["AKBNK"]), "foreks", "rss")[0]
    assert item.published_at == T + timedelta(hours=1)  # değiştirilmez
    assert item.timestamp_status == "PUBLISHED_AFTER_RECEIVED_CLOCK_SKEW"


# ------------------------------------------------------------------ holdout
def test_holdout_outcome_forbidden_but_raw_collection_allowed(tmp_path):
    with pytest.raises(sp.HoldoutAccessError):
        holdout.assert_outcome_analysis_allowed(["2026-11-02"], "labels")
    with pytest.raises(sp.HoldoutAccessError):
        holdout.assert_outcome_analysis_allowed([date(2026, 11, 5)], "alerts")
    holdout.assert_outcome_analysis_allowed(["2026-10-30"], "labels")
    assert holdout.raw_collection_allowed(date(2026, 11, 5))

    class OneItem:
        provider, requests_per_run = "foreks", 1

        def fetch(self):
            return from_raw_item(raw_news(published=T, assets=["AKBNK"]), "foreks", "rss pubDate")
    store = SecondaryStore(tmp_path)
    res = archiver.run([OneItem(), ad.KapArchiveAdapter()], store, now_fn=lambda: T + timedelta(minutes=3))
    assert res["foreks"]["items_inserted"] == 1 and res["kap"]["status"] == "FAILED"
    assert "KAP_SOURCE_NOT_CONFIGURED" in res["kap"]["error"]
    store.close()


def test_status_reports_collection_health_only(tmp_path):
    rep = status.report(tmp_path)
    assert rep["storage"]["status"] == "NO_STORE_YET" and not (tmp_path / "secondary.sqlite").exists()
    s = SecondaryStore(tmp_path)
    s.add_trade(tick())
    s.close()
    rep = status.report(tmp_path)
    text = json.dumps(rep).lower()
    assert rep["storage"]["integrity"]["ok"] and rep["providers"]["kap"]["status"] == "KAP_SOURCE_NOT_CONFIGURED"
    keys = json.dumps(list(_keys(rep))).lower()
    assert not any(k in keys for k in status.FORBIDDEN_KEYS)
    assert "not active" in text


def _keys(d):
    if isinstance(d, dict):
        for k, v in d.items():
            yield k
            yield from _keys(v)
    elif isinstance(d, list):
        for v in d:
            yield from _keys(v)


def test_capability_set_rejects_unknown_names():
    with pytest.raises(SourceContractError):
        CapabilitySet(("a",)).declare("b", "SUPPORTED", "doc")
