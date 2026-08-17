import pytest

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DecisionEngine, _classify


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


class _FakeDecisionRepo:
    def add(self, decision):
        raise AssertionError("persist=False iken add() çağrılmamalı")


@pytest.fixture
def engine():
    return DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())


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
