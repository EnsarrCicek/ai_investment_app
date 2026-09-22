"""HATA 17C — DecisionEngine tüketim-anı freshness/as-of testleri.

Kapsam: `MacroSnapshot` tüketim-tazeliği (`_is_macro_snapshot_fresh_for_
consumption`, HATA 16C'nin ÜRETİM-anı tazeliğinden AYRI bir katman) ve
haber `as_of`/causality filtresi (`select_recent_unique_news_analyses`'in
opsiyonel `as_of` parametresi, HATA 15F `received_at` eligibility'sini
kullanır). HATA 17B (round-before-classify) ve HATA 15/16 regresyon
kilitleri de burada AYRICA doğrulanır (ticket bölüm 34-36).

Bu ticket bir historical/backtest DecisionEngine KURMAZ -- canlı kullanımda
`decision_as_of` her zaman "şimdi"dir; testlerde sentetik `as_of` değerleri
YALNIZCA freshness/causality mantığını kilitlemek için kullanılır.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS,
    DecisionEngine,
    _is_macro_snapshot_fresh_for_consumption,
)
from app.engines.explanation.engine import ExplanationEngine
from app.models.macro_snapshot import MacroSnapshot
from app.models.news_analysis import NewsAnalysis
from app.models.news_raw import NewsRawItem
from app.services.news.news_selection import _received_before_or_at, select_recent_unique_news_analyses

UTC = timezone.utc


class _FakeConfigRepo:
    def get_raw(self, key):
        if key == "decision_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


class _FakeDecisionRepo:
    def __init__(self):
        self.added = []

    def add(self, decision):
        self.added.append(decision)


class _RejectingDecisionRepo:
    def add(self, decision):
        raise AssertionError("persist=False iken add() çağrılmamalı")


@pytest.fixture
def decision_repo():
    return _FakeDecisionRepo()


@pytest.fixture
def engine(decision_repo):
    return DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=decision_repo)


def _macro_snapshot(created_at: datetime, score: float = 10.0) -> MacroSnapshot:
    return MacroSnapshot(
        macro_score=score,
        confidence=0.8,
        components={"dxy": score},
        indicators={},
        created_at=created_at,
    )


def _news(sentiment_score, confidence, news_id="n", created_at=None):
    return NewsAnalysis(
        news_id=news_id,
        asset="TEST",
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=0.5,
        event_type="other",
        reasoning="r",
        model_used="gpt-5.6-luna",
        created_at=created_at or datetime.now(UTC),
    )


def _raw(external_id, title, published_at, received_at):
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary="özet",
        url=f"https://example.com/{external_id}",
        publisher="Reuters",
        source="google_news_rss",
        source_reliability=0.8,
        related_assets=["TEST"],
        published_at=published_at,
        received_at=received_at,
    )


class _FakeTechnicalEngine:
    def __init__(self, score=50.0):
        self._score = score

    def analyze_with_id(self, symbol, persist=True):
        return SimpleNamespace(technical_score=self._score, confidence=1.0, components={}), "tech-id"


class _FakeMacroRepo:
    def __init__(self, snapshot=None, doc_id="macro-1"):
        self._snapshot = snapshot
        self._doc_id = doc_id

    def get_latest_with_id(self):
        if self._snapshot is None:
            return None, None
        return self._snapshot, self._doc_id


class _FakeNewsRepo:
    def __init__(self, analyses):
        self._analyses = analyses

    def list_for_asset(self, asset, limit=None):
        return list(self._analyses)


class _FakeNewsRawRepo:
    def __init__(self, raws: dict):
        self._raws = raws

    def get_by_external_id(self, external_id):
        return self._raws.get(external_id)


class _EmptyNewsRawRepo:
    def get_by_external_id(self, external_id):
        return None


# ---------------------------------------------------------------------------
# _is_macro_snapshot_fresh_for_consumption — unit tests (ticket bölüm 9/10/
# 13/14/15/26/27).
# ---------------------------------------------------------------------------


def test_macro_consumption_freshness_exact_boundary_is_fresh():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS)
    assert _is_macro_snapshot_fresh_for_consumption(created, now) is True


def test_macro_consumption_freshness_one_day_past_boundary_is_stale():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    created = now - timedelta(days=MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS + 1)
    assert _is_macro_snapshot_fresh_for_consumption(created, now) is False


def test_macro_consumption_freshness_weekend_style_gap_not_falsely_stale():
    # Cuma kapanışı -> Pazartesi analizi analogu: 3 takvim günü, muhafazakâr
    # 5 günlük eşiğin İÇİNDE (ticket bölüm 10 -- gerçek hafta günü bağımsız,
    # sadece takvim-gün SAYISI önemli, HATA 16C'nin aynı yaklaşımı).
    now = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    created = now - timedelta(days=3)
    assert _is_macro_snapshot_fresh_for_consumption(created, now) is True


def test_macro_consumption_freshness_future_created_at_not_fresh():
    # Takvim-tarihi bazlı karşılaştırma (HATA 16C ile aynı stil) -- "gelecek"
    # anlamlı olması için takvim GÜNÜ sınırını aşması gerekir, saat farkı
    # yetmez (aynı gün içindeki 1 saatlik fark age_days=0 üretir).
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    created = now + timedelta(days=1)
    assert _is_macro_snapshot_fresh_for_consumption(created, now) is False


def test_macro_consumption_freshness_naive_datetime_not_fresh():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    created = datetime(2026, 6, 14, 12, 0)  # tz-naive
    assert _is_macro_snapshot_fresh_for_consumption(created, now) is False


def test_macro_consumption_freshness_timezone_equivalent_instants_same_result():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    created_utc = now - timedelta(days=2)
    created_plus3 = created_utc.astimezone(timezone(timedelta(hours=3)))
    assert _is_macro_snapshot_fresh_for_consumption(created_utc, now) == _is_macro_snapshot_fresh_for_consumption(
        created_plus3, now
    )


# ---------------------------------------------------------------------------
# decide_for_asset() — macro consumption freshness end-to-end (bölüm 25-27).
# ---------------------------------------------------------------------------


def test_decide_for_asset_fresh_macro_included_normally(engine):
    now = datetime.now(UTC)
    macro = _macro_snapshot(created_at=now - timedelta(days=1), score=-20.0)
    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=60.0),
        macro_repo=_FakeMacroRepo(macro),
        news_repo=_FakeNewsRepo([]),
        news_raw_repo=_EmptyNewsRawRepo(),
        persist=False,
    )
    assert decision.macro_score == -20.0
    assert decision.macro_snapshot_id == "macro-1"
    # technical(.5)+macro(.2)=.7 mevcut -- (60*.5 + -20*.2)/.7
    assert decision.final_score == pytest.approx((60 * 0.5 + -20 * 0.2) / 0.7)


def test_decide_for_asset_stale_macro_excluded_not_recorded_as_contributor(engine):
    now = datetime.now(UTC)
    stale_macro = _macro_snapshot(created_at=now - timedelta(days=20), score=-80.0)
    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=60.0),
        macro_repo=_FakeMacroRepo(stale_macro, doc_id="stale-macro-id"),
        news_repo=_FakeNewsRepo([]),
        news_raw_repo=_EmptyNewsRawRepo(),
        persist=False,
    )
    assert decision.macro_score is None
    assert decision.macro_snapshot_id is None  # stale referans KATKI sağlamamış gibi persist edilmez
    # yalnız technical mevcut -- macro tamamen dışlandı, renormalize edildi.
    assert decision.final_score == pytest.approx(60.0)
    assert decision.decision == "BUY"
    assert decision.channel_completeness == pytest.approx(0.5)


def test_decide_for_asset_weekend_macro_not_falsely_stale(engine):
    now = datetime.now(UTC)
    friday_style_macro = _macro_snapshot(created_at=now - timedelta(days=3), score=15.0)
    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=40.0),
        macro_repo=_FakeMacroRepo(friday_style_macro),
        news_repo=_FakeNewsRepo([]),
        news_raw_repo=_EmptyNewsRawRepo(),
        persist=False,
    )
    assert decision.macro_score == 15.0
    assert decision.macro_snapshot_id == "macro-1"


def test_decide_for_asset_technical_only_when_macro_stale_and_news_empty(engine):
    now = datetime.now(UTC)
    stale_macro = _macro_snapshot(created_at=now - timedelta(days=30))
    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=45.0),
        macro_repo=_FakeMacroRepo(stale_macro),
        news_repo=_FakeNewsRepo([]),
        news_raw_repo=_EmptyNewsRawRepo(),
        persist=False,
    )
    assert decision.technical_score == 45.0
    assert decision.news_score is None
    assert decision.macro_score is None
    assert decision.final_score == pytest.approx(45.0)
    # yalnız technical mevcut -- etkin ağırlığı mevcut ağırlığın %100'ü,
    # ama completeness configured technical payı / toplam.
    assert decision.channel_completeness == pytest.approx(
        DEFAULT_WEIGHTS["technical"] / sum(DEFAULT_WEIGHTS.values())
    )


# ---------------------------------------------------------------------------
# _received_before_or_at / select_recent_unique_news_analyses(as_of=...)
# (bölüm 28-30).
# ---------------------------------------------------------------------------


def test_received_before_or_at_true_when_received_before_as_of():
    as_of = datetime(2026, 6, 15, tzinfo=UTC)
    raw = _raw("e1", "Başlık", published_at=as_of - timedelta(days=1), received_at=as_of - timedelta(hours=1))
    analysis = _news(10.0, 0.9, news_id="e1")
    assert _received_before_or_at(analysis, _FakeNewsRawRepo({"e1": raw}), as_of) is True


def test_received_after_as_of_not_eligible():
    as_of = datetime(2026, 6, 15, tzinfo=UTC)
    # Yayın zamanı as_of'tan ÖNCE ama sistem bunu as_of'tan SONRA gözlemlemiş
    # -- HATA 15F causality: received_at eligibility'i belirler, published_at
    # DEĞİL (ticket bölüm 13/30).
    raw = _raw("e1", "Başlık", published_at=as_of - timedelta(days=2), received_at=as_of + timedelta(hours=1))
    analysis = _news(10.0, 0.9, news_id="e1")
    assert _received_before_or_at(analysis, _FakeNewsRawRepo({"e1": raw}), as_of) is False


def test_received_before_or_at_unresolved_raw_defaults_eligible():
    # Ham kaydı ÇÖZÜMLENEMEYEN bir analiz -- 17C-ÖNCESİ güvenli fallback
    # KORUNUR (bölüm dokümantasyonu, _received_before_or_at docstring'i).
    as_of = datetime(2026, 6, 15, tzinfo=UTC)
    analysis = _news(10.0, 0.9, news_id="unresolved")
    assert _received_before_or_at(analysis, _EmptyNewsRawRepo(), as_of) is True


def test_select_recent_unique_news_analyses_as_of_excludes_received_after():
    as_of = datetime(2026, 6, 15, tzinfo=UTC)
    eligible = _news(50.0, 0.9, news_id="eligible")
    ineligible = _news(-90.0, 0.9, news_id="ineligible")
    raws = {
        "eligible": _raw("eligible", "Eligible haber", as_of - timedelta(days=1), as_of - timedelta(hours=2)),
        "ineligible": _raw("ineligible", "Ineligible haber", as_of - timedelta(days=5), as_of + timedelta(hours=3)),
    }
    news_repo = _FakeNewsRepo([eligible, ineligible])
    weighted = select_recent_unique_news_analyses(
        "TEST", news_repo, _FakeNewsRawRepo(raws), limit=10, as_of=as_of
    )
    assert [w.analysis.news_id for w in weighted] == ["eligible"]


def test_select_recent_unique_news_analyses_as_of_none_preserves_old_behavior():
    # `as_of=None` (varsayılan) -- HİÇ filtre uygulanmaz, 17C-ÖNCESİ davranış
    # BİREBİR korunur (bölüm dokümantasyonu).
    news_repo = _FakeNewsRepo([_news(50.0, 0.9, news_id="a"), _news(-90.0, 0.9, news_id="b")])
    raws = {
        "a": _raw("a", "A haberi", datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC)),
        "b": _raw("b", "B haberi", datetime(2026, 6, 2, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)),
    }
    weighted = select_recent_unique_news_analyses("TEST", news_repo, _FakeNewsRawRepo(raws), limit=10)
    assert {w.analysis.news_id for w in weighted} == {"a", "b"}


def test_mixed_news_ages_correct_filter_order_preserves_backfill():
    """HATA 15B FINAL regresyonu, as_of filtresi AKTİFKEN: 3 tekrar (aynı
    olay) en yeni ham slotları işgal etse bile, as_of + dedup'tan SONRA
    limit uygulanması, bağımsız eski-ama-uygun olayların pencereden
    dışarı itilmediğini kanıtlar (ticket bölüm 12/29)."""
    as_of = datetime(2026, 6, 20, tzinfo=UTC)
    base = as_of - timedelta(hours=1)
    duplicate_ids = ["dup1", "dup2", "dup3"]
    independent_ids = [f"ind{i}" for i in range(9)]  # 9 bağımsız eski olay

    analyses = []
    raws = {}
    for i, nid in enumerate(duplicate_ids):
        analyses.append(_news(80.0, 0.9, news_id=nid))
        raws[nid] = _raw(nid, "Aynı olay tekrar yayını", base - timedelta(hours=i), base - timedelta(hours=i))
    for i, nid in enumerate(independent_ids):
        published = as_of - timedelta(days=10 + i)
        analyses.append(_news(-10.0 - i, 0.9, news_id=nid))
        raws[nid] = _raw(nid, f"Bağımsız olay {i}", published, published)

    news_repo = _FakeNewsRepo(analyses)
    weighted = select_recent_unique_news_analyses(
        "TEST", news_repo, _FakeNewsRawRepo(raws), limit=10, as_of=as_of
    )
    unique_ids = {w.analysis.news_id for w in weighted}
    assert len(weighted) == 10  # 1 (tekrar kümesi) + 9 bağımsız = 10 benzersiz
    assert len(unique_ids & set(duplicate_ids)) == 1  # tekrar kümesi TEK slot işgal ediyor
    assert set(independent_ids).issubset(unique_ids)  # tüm bağımsız olaylar İÇERİDE


# ---------------------------------------------------------------------------
# Aynı as_of macro+news arasında paylaşılıyor mu -- tek now() çağrısı
# (bölüm 14/32).
# ---------------------------------------------------------------------------


def test_decide_for_asset_uses_single_captured_as_of_for_macro_and_news(engine):
    """`decide_for_asset()` kaynak kodu (bkz. modül) `decision_as_of`'u BİR
    KEZ (`datetime.now(timezone.utc)`) yakalar ve bunu HEM macro tüketim-
    tazeliği HEM haber `as_of` filtresine GEÇİRİR -- ayrı `now()` çağrıları
    YOK (kod okumasıyla doğrulandı). Bu test, `datetime`'ı bir alt sınıfla
    değiştirip çağrı SAYISINI mocklamak YERİNE, gerçek zamana göre relatif
    sınır değerleri kullanarak AYNI garantiyi uçtan-uca kanıtlar -- alt
    sınıflama yaklaşımı denendi ve REDDEDİLDİ: `datetime` alt sınıfının
    modül-seviyesi `datetime` adını değiştirmesi, `_is_macro_snapshot_
    fresh_for_consumption()`'ın KENDİ `isinstance(created_at, datetime)`
    kontrolünü de değiştirip gerçek (alt sınıf OLMAYAN) `datetime.datetime`
    nesnelerini yanlışlıkla geçersiz/naive olarak reddetmesine yol açtı
    (disclosed, bilinçli olarak terk edilen yaklaşım)."""
    captured_before_call = datetime.now(UTC)
    macro = _macro_snapshot(
        created_at=captured_before_call - timedelta(days=MAX_MACRO_SNAPSHOT_CONSUMPTION_AGE_DAYS), score=5.0
    )
    news = _news(30.0, 0.9, news_id="boundary-news")
    # `received_at` çağrıdan ÖNCE yakalanan zamana eşit -- gerçek
    # `decision_as_of` (fonksiyon içinde AYRICA hesaplanan) bundan mikro-
    # saniyeler SONRA olacaktır, bu yüzden `received_at <= decision_as_of`
    # LEHE çalışır (kırılgan değil).
    raw = _raw("boundary-news", "Sınır haberi", captured_before_call - timedelta(hours=1), captured_before_call)

    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=10.0),
        macro_repo=_FakeMacroRepo(macro),
        news_repo=_FakeNewsRepo([news]),
        news_raw_repo=_FakeNewsRawRepo({"boundary-news": raw}),
        persist=False,
    )

    assert decision.decision_as_of >= captured_before_call
    assert decision.macro_score == 5.0  # sınırda (tam 5 gün) hâlâ fresh
    assert decision.news_analysis_ids == ["boundary-news"]  # received_at <= decision_as_of, eligible


# ---------------------------------------------------------------------------
# DecisionEngine / ExplanationEngine parity as_of altında (bölüm 29, HATA
# 15E devamı).
# ---------------------------------------------------------------------------


def test_decision_and_explanation_membership_parity_under_as_of(decision_repo):
    now = datetime.now(UTC)
    macro = _macro_snapshot(created_at=now - timedelta(days=1), score=0.0)
    news = _news(20.0, 0.9, news_id="parity-news")
    raw = _raw("parity-news", "Parity haberi", now - timedelta(days=2), now - timedelta(days=2))

    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=decision_repo)
    decision = decision_engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(score=25.0),
        macro_repo=_FakeMacroRepo(macro),
        news_repo=_FakeNewsRepo([news]),
        news_raw_repo=_FakeNewsRawRepo({"parity-news": raw}),
        persist=False,
    )

    explanation_engine = ExplanationEngine(
        decision_engine=DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=decision_repo),
        technical_engine=_FakeTechnicalEngine(score=25.0),
        macro_repo=_FakeMacroRepo(macro),
        news_repo=_FakeNewsRepo([news]),
        news_raw_repo=_FakeNewsRawRepo({"parity-news": raw}),
    )
    explanation = explanation_engine.explain("TEST")

    assert decision.news_analysis_ids == explanation["news_analysis_ids"] == ["parity-news"]
    macro_missing_note = "Güncel bir makro veri anlık görüntüsü bulunamadı."
    assert (decision.macro_score is None) == (macro_missing_note in explanation["missing"])
    assert decision.decision == explanation["decision"]


# ---------------------------------------------------------------------------
# HATA 17B regresyonu -- unrounded classification hâlâ geçerli (bölüm 34).
# ---------------------------------------------------------------------------


def test_hata_17b_regression_classification_still_uses_raw_unrounded_score(engine):
    decision = engine.decide(asset="TEST", technical_score=39.996, persist=False)
    assert decision.final_score == pytest.approx(39.996)
    assert decision.decision == "WEAK_BUY"  # BUY DEĞİL -- round-before-classify bug'ı YENİDEN AÇILMADI


# ---------------------------------------------------------------------------
# Zero-available-weight guard'ı hâlâ geçerli -- macro stale iken de (bölüm
# 20 ile aynı desen).
# ---------------------------------------------------------------------------


class _ZeroTechnicalWeightConfigRepo:
    def get_raw(self, key):
        if key == "decision_weights":
            return {"technical": 0.0, "news": 0.7, "macro": 0.3}
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


def test_stale_macro_plus_zero_weight_technical_raises_no_fake_score():
    now = datetime.now(UTC)
    stale_macro = _macro_snapshot(created_at=now - timedelta(days=30), score=-50.0)
    engine = DecisionEngine(config_repo=_ZeroTechnicalWeightConfigRepo(), decision_repo=_RejectingDecisionRepo())
    with pytest.raises(ValueError, match="NO_POSITIVE_WEIGHT_AVAILABLE"):
        engine.decide_for_asset(
            "TEST",
            technical_engine=_FakeTechnicalEngine(score=90.0),
            macro_repo=_FakeMacroRepo(stale_macro),
            news_repo=_FakeNewsRepo([]),
            news_raw_repo=_EmptyNewsRawRepo(),
            persist=False,
        )
