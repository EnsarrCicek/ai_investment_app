"""HATA 15E — ExplanationEngine / DecisionEngine haber penceresi tutarlılığı.

Kapsam: app/services/news/news_selection.py (paylaşımlı seçim yardımcısı) +
DecisionEngine.decide_for_asset ve ExplanationEngine.explain'in AYNI son-10-
benzersiz-olay üyeliğini/temsilcisini kullandığının kilidi (bkz. HATA 15A
bulgu #2'nin ExplanationEngine tarafındaki disclosed uzantısı, HATA 15C
FINAL raporu).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.models.technical_analysis import TechnicalAnalysis
from app.services.news.news_selection import NEWS_SCORE_LIMIT

T0 = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


def _raw(external_id, title, published_at=T0, summary="özet", asset="THYAO", reliability=0.8):
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


def _independent(label, created_at, score, asset="THYAO"):
    raw = _raw(f"prov:{label}", f"Bağımsız olay numara {label}", published_at=created_at, asset=asset)
    analysis = _analysis(f"prov:{label}", asset=asset, sentiment_score=score, confidence=1.0, created_at=created_at)
    return raw, analysis


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
        return (
            TechnicalAnalysis(
                asset=symbol,
                technical_score=50.0,
                trend="up",
                confidence=0.9,
                components={},
                indicators={},
                created_at=T0,
            ),
            "tech-id",
        )


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeNewsAnalysisRepo:
    """Gerçek `NewsAnalysisRepository.list_for_asset` davranışını taklit
    eder: created_at azalan sıralı TÜM kayıtları döner. `limit` her ZAMAN
    `None` ile çağrılmalı -- dedup TÜM geçmiş üzerinde yapılmalı (bkz.
    HATA 15B FINAL) -- aksi halde AssertionError fırlatır."""

    def __init__(self, analyses):
        self._analyses = sorted(analyses, key=lambda a: a.created_at, reverse=True)

    def list_for_asset(self, asset, limit=20):
        if limit is not None:
            raise AssertionError(
                f"list_for_asset() limit=None ile çağrılmalı, erken limit uygulanmış: {limit!r}"
            )
        # Gerçek NewsAnalysisRepository.list_for_asset() de Firestore
        # sorgusunda `where(asset==...)` filtrelemesi yapar (bkz.
        # news_analysis_repository.py) -- fake bunu taklit etmeli.
        return [a for a in self._analyses if a.asset == asset]


class _FakeNewsRawRepo:
    def __init__(self, raw_by_id):
        self._raw_by_id = raw_by_id

    def get_by_external_id(self, external_id):
        return self._raw_by_id.get(external_id)


def _build_engines(analyses, raws):
    """Aynı fixture verisiyle beslenen, tamamen BAĞIMSIZ DecisionEngine ve
    ExplanationEngine örnekleri -- ikisinin de select_recent_unique_news_
    analyses()'a AYNI şekilde ulaşıp ulaşmadığını kanıtlamak için."""
    news_repo = _FakeNewsAnalysisRepo(analyses)
    raw_repo = _FakeNewsRawRepo(raws)
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    explanation_engine = ExplanationEngine(
        decision_engine=DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo()),
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
    )
    return decision_engine, explanation_engine, news_repo, raw_repo


# ---------------------------------------------------------------------------
# Bölüm 12 — ham tekrarlar (A1/A2/A3 aynı olay + B..J bağımsız).
# ---------------------------------------------------------------------------


