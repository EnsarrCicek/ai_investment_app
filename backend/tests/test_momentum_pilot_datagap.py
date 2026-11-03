"""Momentum veri açığı analizi ve gelecekteki kaynak sözleşmeleri (yalnız araştırma): holdout ve tüketilmiş final
yasak, gecikme karşı-olgusu kuralları yeniden ayarlamaz, kaynak zaman damgaları korunur, sahte veri ve sağlayıcı
birleştirme yok, veri açığı manifest SHA'sı deterministik."""

import inspect
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_pilot import datagap as dg
from app.research.momentum_pilot import redesign as rd
from app.research.momentum_pilot import sources as src
from app.research.momentum_pilot import split as sp

UTC = timezone.utc
T = datetime(2026, 10, 22, 7, 30, tzinfo=UTC)
H = "a" * 64


def meta(**kw):
    base = dict(provider="example", symbol="AKBNK", exchange=None, currency=None, source_timestamp=T,
                received_at=T + timedelta(seconds=40), identity_status="UNVERIFIED", raw_hash=H)
    return src.SourceMeta(**{**base, **kw})


def test_holdout_forbidden_and_audit():
    assert set(rd.holdout_audit("t")["checks"].values()) == {"FORBIDDEN"}
    with pytest.raises(sp.HoldoutAccessError):
        sp.HoldoutGuard(sp.load_manifest()).check_session("2026-11-02")


def test_consumed_final_forbidden(monkeypatch):
    from app.research.momentum_round2 import dataset as ds2
    monkeypatch.setattr(ds2, "selection_and_final", lambda: ([date(2026, 10, 1)], [date(2026, 9, 28)]))
    with pytest.raises(rd.DataPolicyError):
        rd.load_historical(["AKBNK"])


def test_source_timestamp_preserved_and_no_currency_assumption():
    m = meta()
    assert m.source_timestamp == T and m.provider_latency == timedelta(seconds=40)
    assert m.currency is None and m.exchange is None and m.source_role == src.EXPERIMENTAL_SECONDARY


def test_received_cannot_predate_source_when_required():
    with pytest.raises(src.SourceContractError):
        meta(received_at=T - timedelta(minutes=1))
    ok = meta(received_at=T - timedelta(minutes=1), received_must_follow_source=False)  # açık istisna (haber saati)
    assert ok.provider_latency < timedelta(0)
    with pytest.raises(src.SourceContractError):
        meta(source_timestamp=datetime(2026, 10, 22, 10, 30))  # saat dilimsiz


def test_news_uses_original_published_at():
    m = meta(source_timestamp=T)
    ev = src.NewsEvent(m, "kap", T, "AKBANK", "contract", None, "x")
    assert ev.published_at == ev.meta.source_timestamp
    with pytest.raises(src.SourceContractError):
        src.NewsEvent(m, "kap", T + timedelta(minutes=5), "AKBANK", "contract", None, "scraped later")
    with pytest.raises(src.SourceContractError):
        src.NewsEvent(m, "kap", T, "AKBANK", "rumour", None, "x")


def test_no_fake_order_flow_and_no_provider_merge():
    with pytest.raises(src.SourceContractError):
        src.require_real_records([])
    with pytest.raises(src.SourceContractError):
        meta(provider="synthetic")
    a = src.Trade(meta(provider="p1"), 10.0, 100.0, None)
    b = src.Trade(meta(provider="p2"), 10.0, 100.0, "BUY")
    with pytest.raises(src.SourceContractError):
        src.assert_single_provider([a, b])
    sep = src.keep_separate([a], [b])
    assert set(sep) == {"p1|EXPERIMENTAL_SECONDARY", "p2|EXPERIMENTAL_SECONDARY"}
    for cls in (src.IntradayPriceSource, src.OrderFlowSource, src.OrderBookSource, src.NewsEventSource):
        with pytest.raises(TypeError):
            cls()  # yalnız sözleşme; uygulama yok


def test_feature_specs_are_definitions_only():
    s = src.spec()
    assert {"ofi_1m", "ofi_3m", "ofi_5m", "ofi_15m", "order_flow_imbalance"} <= set(s["order_flow_features"])
    assert {"book_imbalance_L1", "book_imbalance_L5", "microprice", "spread_bps"} <= set(s["order_book_features"])
    assert "published_at" in s["news_event_schema"] and "credit_rating" in s["news_event_classes"]


