from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DecisionEngine, _aggregate_news_score, _classify
from app.models.news_analysis import NewsAnalysis


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


class _FakeDecisionRepo:
    def add(self, decision):
        raise AssertionError("persist=False iken add() çağrılmamalı")


@pytest.fixture
def engine():
    return DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())


def _news(sentiment_score, confidence, news_id="n"):
    return NewsAnalysis(
        news_id=news_id,
        asset="TEST",
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=0.5,
        event_type="other",
        reasoning="r",
        model_used="gpt-5.6-luna",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "score,expected",
    [
        (50, "BUY"),
        (40, "BUY"),
        (39.9, "WEAK_BUY"),
        (15, "WEAK_BUY"),
        (14.9, "HOLD"),
        (0, "HOLD"),
        (-14.9, "HOLD"),
        (-15, "WEAK_SELL"),
        (-39.9, "WEAK_SELL"),
        (-40, "SELL"),
        (-50, "SELL"),
    ],
)
def test_classify_thresholds(score, expected):
    assert _classify(score, DEFAULT_THRESHOLDS) == expected


def test_decide_raises_when_no_scores_available(engine):
    with pytest.raises(ValueError):
        engine.decide(asset="TEST", persist=False)


def test_decide_normalizes_weight_when_only_technical_available(engine):
    decision = engine.decide(asset="TEST", technical_score=50.0, technical_confidence=0.8, persist=False)
    assert decision.final_score == 50.0
    assert decision.decision == "BUY"
    # completeness = technical_weight(.5) / toplam ağırlık(1.0) = 0.5
    assert decision.confidence == pytest.approx(0.8 * 0.5 * 100, rel=1e-6)


def test_decide_combines_available_scores_by_weight(engine):
    decision = engine.decide(
        asset="TEST",
        technical_score=100.0,
        news_score=-100.0,
        macro_score=0.0,
        technical_confidence=1.0,
        persist=False,
    )
    # 100*.5 + -100*.3 + 0*.2 = 50 - 30 = 20
    assert decision.final_score == pytest.approx(20.0)
    assert decision.decision == "WEAK_BUY"


def test_decide_renormalizes_when_technical_score_is_none(engine):
    # HATA 5B1 permanent test plan, madde R: TechnicalAnalysisEngine
    # `technical_score=None` üretebilir (7 component'in tamamı unavailable
    # olduğunda, bkz. scoring.py). `DecisionEngine.decide()`'ın MEVCUT
    # contract'ı (`available = {k:v for k,v ... if v is not None}`) bunu
    # zaten doğru ele alıyor -- bu yalnız o davranışı bir regresyon testiyle
    # kilitliyor: technical=None + news/macro mevcut -> crash YOK, kalan
    # ağırlıklar üzerinden renormalize edilmiş bir karar üretilir.
    decision = engine.decide(
        asset="TEST",
        technical_score=None,
        news_score=-100.0,
        macro_score=0.0,
        persist=False,
    )
    # news(.3)+macro(.2) = .5 toplam ağırlık -- yalnız bunlar üzerinden:
    # (-100*.3 + 0*.2) / .5 = -60
    assert decision.final_score == pytest.approx(-60.0)
    assert decision.technical_score is None
    assert decision.decision == "SELL"


def test_decide_missing_technical_channel_does_not_zero_out_confidence(engine):
    # HATA 5B1 CONFIDENCE COMMIT BLOCKER: `TechnicalAnalysisEngine`,
    # `technical_score=None` ürettiğinde `confidence=0.0` da döner (bkz.
    # models/technical_analysis.py) -- bu "üretilemeyen bir skora güven yok"
    # demektir, `decide()`'ın bunu DOĞRUDAN `base_confidence` yapıp overall
    # confidence'ı YAPAY olarak sıfırlaması YANLIŞTIR. technical kanalı
    # gerçekten unavailable'ken `technical_confidence` (0.0 dahil) HİÇ
    # kullanılmamalı -- teknik hiç verilmediğinde kullanılan AYNI nötr
    # varsayılana (0.6) düşülmeli.
    decision = engine.decide(
        asset="TEST",
        technical_score=None,
        technical_confidence=0.0,  # decide_for_asset() production'da TAM BÖYLE geçirir
        news_score=60.0,
        macro_score=40.0,
        persist=False,
    )
    # available = news(.3)+macro(.2) = .5 -- (60*.3 + 40*.2)/.5 = (18+8)/.5 = 52.0
    assert decision.final_score == pytest.approx(52.0)
    assert decision.decision == "BUY"
    # base_confidence=0.6 (0.0 KULLANILMADI) * completeness(.5) * 100 = 30.0
    assert decision.confidence == pytest.approx(30.0)