def test_raw_duplicates_produce_identical_membership_in_both_engines():
    t = T0 + timedelta(hours=20)
    raws = {
        "yahoo:A1": _raw("yahoo:A1", "THY rekor kâr açıkladı", published_at=t),
        "google:A2": _raw("google:A2", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=1)),
        "foreks:A3": _raw("foreks:A3", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=2)),
    }
    analyses = [
        _analysis("yahoo:A1", sentiment_score=0.0, confidence=1.0, created_at=t),
        _analysis("google:A2", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=1)),
        _analysis("foreks:A3", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=2)),
    ]
    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=3 + i)
        raw, analysis = _independent(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    decision_engine, explanation_engine, news_repo, raw_repo = _build_engines(analyses, raws)

    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    explanation = explanation_engine.explain("THYAO")

    assert len(decision.news_analysis_ids) == 10
    assert set(decision.news_analysis_ids) == set(explanation["news_analysis_ids"])
    assert decision.news_analysis_ids == explanation["news_analysis_ids"]


# ---------------------------------------------------------------------------
# Bölüm 13 — eski (ham-10-önce-dedup) davranışta I/J hiç okunmazdı.
# ---------------------------------------------------------------------------


def test_older_backfill_included_identically_in_both_engines():
    t = T0 + timedelta(hours=20)
    raws = {
        "yahoo:A1": _raw("yahoo:A1", "THY rekor kâr açıkladı", published_at=t),
        "google:A2": _raw("google:A2", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=1)),
        "foreks:A3": _raw("foreks:A3", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=2)),
    }
    analyses = [
        _analysis("yahoo:A1", sentiment_score=0.0, confidence=1.0, created_at=t),
        _analysis("google:A2", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=1)),
        _analysis("foreks:A3", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=2)),
    ]
    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=3 + i)
        raw, analysis = _independent(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    decision_engine, explanation_engine, news_repo, raw_repo = _build_engines(analyses, raws)

    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    explanation = explanation_engine.explain("THYAO")

    assert "prov:I" in decision.news_analysis_ids
    assert "prov:J" in decision.news_analysis_ids
    assert "prov:I" in explanation["news_analysis_ids"]
    assert "prov:J" in explanation["news_analysis_ids"]


# ---------------------------------------------------------------------------
# Bölüm 14 — 20 ardışık kopya sabit bir over-fetch limitinin arkasına
# gizlenmemeli, iki motor da bunu aşıp bağımsız olaylara ulaşmalı.
# ---------------------------------------------------------------------------


def test_twenty_duplicate_run_no_fixed_over_fetch_shortcut_in_either_engine():
    t = T0 + timedelta(hours=40)
    raws: dict[str, NewsRawItem] = {}
    analyses: list[NewsAnalysis] = []
    for i in range(20):
        news_id = f"dup:{i}"
        created_at = t - timedelta(minutes=i)
        raws[news_id] = _raw(news_id, "THY rekor kâr açıkladı", published_at=created_at)
        analyses.append(_analysis(news_id, sentiment_score=0.0, confidence=1.0, created_at=created_at))
    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=1 + i)
        raw, analysis = _independent(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    decision_engine, explanation_engine, news_repo, raw_repo = _build_engines(analyses, raws)

    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    explanation = explanation_engine.explain("THYAO")

    assert len(decision.news_analysis_ids) == 10
    assert decision.news_analysis_ids == explanation["news_analysis_ids"]
    assert "prov:I" in explanation["news_analysis_ids"]
    assert "prov:J" in explanation["news_analysis_ids"]


# ---------------------------------------------------------------------------
# Bölüm 15 — girdi/storage sırasından bağımsızlık.
# ---------------------------------------------------------------------------


def test_membership_independent_of_storage_insertion_order():
    t = T0
    raw_a = _raw("yahoo:1", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=t)
    raw_b = _raw(
        "google:1", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=t + timedelta(hours=1)
    )
    analysis_a = _analysis("yahoo:1", sentiment_score=50.0, confidence=1.0, created_at=t)
    analysis_b = _analysis("google:1", sentiment_score=50.0, confidence=1.0, created_at=t + timedelta(hours=1))

    forward = _build_engines([analysis_a, analysis_b], {"yahoo:1": raw_a, "google:1": raw_b})
    reversed_ = _build_engines([analysis_b, analysis_a], {"google:1": raw_b, "yahoo:1": raw_a})

    for decision_engine, explanation_engine, news_repo, raw_repo in (forward, reversed_):
        decision = decision_engine.decide_for_asset(
            "THYAO",
            technical_engine=_FakeTechnicalEngine(),
            macro_repo=_FakeMacroRepo(),
            news_repo=news_repo,
            news_raw_repo=raw_repo,
            persist=False,
        )
        explanation = explanation_engine.explain("THYAO")
        assert decision.news_analysis_ids == explanation["news_analysis_ids"]

    forward_decision = forward[0].decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=forward[2],
        news_raw_repo=forward[3],
        persist=False,
    )
    reversed_decision = reversed_[0].decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=reversed_[2],
        news_raw_repo=reversed_[3],
        persist=False,
    )
    assert forward_decision.news_analysis_ids == reversed_decision.news_analysis_ids


