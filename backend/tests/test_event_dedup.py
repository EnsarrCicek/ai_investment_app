"""HATA 15B — cross-source event-level dedup testleri.

Kapsam: app/services/news/event_dedup.py (kümeleme motoru) +
EventIntelligenceEngine.analyze_recent_for_asset (analiz-öncesi dedup) +
DecisionEngine._deduplicate_news_analyses (skorlama-anı dedup).
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    DecisionEngine,
    _aggregate_news_score,
    _deduplicate_news_analyses,
)
from app.engines.event_intelligence import engine as ei_engine_module
from app.engines.event_intelligence.engine import EventIntelligenceEngine
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.services.news.event_dedup import (
    DEDUP_WINDOW,
    NEAR_DUPLICATE_THRESHOLD,
    DedupEntry,
    cluster_by_event,
    is_near_duplicate_title,
    normalize_title,
)

T0 = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def _news(external_id, title, published_at=T0, summary="özet metni", asset="THYAO"):
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary=summary,
        url=f"https://example.com/{external_id}",
        publisher="Test",
        source="test",
        source_reliability=0.8,
        related_assets=[asset],
        published_at=published_at,
        received_at=published_at,
    )


def _entry(news: NewsRawItem, asset="THYAO"):
    return DedupEntry(
        asset=asset,
        event_id=news.external_id,
        title=news.title,
        published_at=news.published_at,
        has_body=bool(news.summary.strip()),
        payload=news,
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


# ---------------------------------------------------------------------------
# Bölüm 24 — aynı external_id idempotency REGRESYONU (mevcut davranış).
# ---------------------------------------------------------------------------


def test_same_external_id_upsert_is_still_idempotent_by_document_id():
    # NewsRawRepository.upsert() dokümanı external_id ile SET eder (bkz.
    # news_raw_repository.py) -- HATA 15B bu mekanizmaya dokunmuyor, yalnızca
    # BUNUN ÜZERİNE ayrı bir mantıksal-olay katmanı ekliyor. Burada regresyon
    # yalnızca modelin/identity alanının değişmediğini doğruluyor.
    a = _news("yahoo:1", "THY hisseleri yükseldi")
    b = _news("yahoo:1", "THY hisseleri yükseldi (güncellendi)")
    assert a.external_id == b.external_id == "yahoo:1"


# ---------------------------------------------------------------------------
# Bölüm 25 — cross-provider EXACT title duplicate.
# ---------------------------------------------------------------------------


def test_cross_provider_exact_title_collapses_to_one_cluster():
    yahoo = _news("yahoo:1", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    google = _news("google:1", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=3))

    clusters = cluster_by_event([_entry(yahoo), _entry(google)])

    assert len(clusters) == 1
    assert {e.event_id for e in clusters[0].entries} == {"yahoo:1", "google:1"}


# ---------------------------------------------------------------------------
# Bölüm 26 — cross-provider NEAR duplicate (aynı dil, gerçekçi ufak
# ifade farkı — bkz. modül docstring'i: farklı DİL eşleşmesi bu deterministik
# yöntemin kapsamı DIŞINDA, bilinçli/belgelenen bir sınır).
# ---------------------------------------------------------------------------


def test_cross_provider_near_duplicate_collapses_to_one_cluster():
    yahoo = _news("yahoo:2", "THY üçüncü çeyrek kâr beklentisini yükseltti", published_at=T0)
    foreks = _news(
        "foreks:9", "THY üçüncü çeyrek kâr beklentisini bugün yükseltti", published_at=T0 + timedelta(hours=1)
    )
    assert is_near_duplicate_title(yahoo.title, foreks.title) is True

    clusters = cluster_by_event([_entry(yahoo), _entry(foreks)])

    assert len(clusters) == 1


# ---------------------------------------------------------------------------
# Bölüm 27 — fetch-order determinizmi.
# ---------------------------------------------------------------------------


def test_clustering_result_independent_of_input_order():
    yahoo = _news("yahoo:3", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    google = _news("google:3", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=2))
    foreks = _news("foreks:3", "THYAO 2026 rekor kâr açıkladı", published_at=T0 + timedelta(hours=5))

    forward = [_entry(yahoo), _entry(google), _entry(foreks)]
    reversed_order = [_entry(foreks), _entry(google), _entry(yahoo)]
    shuffled = [_entry(google), _entry(foreks), _entry(yahoo)]

    def _signature(clusters):
        return sorted(
            (cluster.representative.event_id, frozenset(e.event_id for e in cluster.entries))
            for cluster in clusters
        )

    sig_forward = _signature(cluster_by_event(forward))
    sig_reversed = _signature(cluster_by_event(reversed_order))
    sig_shuffled = _signature(cluster_by_event(shuffled))

    assert sig_forward == sig_reversed == sig_shuffled
    assert len(sig_forward) == 2  # {yahoo,google} birleşik + foreks ayrı


# ---------------------------------------------------------------------------
# Bölüm 28 — benzer kelime dağarcığı ama finansal olarak AYRI olay.
# ---------------------------------------------------------------------------


def test_similar_vocabulary_but_different_event_stays_separate():
    a = _news("yahoo:4", "THY yeni Airbus siparişi verdi", published_at=T0)
    b = _news("google:4", "THY yeni Boeing siparişi verdi", published_at=T0 + timedelta(hours=1))

    clusters = cluster_by_event([_entry(a), _entry(b)])

    assert len(clusters) == 2


# ---------------------------------------------------------------------------
# Bölüm 29 — negation koruması.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        ("THY signs aircraft purchase agreement", "THY cancels aircraft purchase agreement"),
        ("Company announces dividend", "Company cancels dividend"),
    ],
)
def test_negation_protection_does_not_collapse(title_a, title_b):
    a = _news("a:1", title_a, published_at=T0)
    b = _news("b:1", title_b, published_at=T0 + timedelta(hours=1))

    assert is_near_duplicate_title(title_a, title_b) is False
    clusters = cluster_by_event([_entry(a), _entry(b)])
    assert len(clusters) == 2


# ---------------------------------------------------------------------------
# Bölüm 30 — çeyrek/yıl/rakam ayrımı (normalizasyon rakamları SİLMEZ).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title_a,title_b",
    [
        ("Q1 earnings announced", "Q2 earnings announced"),
        ("THY 2026 kâr beklentisini yükseltti", "THY 2025 kâr beklentisini yükseltti"),
    ],
)
def test_numeric_distinction_protection_does_not_collapse(title_a, title_b):
    assert is_near_duplicate_title(title_a, title_b) is False
    a = _news("a:2", title_a, published_at=T0)
    b = _news("b:2", title_b, published_at=T0 + timedelta(hours=1))
    clusters = cluster_by_event([_entry(a), _entry(b)])
    assert len(clusters) == 2


def test_normalize_title_preserves_digits():
    assert "2026" in normalize_title("THY 2026 kâr beklentisini yükseltti")


# ---------------------------------------------------------------------------
# Bölüm 31 — zaman penceresi sınırı (tam sınır dahil test edilir).
# ---------------------------------------------------------------------------


def test_time_window_boundary_exact_equal_collapses():
    a = _news("a:3", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    b = _news(
        "b:3",
        "THY Airbus ile yeni uçak anlaşması imzaladı",
        published_at=T0 + DEDUP_WINDOW,  # tam sınırda -- DAHIL
    )
    clusters = cluster_by_event([_entry(a), _entry(b)])
    assert len(clusters) == 1


def test_time_window_boundary_just_over_stays_separate():
    a = _news("a:4", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    b = _news(
        "b:4",
        "THY Airbus ile yeni uçak anlaşması imzaladı",
        published_at=T0 + DEDUP_WINDOW + timedelta(seconds=1),  # sınırın az üstü
    )
    clusters = cluster_by_event([_entry(a), _entry(b)])
    assert len(clusters) == 2


def test_similar_headline_months_apart_is_genuinely_separate_event():
    a = _news("a:5", "THY 2026 üçüncü çeyrek kâr açıkladı", published_at=T0)
    b = _news("b:5", "THY 2026 üçüncü çeyrek kâr açıkladı", published_at=T0 + timedelta(days=90))
    clusters = cluster_by_event([_entry(a), _entry(b)])
    assert len(clusters) == 2


# ---------------------------------------------------------------------------
# Bölüm 32 — farklı asset sınırı.
# ---------------------------------------------------------------------------


def test_different_asset_never_merges_even_with_identical_title():
    a = _news("a:6", "Genel piyasa haberi aynı başlık", published_at=T0, asset="THYAO")
    b = _news("b:6", "Genel piyasa haberi aynı başlık", published_at=T0 + timedelta(hours=1), asset="GARAN")

    clusters = cluster_by_event([_entry(a, asset="THYAO"), _entry(b, asset="GARAN")])

    assert len(clusters) == 2
    assets_seen = {cluster.entries[0].asset for cluster in clusters}
    assert assets_seen == {"THYAO", "GARAN"}


# ---------------------------------------------------------------------------
# Bölüm 13/14 — deterministik temsilci seçimi (gövde > eski tarih > id).
# ---------------------------------------------------------------------------


def test_representative_prefers_item_with_body_over_earlier_no_body():
    earlier_no_body = _news("a:7", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0, summary="")
    later_with_body = _news(
        "b:7", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=2), summary="detay"
    )

    clusters = cluster_by_event([_entry(earlier_no_body), _entry(later_with_body)])

    assert clusters[0].representative.event_id == "b:7"


def test_representative_tie_break_is_deterministic_id_order_when_all_equal():
    a = _news("z:8", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    b = _news("a:8", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)

    clusters = cluster_by_event([_entry(a), _entry(b)])

    assert clusters[0].representative.event_id == "a:8"  # lexicographic tie-break


# ---------------------------------------------------------------------------
# Bölüm 36 — EventIntelligenceEngine analiz-öncesi dedup (LLM çağrı sayısı).
# ---------------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, response_json):
        self.response_json = response_json
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=json.dumps(self.response_json))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class _FakeOpenAIClient:
    def __init__(self, response_json):
        self.chat = SimpleNamespace(completions=_FakeCompletions(response_json))


class _FakeAnalysisRepo:
    def __init__(self, existing=None):
        self._existing = existing or {}
        self.added = []

    def add(self, analysis):
        self.added.append(analysis)
        return "fake-id"

    def get_by_news_id(self, news_id, asset):
        analysis = self._existing.get(news_id)
        return analysis if analysis is not None and analysis.asset == asset else None


class _FakeNewsRepo:
    def __init__(self, items):
        self._items = items

    def get_recent(self, symbol, limit=20):
        return self._items[:limit]


class _FakeUsageRepo:
    def add(self, log):
        pass


_VALID_RESPONSE = {
    "sentiment_score": 40.0,
    "confidence": 0.7,
    "importance": 0.5,
    "event_type": "corporate_action",
    "time_horizon": "medium_term",
    "reasoning": "gerekçe",
}


@pytest.fixture(autouse=True)
def _no_real_article_fetch(monkeypatch):
    monkeypatch.setattr(ei_engine_module, "fetch_article_text", lambda url, **kwargs: "")


def test_analyze_recent_for_asset_calls_llm_only_once_for_duplicate_cluster():
    yahoo = _news("yahoo:5", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    google = _news(
        "google:5", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=1)
    )
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(),
        news_repo=_FakeNewsRepo([yahoo, google]),
        usage_repo=_FakeUsageRepo(),
        primary_model="m",
    )

    results = engine.analyze_recent_for_asset("THYAO", limit=5)

    assert len(client.chat.completions.calls) == 1  # tek LLM çağrısı
    assert len(results) == 2
    assert results[0] is results[1]  # aynı olay -- aynı analiz paylaşılıyor
    assert results[0].news_id == "yahoo:5"  # deterministik temsilci (daha eski)


def test_analyze_recent_for_asset_independent_events_both_analyzed():
    a = _news("a:9", "THY Airbus siparişi verdi", published_at=T0)
    b = _news("b:9", "GARAN yeni şube açtı", published_at=T0 + timedelta(hours=1))
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(),
        news_repo=_FakeNewsRepo([a, b]),
        usage_repo=_FakeUsageRepo(),
        primary_model="m",
    )

    results = engine.analyze_recent_for_asset("THYAO", limit=5)

    assert len(client.chat.completions.calls) == 2
    assert results[0] is not results[1]


def test_analyze_recent_for_asset_reuses_existing_legacy_duplicate_analysis_without_new_llm_call():
    # HATA 15B bölüm 19: bu düzeltmeden ÖNCE her iki makale de bağımsız
    # analiz edilmiş olabilir (legacy). Temsilci olmayan üye zaten kendi
    # analizine sahipse, o kayıt OLDUĞU GİBİ döner -- provenance korunur,
    # LLM tekrar çağrılmaz.
    yahoo = _news("yahoo:6", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    google = _news(
        "google:6", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=1)
    )
    legacy_google_analysis = _analysis("google:6", sentiment_score=99.0)
    client = _FakeOpenAIClient(_VALID_RESPONSE)
    engine = EventIntelligenceEngine(
        client=client,
        analysis_repo=_FakeAnalysisRepo(existing={"google:6": legacy_google_analysis}),
        news_repo=_FakeNewsRepo([yahoo, google]),
        usage_repo=_FakeUsageRepo(),
        primary_model="m",
    )

    results = engine.analyze_recent_for_asset("THYAO", limit=5)

    assert len(client.chat.completions.calls) == 1  # yalnız temsilci (yahoo:6) için
    result_by_id = {r.news_id if hasattr(r, "news_id") else None: r for r in results}
    google_result = [r for r in results if r.news_id == "google:6"]
    assert google_result == [legacy_google_analysis]


# ---------------------------------------------------------------------------
# Bölüm 33/34/35/19 — DecisionEngine skorlama-anı dedup (legacy duplicate
# NewsAnalysis kayıtları, tam sayısal skor kilidi).
# ---------------------------------------------------------------------------


class _FakeNewsRawRepoWithData:
    def __init__(self, raw_by_id):
        self._raw_by_id = raw_by_id

    def get_by_external_id(self, external_id):
        return self._raw_by_id.get(external_id)


def test_deduplicate_news_analyses_collapses_legacy_duplicate_analyses():
    raw_a = _news("yahoo:7", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0)
    raw_b = _news(
        "google:7", "THY Airbus ile yeni uçak anlaşması imzaladı", published_at=T0 + timedelta(hours=1)
    )
    raw_c = _news("foreks:7", "GARAN yeni şube açtı", published_at=T0 + timedelta(hours=2))

    analyses = [
        _analysis("yahoo:7", sentiment_score=90.0, confidence=1.0, created_at=T0),
        _analysis("google:7", sentiment_score=90.0, confidence=1.0, created_at=T0 + timedelta(hours=1)),
        _analysis("foreks:7", sentiment_score=-90.0, confidence=1.0, created_at=T0 + timedelta(hours=2)),
    ]
    raw_repo = _FakeNewsRawRepoWithData({"yahoo:7": raw_a, "google:7": raw_b, "foreks:7": raw_c})

    deduped = _deduplicate_news_analyses(analyses, raw_repo)

    assert {a.news_id for a in deduped} == {"yahoo:7", "foreks:7"}  # google:7 aynı olay, elendi
    assert len(deduped) == 2


def test_score_effect_duplicate_event_no_longer_dominates_aggregate():
    # Ticket bölüm 35 örneği: Event A (3 sağlayıcıdan +90) vs Event B
    # (bağımsız, -90). DÜZELTMEDEN ÖNCE 3 kopya A'yı domine ederdi. DÜZELTME
    # SONRASI A bir kez, B bir kez katkı yapmalı -- eşit confidence ile
    # beklenen ortalama TAM OLARAK (90 + -90) / 2 = 0.0.
    t = T0
    raw_a1 = _news("yahoo:a", "THY rekor kâr açıkladı", published_at=t)
    raw_a2 = _news("google:a", "THY rekor kâr açıkladı", published_at=t + timedelta(hours=1))
    raw_a3 = _news("foreks:a", "THY rekor kâr açıkladı", published_at=t + timedelta(hours=2))
    raw_b = _news("yahoo:b", "GARAN büyük zarar açıkladı", published_at=t + timedelta(hours=3))

    analyses = [
        _analysis("yahoo:a", sentiment_score=90.0, confidence=1.0, created_at=t),
        _analysis("google:a", sentiment_score=90.0, confidence=1.0, created_at=t + timedelta(hours=1)),
        _analysis("foreks:a", sentiment_score=90.0, confidence=1.0, created_at=t + timedelta(hours=2)),
        _analysis("yahoo:b", sentiment_score=-90.0, confidence=1.0, created_at=t + timedelta(hours=3)),
    ]
    raw_repo = _FakeNewsRawRepoWithData(
        {"yahoo:a": raw_a1, "google:a": raw_a2, "foreks:a": raw_a3, "yahoo:b": raw_b}
    )

    # Düzeltme ÖNCESİ (dedup uygulanmadan) -- kilit için referans: 3xA + 1xB.
    before_score = _aggregate_news_score(analyses)
    assert before_score == pytest.approx(45.0)  # (90*3 + -90) / 4

    deduped = _deduplicate_news_analyses(analyses, raw_repo)
    after_score = _aggregate_news_score(deduped)

    assert len(deduped) == 2
    assert after_score == pytest.approx(0.0)  # (90 + -90) / 2 -- artık A tek, B tek


# ---------------------------------------------------------------------------
# Bölüm 34 — "son-10 BENZERSİZ olay" penceresi (raw makale değil).
# ---------------------------------------------------------------------------


def test_last_n_window_counts_unique_events_not_raw_articles():
    t = T0
    # Bir olay 3 sağlayıcıdan geliyor + 5 bağımsız olay = 8 ham analiz kaydı,
    # ama yalnızca 6 BENZERSİZ mantıksal olay olmalı.
    dup_raws = {
        "p1": _news("p1", "THY rekor kâr açıkladı", published_at=t),
        "p2": _news("p2", "THY rekor kâr açıkladı", published_at=t + timedelta(hours=1)),
        "p3": _news("p3", "THY rekor kâr açıkladı", published_at=t + timedelta(hours=2)),
    }
    independent_raws = {
        f"i{i}": _news(f"i{i}", f"Bağımsız olay numara {i}", published_at=t + timedelta(hours=3 + i))
        for i in range(5)
    }
    all_raws = {**dup_raws, **independent_raws}

    analyses = [
        _analysis(news_id, sentiment_score=10.0, confidence=1.0, created_at=all_raws[news_id].published_at)
        for news_id in all_raws
    ]
    raw_repo = _FakeNewsRawRepoWithData(all_raws)

    deduped = _deduplicate_news_analyses(analyses, raw_repo)

    assert len(deduped) == 6  # 1 (dup olayı) + 5 bağımsız


# ---------------------------------------------------------------------------
# Bölüm 37 — geriye dönük uyumluluk: ham kaydı bulunamayan analiz crash
# ETMEMELİ, kendi başına tek üyeli küme olarak GÜVENLİ geçilmeli.
# ---------------------------------------------------------------------------


def test_backward_compatibility_missing_raw_record_does_not_crash():
    raw_repo = _FakeNewsRawRepoWithData({})  # hiçbir ham kayıt yok (eski/silinmiş veri simülasyonu)
    analyses = [
        _analysis("old:1", sentiment_score=50.0, confidence=1.0, created_at=T0),
        _analysis("old:2", sentiment_score=-50.0, confidence=1.0, created_at=T0 + timedelta(hours=1)),
    ]

    deduped = _deduplicate_news_analyses(analyses, raw_repo)

    assert len(deduped) == 2  # kümelenemediler -- ikisi de ayrı kaldı, crash yok
    assert _aggregate_news_score(deduped) == pytest.approx(0.0)


def test_deduplicate_news_analyses_empty_input_returns_empty():
    assert _deduplicate_news_analyses([], _FakeNewsRawRepoWithData({})) == []


# ---------------------------------------------------------------------------
# Bölüm 38 — Foreks intra-batch davranışı REGRESYONU (ayrı, KENDİ eşiğiyle
# hâlâ çalışıyor -- bu ticket onu DEĞİŞTİRMİYOR, bkz. foreks_news_provider.py
# `_NEAR_DUPLICATE_THRESHOLD`. Cross-source mekanizması AYNI eşiği (0.82)
# başlangıç noktası olarak kullanıyor ama tamamen bağımsız bir katman.
# ---------------------------------------------------------------------------


def test_foreks_own_threshold_matches_shared_cross_source_default():
    from app.services.news import foreks_news_provider

    assert foreks_news_provider._NEAR_DUPLICATE_THRESHOLD == NEAR_DUPLICATE_THRESHOLD


# ---------------------------------------------------------------------------
# DecisionEngine.decide_for_asset uçtan uca -- dedup gerçekten skora yansıyor.
# ---------------------------------------------------------------------------


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
        return SimpleNamespace(technical_score=None, confidence=None), "tech-id"


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeAnalysisListRepo:
    def __init__(self, analyses):
        self._analyses = analyses

    def list_for_asset(self, asset, limit=10):
        return self._analyses


def test_decide_for_asset_end_to_end_uses_deduplicated_news_score():
    t = T0
    raw_a1 = _news("yahoo:e2e", "THY rekor kâr açıkladı", published_at=t)
    raw_a2 = _news("google:e2e", "THY rekor kâr açıkladı", published_at=t + timedelta(hours=1))
    news_repo = _FakeAnalysisListRepo(
        [
            _analysis("yahoo:e2e", sentiment_score=80.0, confidence=1.0, created_at=t),
            _analysis("google:e2e", sentiment_score=80.0, confidence=1.0, created_at=t + timedelta(hours=1)),
        ]
    )
    raw_repo = _FakeNewsRawRepoWithData({"yahoo:e2e": raw_a1, "google:e2e": raw_a2})
    engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())

    decision = engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )

    assert decision.news_score == 80.0  # dedup sonrası (öncesi de aynı 80 olurdu bu simetrik örnekte,
    # ama news_analysis_ids TEKİLLEŞMİŞ olmalı -- gerçek kanıt budur:
    assert decision.news_analysis_ids == ["yahoo:e2e"]


# ---------------------------------------------------------------------------
# HATA 15B FINAL — etkin pencere "son 10 BENZERSİZ OLAY" olmalı, "son 10 ham
# kayıttan tekilleştirilmiş alt küme" DEĞİL. `list_for_asset(limit=NEWS_
# SCORE_LIMIT)` erken limit uyguladığı için (Firestore sorgusu zaten TÜM
# eşleşen kayıtları okuyordu, kesme yalnızca Python tarafındaydı) tekrarlar
# en yeni 10 ham slot'u işgal ettiğinde ondan eskiye giden BAĞIMSIZ olaylar
# hiç okunmadan pencereden dışarı kalıyordu.
# ---------------------------------------------------------------------------


class _FakeNewsRepoAssertsUnboundedFetch:
    """Gerçek `NewsAnalysisRepository.list_for_asset` davranışını taklit eder:
    created_at azalan sıralı TÜM kayıtları döner. `decide_for_asset()`'in
    dedup'ı TÜM geçmiş üzerinde yapabilmesi için limit'i `None` ile çağırdığını
    KİLİTLER -- eski (hatalı) erken-limit davranışına regresyon olursa bu fake
    AssertionError fırlatır, testler net şekilde kırılır."""

    def __init__(self, analyses):
        self._analyses = sorted(analyses, key=lambda a: a.created_at, reverse=True)

    def list_for_asset(self, asset, limit=20):
        if limit is not None:
            raise AssertionError(
                "decide_for_asset() list_for_asset()'i limit=None ile çağırmalı "
                f"(dedup TÜM geçmiş üzerinde, limit SONRADAN uygulanmalı) -- "
                f"erken limit uygulanmış: {limit!r}"
            )
        return list(self._analyses)


def _independent_raw_and_analysis(label, created_at, score):
    """Bölüm 8/9/11 testleri için tekrar kullanılan yardımcı: birbirine hiç
    benzemeyen (Jaccard eşiğinin altında), bağımsız bir olay üretir."""
    raw = _news(f"prov:{label}", f"Bağımsız olay numara {label}", published_at=created_at)
    analysis = _analysis(f"prov:{label}", sentiment_score=score, confidence=1.0, created_at=created_at)
    return raw, analysis


def test_limit_backfill_pulls_older_independent_events_past_newest_ten_raw_slots():
    # Ticket bölüm 8/9: en yeni 3 ham kayıt (A1/A2/A3) AYNI olayı temsil
    # ediyor. Onların ardından B..J (9 bağımsız olay) geliyor -- toplam 12 ham
    # kayıt, ama tam olarak 10 BENZERSİZ mantıksal olay (A + B..J) var. I ve J
    # en yeni 10 ham kayıt arasında DEĞİL (A1,A2,A3,B..H = 10. slot), bu yüzden
    # eski (hatalı) davranış onları hiç okumazdı.
    t = T0 + timedelta(hours=20)
    raw_a1 = _news("yahoo:A1", "THY rekor kâr açıkladı", published_at=t)
    raw_a2 = _news("google:A2", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=1))
    raw_a3 = _news("foreks:A3", "THY rekor kâr açıkladı", published_at=t - timedelta(hours=2))
    analyses = [
        _analysis("yahoo:A1", sentiment_score=0.0, confidence=1.0, created_at=t),
        _analysis("google:A2", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=1)),
        _analysis("foreks:A3", sentiment_score=0.0, confidence=1.0, created_at=t - timedelta(hours=2)),
    ]
    raws = {"yahoo:A1": raw_a1, "google:A2": raw_a2, "foreks:A3": raw_a3}

    # B..J = 9 bağımsız olay, sırasıyla 10.0, 20.0, ..., 90.0 puanlı --
    # J (en eski, +90.0) tam olarak en yeni 10 ham slot'un DIŞINDA kalıyor
    # (slot 12), I (+80.0) da öyle (slot 11).
    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=3 + i)
        raw, analysis = _independent_raw_and_analysis(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    assert len(analyses) == 12  # A1,A2,A3 + B..J

    raw_repo = _FakeNewsRawRepoWithData(raws)
    news_repo = _FakeNewsRepoAssertsUnboundedFetch(analyses)
    engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())

    decision = engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )

    # 10 BENZERSİZ olay: A (temsilci) + B..J.
    assert len(decision.news_analysis_ids) == 10
    assert "yahoo:A1" in decision.news_analysis_ids or "google:A2" in decision.news_analysis_ids or (
        "foreks:A3" in decision.news_analysis_ids
    )
    # I (prov:I, +80.0) ve J (prov:J, +90.0) etkin sete DAHİL -- eski (hatalı)
    # davranışta bunlar hiç okunmazdı.
    assert "prov:I" in decision.news_analysis_ids
    assert "prov:J" in decision.news_analysis_ids

    # Bölüm 9 -- TAM sayısal skor kilidi: A=0, B..J=10..90 -> ortalama 45.0.
    # Eski (hatalı) davranış I/J'yi hiç okumadan yalnızca 8 benzersiz olay
    # (A,B,C,D,E,F,G,H) üzerinden 35.0 hesaplardı -- bu test o farkı kilitler.
    assert decision.news_score == pytest.approx(45.0)


def test_large_duplicate_run_does_not_hide_behind_a_fixed_over_fetch_limit():
    # Ticket bölüm 11: 20 en yeni ham kayıt AYNI olayı (A) temsil ediyor,
    # ardından 9 bağımsız olay (B..J) geliyor. Sabit bir "over-fetch limiti"
    # (ör. 20) kullanan bir implementasyon, tam da bu 20 kopyanın ARDINDAN
    # gelen bağımsız olayları hiç göremezdi.
    t = T0 + timedelta(hours=40)
    raws: dict[str, object] = {}
    analyses = []
    for i in range(20):
        news_id = f"dup:{i}"
        created_at = t - timedelta(minutes=i)
        raws[news_id] = _news(news_id, "THY rekor kâr açıkladı", published_at=created_at)
        analyses.append(_analysis(news_id, sentiment_score=0.0, confidence=1.0, created_at=created_at))

    for i, label in enumerate("BCDEFGHIJ"):
        created_at = t - timedelta(hours=1 + i)
        raw, analysis = _independent_raw_and_analysis(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    assert len(analyses) == 29  # 20 kopya + 9 bağımsız

    raw_repo = _FakeNewsRawRepoWithData(raws)
    news_repo = _FakeNewsRepoAssertsUnboundedFetch(analyses)
    engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())

    decision = engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )

    assert len(decision.news_analysis_ids) == 10  # A (temsilci) + B..J
    assert "prov:I" in decision.news_analysis_ids
    assert "prov:J" in decision.news_analysis_ids


def test_fewer_than_ten_unique_events_returns_all_available_no_fabrication():
    # Ticket bölüm 10: tüm geçmişte yalnızca 6 BENZERSİZ mantıksal olay
    # varsa, eksik 4 slot UYDURULMAZ -- 6 döner.
    t = T0 + timedelta(hours=5)
    raws = {}
    analyses = []
    for i, label in enumerate("ABCDEF"):
        created_at = t - timedelta(hours=i)
        raw, analysis = _independent_raw_and_analysis(label, created_at, score=10.0 * (i + 1))
        raws[analysis.news_id] = raw
        analyses.append(analysis)

    raw_repo = _FakeNewsRawRepoWithData(raws)
    news_repo = _FakeNewsRepoAssertsUnboundedFetch(analyses)
    engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())

    decision = engine.decide_for_asset(
        "THYAO",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        news_raw_repo=raw_repo,
        persist=False,
    )

    assert len(decision.news_analysis_ids) == 6
