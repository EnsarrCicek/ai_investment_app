"""HATA 15C — source_reliability'nin DecisionEngine haber skoruna etkisi.

Kapsam: app/engines/decision/engine.py::_effective_news_weight /
_aggregate_news_score / _deduplicate_news_analyses (HATA 15B'nin kümeleme/
temsilci seçimi katmanı DEĞİŞMEDİ -- bu dosya yalnızca reliability
ağırlıklandırmasını kilitler).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.decision.engine import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    DecisionEngine,
    _aggregate_news_score,
    _deduplicate_news_analyses,
    _WeightedNewsAnalysis,
)
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem

T0 = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def _news(external_id, title, reliability, published_at=T0, asset="THYAO", summary="özet metni"):
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary=summary,
        url=f"https://example.com/{external_id}",
        publisher="Test",
        source="test",
        source_reliability=reliability,
        related_assets=[asset],
        published_at=published_at,
        received_at=published_at,
    )


def _analysis(news_id, asset="THYAO", sentiment_score=0.0, confidence=1.0, created_at=None):
    return NewsAnalysis(
        news_id=news_id,
        asset=asset,
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=0.5,
        event_type="other",
        reasoning="r",
        model_used="gpt-5.6-luna",
        created_at=created_at or T0,
    )


def _weighted(sentiment_score, confidence, source_reliability, news_id="n"):
    return _WeightedNewsAnalysis(
        analysis=_analysis(news_id, sentiment_score=sentiment_score, confidence=confidence),
        source_reliability=source_reliability,
    )


class _FakeNewsRawRepoWithData:
    def __init__(self, raw_by_id):
        self._raw_by_id = raw_by_id

    def get_by_external_id(self, external_id):
        return self._raw_by_id.get(external_id)


class _FakeConfigRepo:
    def get_raw(self, key):
        if key == "decision_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


class _FakeDecisionRepo:
    def add(self, decision):
        raise AssertionError("persist=False iken add() çağrılmamalı")


class _FakeTechnicalEngine:
    def analyze_with_id(self, symbol, persist=True):
        from types import SimpleNamespace

        return SimpleNamespace(technical_score=None, confidence=None), "tech-id"


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeNewsRepoUnbounded:
    def __init__(self, analyses):
        self._analyses = sorted(analyses, key=lambda a: a.created_at, reverse=True)

    def list_for_asset(self, asset, limit=None):
        return list(self._analyses)


# ---------------------------------------------------------------------------
# Bölüm 17 — sayısal reliability etkisi (ticket'ın kendi örneği).
# ---------------------------------------------------------------------------


def test_reliability_changes_score_exact_numeric_example():
    weighted = [_weighted(100.0, 1.0, 1.0, "a"), _weighted(-100.0, 1.0, 0.5, "b")]
    # (100*1*1.0 + -100*1*0.5) / (1.0+0.5) = 50/1.5 = 33.333... -> round(...,2) = 33.33
    assert _aggregate_news_score(weighted) == pytest.approx(33.33)


# ---------------------------------------------------------------------------
# Bölüm 18 — eşit reliability kontrolü: eski confidence-only formülle AYNI.
# ---------------------------------------------------------------------------


def test_equal_reliability_matches_confidence_only_formula():
    weighted_equal = [_weighted(100.0, 0.9, 0.7, "a"), _weighted(-100.0, 0.1, 0.7, "b")]
    old_style = [_weighted(100.0, 0.9, None, "a"), _weighted(-100.0, 0.1, None, "b")]
    assert _aggregate_news_score(weighted_equal) == pytest.approx(_aggregate_news_score(old_style))
    assert _aggregate_news_score(weighted_equal) == pytest.approx(80.0)  # 100*.9 + -100*.1


# ---------------------------------------------------------------------------
# Bölüm 19 — confidence hâlâ önemli: reliability confidence'ı YERİNE
# GEÇMİYOR, ÇARPIYOR.
# ---------------------------------------------------------------------------


def test_confidence_still_multiplies_not_replaced_by_reliability():
    weighted = [_weighted(100.0, 1.0, 0.5, "a"), _weighted(-100.0, 0.0, 0.5, "b")]
    # b'nin confidence'ı 0 -- reliability'si ne olursa olsun tamamen ağırlıksız.
    assert _aggregate_news_score(weighted) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Bölüm 20 — sıfır reliability.
# ---------------------------------------------------------------------------


def test_zero_reliability_contributes_zero_weight():
    weighted = [_weighted(100.0, 1.0, 0.0, "a"), _weighted(-40.0, 1.0, 1.0, "b")]
    assert _aggregate_news_score(weighted) == pytest.approx(-40.0)


def test_all_zero_effective_weight_returns_none_not_fabricated_zero():
    weighted = [_weighted(100.0, 1.0, 0.0, "a"), _weighted(-100.0, 1.0, 0.0, "b")]
    assert _aggregate_news_score(weighted) is None


# ---------------------------------------------------------------------------
# Bölüm 21 — geçersiz reliability -- fail-fast, sessiz clamp YOK.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [-0.1, 1.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_reliability_value_fails_fast(bad_value):
    weighted = [_weighted(50.0, 1.0, bad_value, "a")]
    with pytest.raises(ValueError):
        _aggregate_news_score(weighted)


# ---------------------------------------------------------------------------
# Bölüm 22 — bilinmeyen/eksik kaynak: fabrike OTHER_MEDIA=0.60 DEĞİL, None.
# ---------------------------------------------------------------------------


def test_missing_raw_record_yields_none_reliability_not_fabricated_other_media_default():
    raw_repo = _FakeNewsRawRepoWithData({})  # ham kayıt yok (provenance eksik)
    analyses = [_analysis("old:1", sentiment_score=50.0, confidence=1.0, created_at=T0)]

    deduped = _deduplicate_news_analyses(analyses, raw_repo)

    assert len(deduped) == 1
    assert deduped[0].source_reliability is None
    # DEFAULT_SOURCE_RELIABILITY["OTHER_MEDIA"] == 0.60 -- fabrike DEĞİL, None.
    assert deduped[0].source_reliability != 0.60


# ---------------------------------------------------------------------------
# Bölüm 23 — bilinen OTHER_MEDIA kategorisi GERÇEK configured bilgidir,
# ağırlıklandırmayı ETKİLEMELİDİR (eksik provenance'la KARIŞTIRILMAZ).
# ---------------------------------------------------------------------------


def test_known_other_media_category_reliability_does_affect_weighting():
    raw_other = _news("blog:1", "Bağımsız olay X", reliability=0.60, published_at=T0)
    raw_kap = _news("kap:1", "Bağımsız olay Y", reliability=1.00, published_at=T0 + timedelta(hours=5))
    analyses = [
        _analysis("blog:1", sentiment_score=100.0, confidence=1.0, created_at=T0),
        _analysis("kap:1", sentiment_score=-100.0, confidence=1.0, created_at=T0 + timedelta(hours=5)),
    ]
    raw_repo = _FakeNewsRawRepoWithData({"blog:1": raw_other, "kap:1": raw_kap})

    deduped = _deduplicate_news_analyses(analyses, raw_repo)
    score = _aggregate_news_score(deduped)

    assert len(deduped) == 2  # farklı olaylar -- kümelenmiyor
    # (100*1*0.60 + -100*1*1.00) / (0.60+1.00) = (60-100)/1.6 = -25.0
    assert score == pytest.approx(-25.0)


# ---------------------------------------------------------------------------
# Bölüm 24 — config değişikliği hassasiyeti (hardcoded kopya DEĞİL).
# ---------------------------------------------------------------------------


def test_config_change_sensitivity_different_reliability_changes_score():
    raw_a = _news("a:1", "Bağımsız olay Alfa", reliability=0.8, published_at=T0)
    analyses = [
        _analysis("a:1", sentiment_score=100.0, confidence=1.0, created_at=T0),
        _analysis("b:1", sentiment_score=-100.0, confidence=1.0, created_at=T0 + timedelta(hours=1)),
    ]

    raw_b_high = _news("b:1", "Bağımsız olay Beta", reliability=0.9, published_at=T0 + timedelta(hours=1))
    raw_repo_high = _FakeNewsRawRepoWithData({"a:1": raw_a, "b:1": raw_b_high})
    score_high = _aggregate_news_score(_deduplicate_news_analyses(analyses, raw_repo_high))

    raw_b_low = _news("b:1", "Bağımsız olay Beta", reliability=0.1, published_at=T0 + timedelta(hours=1))
    raw_repo_low = _FakeNewsRawRepoWithData({"a:1": raw_a, "b:1": raw_b_low})
    score_low = _aggregate_news_score(_deduplicate_news_analyses(analyses, raw_repo_low))

    assert score_high != score_low


# ---------------------------------------------------------------------------
# Bölüm 15/25 — aynı mantıksal olay birden çok sağlayıcıdan, HER BİRİNİN
# reliability'si FARKLI -- yalnızca temsilcininki kullanılmalı, TOPLANMAMALI.
# ---------------------------------------------------------------------------


def test_duplicate_event_multiple_reliabilities_uses_only_representative_no_amplification():
    t = T0
    raw_a1 = _news("yahoo:x", "THY rekor kâr açıkladı", reliability=0.3, published_at=t)
    raw_a2 = _news("google:x", "THY rekor kâr açıkladı", reliability=0.9, published_at=t + timedelta(hours=1))
    raw_a3 = _news("foreks:x", "THY rekor kâr açıkladı", reliability=1.0, published_at=t + timedelta(hours=2))
    raw_b = _news("yahoo:y", "Bağımsız olay Gamma", reliability=0.5, published_at=t + timedelta(hours=3))

    analyses = [
        _analysis("yahoo:x", sentiment_score=90.0, confidence=1.0, created_at=t),
        _analysis("google:x", sentiment_score=90.0, confidence=1.0, created_at=t + timedelta(hours=1)),
        _analysis("foreks:x", sentiment_score=90.0, confidence=1.0, created_at=t + timedelta(hours=2)),
        _analysis("yahoo:y", sentiment_score=-90.0, confidence=1.0, created_at=t + timedelta(hours=3)),
    ]
    raw_repo = _FakeNewsRawRepoWithData(
        {"yahoo:x": raw_a1, "google:x": raw_a2, "foreks:x": raw_a3, "yahoo:y": raw_b}
    )

    deduped = _deduplicate_news_analyses(analyses, raw_repo)
    assert len(deduped) == 2

    rep = next(w for w in deduped if w.analysis.news_id == "yahoo:x")
    assert rep.source_reliability == pytest.approx(0.3)  # temsilci: en eski (t) -- 0.9/1.0 DEĞİL

    score = _aggregate_news_score(deduped)
    # (90*1*0.3 + -90*1*0.5) / (0.3+0.5) = (27-45)/0.8 = -22.5
    assert score == pytest.approx(-22.5)


# ---------------------------------------------------------------------------
# Bölüm 26 — son-10-BENZERSİZ-olay penceresi (HATA 15B FINAL) reliability
# ağırlıklandırması altında da bozulmuyor.
# ---------------------------------------------------------------------------


def test_unique_ten_event_window_holds_under_reliability_weighting():
    t = T0 + timedelta(hours=50)
    raw_a1 = _news("yahoo:U1", "THY rekor kâr açıkladı", reliability=0.2, published_at=t)
    raw_a2 = _news("google:U2", "THY rekor kâr açıkladı", reliability=0.9, published_at=t - timedelta(hours=1))
    raw_a3 = _news("foreks:U3", "THY rekor kâr açıkladı", reliability=1.0, published_at=t - timedelta(hours=2))
    analyses = [
        _analysis("yahoo:U1", sentiment_score=0.0, confidence=1.0, created_at=t),
        _analysis("google:U2", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=1)),
        _analysis("foreks:U3", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=2)),
    ]
    raws = {"yahoo:U1": raw_a1, "google:U2": raw_a2, "foreks:U3": raw_a3}
    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=3 + i)
        raw = _news(f"prov:{label}", f"Bağımsız olay numara {label}", reliability=0.5, published_at=created_at)
        analysis = _analysis(f"prov:{label}", sentiment_score=10.0 * (i + 1), confidence=1.0, created_at=created_at)
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    raw_repo = _FakeNewsRawRepoWithData(raws)
    news_repo = _FakeNewsRepoUnbounded(analyses)
    engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())

    decision = engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )

    assert len(decision.news_analysis_ids) == 10  # A temsilcisi + B..J -- pencere bozulmadı
    assert "prov:I" in decision.news_analysis_ids
    assert "prov:J" in decision.news_analysis_ids
    # Temsilci: en eski = foreks:U3 (t-2h), reliability=1.0, sentiment=0.0.
    # weight_A=1.0*1.0=1.0; weight_B..J = 9 * (1.0*0.5) = 4.5; toplam=5.5
    # weighted_sum = 0*1.0 + (10+20+...+90)*0.5 = 225
    # score = round(225/5.5, 2) = 40.91
    assert decision.news_score == pytest.approx(40.91)