# ---------------------------------------------------------------------------
# Bölüm 16 — farklı asset sınırı.
# ---------------------------------------------------------------------------


def test_different_asset_boundary_holds_in_explanation_engine_too():
    t = T0
    raw_thyao = _raw("yahoo:thy", "Şirket yeni anlaşma imzaladı", published_at=t, asset="THYAO")
    raw_garan = _raw("yahoo:gar", "Şirket yeni anlaşma imzaladı", published_at=t, asset="GARAN")
    analysis_thyao = _analysis("yahoo:thy", asset="THYAO", sentiment_score=70.0, confidence=1.0, created_at=t)
    analysis_garan = _analysis("yahoo:gar", asset="GARAN", sentiment_score=-70.0, confidence=1.0, created_at=t)

    _, explanation_engine, _, _ = _build_engines(
        [analysis_thyao, analysis_garan], {"yahoo:thy": raw_thyao, "yahoo:gar": raw_garan}
    )

    result = explanation_engine.explain("THYAO")
    assert result["news_analysis_ids"] == ["yahoo:thy"]


# ---------------------------------------------------------------------------
# Bölüm 17 — legacy kayıt uyumluluğu (HATA 15D provenance alanları yok).
# ---------------------------------------------------------------------------


def test_legacy_records_without_hata_15d_provenance_fields_work_fine():
    legacy = _analysis("legacy:1", sentiment_score=40.0, confidence=1.0, created_at=T0)
    assert legacy.analyzed_text is None
    assert legacy.prompt_version is None

    _, explanation_engine, _, _ = _build_engines([legacy], {"legacy:1": _raw("legacy:1", "Eski haber", published_at=T0)})

    result = explanation_engine.explain("THYAO")
    assert result["news_analysis_ids"] == ["legacy:1"]
    assert not any("haber" in m.lower() for m in result["missing"])


# ---------------------------------------------------------------------------
# Bölüm 18 — eksik ham provenance (savunma amaçlı güvenli fallback) iki
# motorda da AYNI şekilde davranmalı, crash yok, bağımsız gruplama icat
# edilmiyor.
# ---------------------------------------------------------------------------


def test_missing_raw_provenance_same_safe_fallback_in_both_engines():
    analysis = _analysis("orphan:1", sentiment_score=25.0, confidence=1.0, created_at=T0)
    decision_engine, explanation_engine, news_repo, raw_repo = _build_engines([analysis], {})

    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    explanation = explanation_engine.explain("THYAO")

    assert decision.news_analysis_ids == ["orphan:1"]
    assert explanation["news_analysis_ids"] == ["orphan:1"]


# ---------------------------------------------------------------------------
# Bölüm 19 — YÜK TAŞIYAN (load-bearing) invariant: parity.
# ---------------------------------------------------------------------------


