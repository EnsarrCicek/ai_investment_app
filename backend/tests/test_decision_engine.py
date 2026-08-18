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