def _grid():
    days = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")
    rng = np.random.default_rng(1)
    frames, p = [], 100.0
    for d in days:
        idx = pd.date_range(f"{d} 09:55", f"{d} 17:55", freq="5min", tz=ISTANBUL_TZ)
        c = p * np.exp(np.cumsum(rng.normal(0, 0.004, len(idx))))
        o = np.concatenate([[p], c[:-1]])
        frames.append(pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.003, "Low": np.minimum(o, c) * 0.997,
                                    "Close": c, "Volume": 1000.0}, index=idx))
        p = c[-1]
    bars = pd.concat(frames)
    f = rd.asset_features(bars, bars)
    f["symbol"] = "AAA"
    panel = rd.add_cross_section(f)
    return rd.Grid(panel, [date(2026, 8, 6)], rd.estimated_visibility(15 * rd.MIN_NS), "T")


def test_counterfactual_only_changes_visibility():
    g = _grid()
    mask = np.zeros(len(g.rows), dtype=bool)
    mask[10] = True
    g0 = dg.delayed_grid(g, 0)
    np.testing.assert_array_equal(g0.info, g.info)
    assert (g0.visible == g.info).all() and (g.visible == g.info + 15 * rd.MIN_NS).all()
    assert g0.evaluate(mask)["alerts"] == g.evaluate(mask)["alerts"] == 1
    src_cf = inspect.getsource(dg.latency_counterfactual)
    assert "choose_threshold" not in src_cf and "fit_" not in src_cf  # karşı-olguda yeniden ayar yok
    assert 'dp.GRID["A0_round1_watch"]' in src_cf and 'dp.GRID["A5d_weak_volume+relative"]' in src_cf


def test_data_gap_manifest_deterministic(tmp_path):
    lat = {"1m": {"median": 18.1}, "5m": {"median": 15.6}}
    a = dg.manifest_body("p" * 64, lat, {"x.json": H}, "2026-11-03T00:00:00+00:00")
    b = dg.manifest_body("p" * 64, lat, {"x.json": H}, "2026-11-03T00:00:00+00:00")
    assert a == b and sp.cd.sha256_of(a) == sp.cd.sha256_of(b)
    assert a["conclusion"] == "OHLCV_ONLY_NOT_SUFFICIENT_FOR_CURRENT_TARGET" and a["label_v2_sha256"] == sp.LABEL_V2_SHA256
    path = tmp_path / "m.json"
    d1 = dg.freeze_manifest(a, path)
    assert dg.freeze_manifest({**b, "created_at": "later"}, path) == d1  # aynı anlam: dosya değişmez
    with pytest.raises(dg.DataGapManifestError):
        dg.freeze_manifest({**a, "conclusion": "OTHER"}, path)


def test_repository_data_gap_manifest_valid():
    import json
    doc = json.loads(dg.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert sp.cd.sha256_of(doc["manifest"]) == doc["sha256"]
    assert doc["manifest"]["pilot_manifest_sha256"] == sp.load_manifest()["sha256"]


def test_taxonomy_rules_deterministic():
    base = {"symbol": "A", "session": "2026-10-22", "rise_min": 60}
    assert dg.classify_event({**base, "class": rd.BOTTLENECK[1]}, False, False) == dg.TAXONOMY[0]
    assert dg.classify_event({**base, "class": rd.BOTTLENECK[3]}, False, False) == dg.TAXONOMY[5]
    early = {**base, "class": rd.BOTTLENECK[0], "first_price_evidence_minus_T0_min": 20,
             "first_volume_anomaly_minus_T0_min": 5}
    assert dg.classify_event(early, False, False) == dg.TAXONOMY[3]
    assert dg.classify_event({**early, "first_volume_anomaly_minus_T0_min": 30}, False, False) == dg.TAXONOMY[1]
    late = {**base, "class": rd.BOTTLENECK[2], "first_breakout_minus_T0_min": 70}
    assert dg.classify_event(late, False, False) == dg.TAXONOMY[2]
    assert dg.classify_event(early, False, True) == dg.TAXONOMY[3]  # arşiv yokken haber sınıfı verilmez
    assert dg.classify_event(early, True, True) == dg.TAXONOMY[4]