def test_decision_and_explanation_membership_parity():
    t = T0 + timedelta(hours=5)
    raws = {}
    analyses = []
    for i, label in enumerate("ABCDEF"):
        created_at = t - timedelta(hours=i)
        raw, analysis = _independent(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    decision_engine, explanation_engine, news_repo, raw_repo = _build_engines(analyses, raws)

    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    explanation = explanation_engine.explain("THYAO")

    assert decision.news_analysis_ids == explanation["news_analysis_ids"]


# ---------------------------------------------------------------------------
# Bölüm 20 — refactor öncesi/sonrası skor regresyonu (aynı formül).
# ---------------------------------------------------------------------------


def test_decision_news_score_unchanged_by_shared_selector_refactor():
    raw_a = _raw("yahoo:s1", "Bağımsız olay S1", published_at=T0, reliability=1.0)
    raw_b = _raw("yahoo:s2", "Bağımsız olay S2", published_at=T0 - timedelta(hours=1), reliability=1.0)
    analysis_a = _analysis("yahoo:s1", sentiment_score=100.0, confidence=1.0, created_at=T0)
    analysis_b = _analysis("yahoo:s2", sentiment_score=-100.0, confidence=1.0, created_at=T0 - timedelta(hours=1))

    decision_engine, _, news_repo, raw_repo = _build_engines(
        [analysis_a, analysis_b], {"yahoo:s1": raw_a, "yahoo:s2": raw_b}
    )
    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    # Reliability eşit (1.0/1.0) olduğu için confidence-only formülle AYNI:
    # (100*1 + -100*1) / 2 = 0.0.
    assert decision.news_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Bölüm 21 — HATA 15C reliability temsilcisi/seçimi, helper taşınmasıyla
# DEĞİŞMEMELİ.
# ---------------------------------------------------------------------------


def test_representative_reliability_unchanged_by_helper_move():
    raw_high = _raw("yahoo:r1", "THY rekor kâr açıkladı", published_at=T0, reliability=1.0)
    raw_low = _raw("google:r1", "THY rekor kâr açıkladı", published_at=T0 + timedelta(hours=1), reliability=0.3)
    analysis_high = _analysis("yahoo:r1", sentiment_score=80.0, confidence=1.0, created_at=T0)
    analysis_low = _analysis("google:r1", sentiment_score=80.0, confidence=1.0, created_at=T0 + timedelta(hours=1))

    decision_engine, _, news_repo, raw_repo = _build_engines(
        [analysis_high, analysis_low], {"yahoo:r1": raw_high, "google:r1": raw_low}
    )
    decision = decision_engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )
    # Temsilci seçimi (bkz. event_dedup.EventCluster.representative): gövde/
    # özet var + en eski yayın zamanı -- ikisi de özet taşıyor, bu yüzden
    # EN ESKİ (yahoo:r1, reliability=1.0) kazanır. Tek olay, tek katkı --
    # skor tam olarak 80*1.0 = 80.0 olmalı (0.3 asla karışmamalı).
    assert decision.news_analysis_ids == ["yahoo:r1"]
    assert decision.news_score == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Bölüm 22 — provenance regresyonu: ExplanationEngine canlı fetch/LLM
# ÇAĞIRMAMALI.
# ---------------------------------------------------------------------------


def test_explanation_engine_never_fetches_live_article_or_calls_llm(monkeypatch):
    import app.engines.event_intelligence.engine as ei_engine_module
    import app.services.news.article_fetcher as article_fetcher_module

    def _raise_fetch(*args, **kwargs):
        raise AssertionError("ExplanationEngine canlı makale fetch ETMEMELİ")

    def _raise_analyze(self, *args, **kwargs):
        raise AssertionError("ExplanationEngine LLM yeniden-analiz ÇAĞIRMAMALI")

    monkeypatch.setattr(article_fetcher_module, "fetch_article_text", _raise_fetch)
    monkeypatch.setattr(ei_engine_module.EventIntelligenceEngine, "analyze_item", _raise_analyze)

    analysis = _analysis("prov:x", sentiment_score=10.0, confidence=1.0, created_at=T0)
    raw = _raw("prov:x", "Herhangi bir olay", published_at=T0)
    _, explanation_engine, _, _ = _build_engines([analysis], {"prov:x": raw})

    result = explanation_engine.explain("THYAO")  # exception atmamalı
    assert result["news_analysis_ids"] == ["prov:x"]