def test_decide_available_zero_confidence_technical_channel_still_zeroes_confidence(engine):
    # KARŞIT durum: technical_score=0.0 GEÇERLİ bir skordur (kanal MEVCUT),
    # yalnızca o skora duyulan güven gerçekten sıfırdır -- bu durumda
    # `technical_confidence=0.0` HÂLÂ kullanılmalı (yapay bir 0.6'ya
    # YÜKSELTİLMEMELİ). Aynı news/macro girdileriyle yalnızca technical_score
    # None mü yoksa 0.0 mı olduğuna göre confidence NET olarak farklı çıkar.
    decision = engine.decide(
        asset="TEST",
        technical_score=0.0,
        technical_confidence=0.0,
        news_score=60.0,
        macro_score=40.0,
        persist=False,
    )
    # available = technical(.5)+news(.3)+macro(.2) = 1.0 -- (0*.5+60*.3+40*.2)/1.0 = 26.0
    assert decision.final_score == pytest.approx(26.0)
    assert decision.decision == "WEAK_BUY"
    # base_confidence=0.0 (GERÇEK ölçülmüş sıfır güven, KULLANILDI) * completeness(1.0) * 100 = 0.0
    assert decision.confidence == pytest.approx(0.0)


def test_decide_with_persist_false_does_not_call_repository(engine):
    # _FakeDecisionRepo.add() çağrılırsa AssertionError fırlatır — sessizce
    # tamamlanması persist=False'un gerçekten saygı gördüğünü kanıtlar.
    engine.decide(asset="TEST", technical_score=10.0, persist=False)


def test_aggregate_news_score_returns_none_when_no_analyses():
    assert _aggregate_news_score([]) is None


def test_aggregate_news_score_weights_by_confidence():
    analyses = [_news(sentiment_score=100.0, confidence=0.9), _news(sentiment_score=-100.0, confidence=0.1)]
    # (100*.9 + -100*.1) / (.9+.1) = (90 - 10) / 1.0 = 80
    assert _aggregate_news_score(analyses) == pytest.approx(80.0)


def test_aggregate_news_score_none_when_all_zero_confidence():
    analyses = [_news(sentiment_score=50.0, confidence=0.0)]
    assert _aggregate_news_score(analyses) is None


class _FakeTechnicalEngine:
    def analyze_with_id(self, symbol, persist=True):
        return SimpleNamespace(technical_score=100.0, confidence=1.0), "tech-id"


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeNewsRepo:
    def __init__(self, analyses):
        self._analyses = analyses

    def list_for_asset(self, asset, limit=10):
        return self._analyses


def test_decide_for_asset_includes_aggregated_news_score(engine):
    news_repo = _FakeNewsRepo([_news(sentiment_score=-100.0, confidence=1.0, news_id="n1")])

    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=news_repo,
        persist=False,
    )

    assert decision.news_score == -100.0
    assert decision.news_analysis_ids == ["n1"]
    # final_score = 100*.5 + -100*.3 = 50 - 30 = 20 (macro eksik, ağırlığı normalize edilmiyor çünkü
    # technical+news ağırlığı zaten toplamın .8'i, macro sadece katkı yapmıyor)
    assert decision.final_score == pytest.approx((100 * 0.50 + -100 * 0.30) / 0.80)


class _FakeTechnicalEngineUnavailableScore:
    def analyze_with_id(self, symbol, persist=True):
        # HATA 5B1: technical_score=None -> confidence=0.0 (production
        # analyze_with_id()'in GERÇEK davranışı, bkz. technical/engine.py).
        return SimpleNamespace(technical_score=None, confidence=0.0), "tech-id-unavailable"


def test_decide_for_asset_missing_technical_channel_does_not_zero_out_confidence(engine):
    # HATA 5B1 CONFIDENCE COMMIT BLOCKER, uçtan uca (decide_for_asset() ->
    # decide()) regresyon kilidi -- production'da `technical_confidence`
    # tam olarak `analysis.confidence` (0.0) olarak geçirilir.
    news_repo = _FakeNewsRepo([_news(sentiment_score=60.0, confidence=1.0, news_id="n1")])

    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngineUnavailableScore(),
        macro_repo=_FakeMacroRepo(),  # macro yok -- yalnızca news mevcut
        news_repo=news_repo,
        persist=False,
    )

    assert decision.technical_score is None
    assert decision.news_score == 60.0
    # available = news(.3) -- final_score = 60*.3/.3 = 60.0
    assert decision.final_score == pytest.approx(60.0)
    # base_confidence=0.6 (0.0 KULLANILMADI) * completeness(.3/1.0=.3) * 100 = 18.0
    assert decision.confidence == pytest.approx(18.0)


def test_decide_for_asset_news_score_none_when_no_analyses(engine):
    decision = engine.decide_for_asset(
        "TEST",
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo([]),
        persist=False,
    )

    assert decision.news_score is None
    assert decision.news_analysis_ids == []
