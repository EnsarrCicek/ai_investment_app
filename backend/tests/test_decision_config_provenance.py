"""HATA 17D — DecisionEngine config/threshold provenance & historical
reproducibility (HATA 17A bulgu #2'nin kapanışı, HATA 17 serisinin son
ticket'ı).

`final_score` zaten (weights+scores her zaman persist edildiği için)
reproducible'dı, ama `decision` LABEL'ı (threshold config'e bağımlı) mevcut
Firestore config'i OKUMADAN yeniden üretilemiyordu. Bu dosya, final_score/
decision/confidence/channel_completeness'ın TAMAMININ, yalnızca persisted
`AIDecision` alanlarından (hiçbir config repository/provider erişimi
OLMADAN) yeniden üretilebildiğini kilitler -- HATA 16D'nin macro provenance
testleriyle AYNI disiplin (bkz. test_macro_provenance.py).
"""

import re
from datetime import datetime, timezone

import pytest

from app.engines.decision.engine import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    _DIRECTION_BY_CLASSIFICATION,
    _classify,
    DecisionEngine,
    compute_decision_config_sha256,
)
from app.models.ai_decision import AIDecision

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class _FakeConfigRepo:
    def __init__(self, weights=None, thresholds=None):
        self._weights = dict(weights or DEFAULT_WEIGHTS)
        self._thresholds = dict(thresholds or DEFAULT_THRESHOLDS)

    def get_raw(self, key):
        if key == "decision_weights":
            return dict(self._weights)
        if key == "decision_thresholds":
            return dict(self._thresholds)
        return None


class _MutableConfigRepo:
    """HATA 17D madde 24: `weights`/`thresholds` çağıranın sonradan
    değiştirebileceği (mutasyona uğratabileceği) mutable öznitelikler --
    "CONFIG A ile persist et, sonra CONFIG B'ye mutasyona uğrat" senaryosunu
    simüle etmek için."""

    def __init__(self, weights, thresholds):
        self.weights = dict(weights)
        self.thresholds = dict(thresholds)

    def get_raw(self, key):
        if key == "decision_weights":
            return dict(self.weights)
        if key == "decision_thresholds":
            return dict(self.thresholds)
        return None


class _CapturingDecisionRepo:
    def __init__(self):
        self.added: list[AIDecision] = []

    def add(self, decision: AIDecision) -> str:
        self.added.append(decision)
        return f"doc-{len(self.added)}"


@pytest.fixture
def engine():
    return DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_CapturingDecisionRepo())


def _channel_dicts(decision: AIDecision):
    scores = {"technical": decision.technical_score, "news": decision.news_score, "macro": decision.macro_score}
    weights = {"technical": decision.technical_weight, "news": decision.news_weight, "macro": decision.macro_weight}
    return scores, weights


def _reproduce_final_score(decision: AIDecision) -> float:
    """Yalnızca persisted `AIDecision` alanlarından -- SystemConfigRepository,
    mevcut DecisionEngine config'i veya güncel upstream analiz erişimi YOK."""
    scores, weights = _channel_dicts(decision)
    available = {k: v for k, v in scores.items() if v is not None}
    available_weight = sum(weights[k] for k in available)
    return sum(scores[k] * weights[k] for k in available) / available_weight


def _reproduce_decision(decision: AIDecision) -> str:
    """Yalnızca persisted `final_score` + persisted `decision_thresholds`
    snapshot'ından -- bu, HATA 17A bulgu #2'nin birincil düzeltmesidir."""
    return _classify(_reproduce_final_score(decision), decision.decision_thresholds)


def _reproduce_confidence(decision: AIDecision) -> float:
    scores, weights = _channel_dicts(decision)
    available = {k: v for k, v in scores.items() if v is not None}
    available_weight = sum(weights[k] for k in available)
    final_direction = _DIRECTION_BY_CLASSIFICATION[_reproduce_decision(decision)]
    agreement = sum(
        weights[k]
        for k in available
        if _DIRECTION_BY_CLASSIFICATION[_classify(scores[k], decision.decision_thresholds)] == final_direction
    ) / available_weight
    return round(agreement * 100, 2)


def _reproduce_completeness(decision: AIDecision) -> float:
    scores, weights = _channel_dicts(decision)
    available = {k: v for k, v in scores.items() if v is not None}
    available_weight = sum(weights[k] for k in available)
    return round(available_weight / sum(weights.values()), 2)


# ---------------------------------------------------------------------------
# Threshold/config snapshot alanları
# ---------------------------------------------------------------------------


def test_decision_thresholds_snapshot_matches_resolved_config(engine):
    decision = engine.decide(asset="TEST", technical_score=32.0, persist=False)
    assert decision.decision_thresholds == DEFAULT_THRESHOLDS


def test_decision_config_sha256_is_valid_hex(engine):
    decision = engine.decide(asset="TEST", technical_score=32.0, persist=False)
    assert _SHA256_HEX_RE.fullmatch(decision.decision_config_sha256)


def test_weight_fields_are_configured_not_renormalized_technical_only(engine):
    # HATA 17D madde 5: teknik-only bir kararda bile persisted weight
    # alanları HALA orijinal configured `{0.5, 0.3, 0.2}` -- effective
    # (renormalized) 1.0 DEĞİL.
    decision = engine.decide(asset="TEST", technical_score=60.0, persist=False)
    assert decision.technical_weight == pytest.approx(0.50)
    assert decision.news_weight == pytest.approx(0.30)
    assert decision.macro_weight == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Reproduction -- yalnızca persisted alanlardan
# ---------------------------------------------------------------------------


def test_normal_three_channel_reproduction(engine):
    decision = engine.decide(asset="TEST", technical_score=60.0, news_score=20.0, macro_score=-20.0, persist=False)
    assert decision.final_score == pytest.approx(32.0)
    assert decision.decision == "WEAK_BUY"
    assert decision.confidence == pytest.approx(80.0)
    assert decision.channel_completeness == pytest.approx(1.0)

    assert _reproduce_final_score(decision) == pytest.approx(decision.final_score)
    assert _reproduce_decision(decision) == decision.decision
    assert _reproduce_confidence(decision) == pytest.approx(decision.confidence)
    assert _reproduce_completeness(decision) == pytest.approx(decision.channel_completeness)


def test_two_channel_reproduction(engine):
    decision = engine.decide(asset="TEST", technical_score=60.0, news_score=20.0, macro_score=None, persist=False)
    assert decision.final_score == pytest.approx(45.0)
    assert decision.decision == "BUY"
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(0.8)

    assert _reproduce_final_score(decision) == pytest.approx(decision.final_score)
    assert _reproduce_decision(decision) == decision.decision
    assert _reproduce_confidence(decision) == pytest.approx(decision.confidence)
    assert _reproduce_completeness(decision) == pytest.approx(decision.channel_completeness)


def test_technical_only_reproduction_renormalizes_from_full_configured_weights(engine):
    # Kritik: reproduction, persisted (FULL, renormalize-edilmemiş) configured
    # weight'lerden BAŞLAYIP kendisi renormalize etmeli -- zaten çökmüş bir
    # effective-1.0 weight'ten DEĞİL.
    decision = engine.decide(asset="TEST", technical_score=60.0, news_score=None, macro_score=None, persist=False)
    assert decision.final_score == pytest.approx(60.0)
    assert decision.decision == "BUY"
    assert decision.channel_completeness == pytest.approx(0.5)  # 0.5/1.0

    assert _reproduce_final_score(decision) == pytest.approx(decision.final_score)
    assert _reproduce_decision(decision) == decision.decision
    assert _reproduce_confidence(decision) == pytest.approx(decision.confidence)
    assert _reproduce_completeness(decision) == pytest.approx(decision.channel_completeness)


def test_genuine_zero_reproduction(engine):
    decision = engine.decide(asset="TEST", technical_score=0.0, news_score=0.0, macro_score=0.0, persist=False)
    assert decision.final_score == pytest.approx(0.0)
    assert decision.decision == "HOLD"

    assert _reproduce_final_score(decision) == pytest.approx(0.0)
    assert _reproduce_decision(decision) == "HOLD"
    assert _reproduce_confidence(decision) == pytest.approx(decision.confidence)
    assert _reproduce_completeness(decision) == pytest.approx(decision.channel_completeness)


def test_near_threshold_39_996_reproduction_protects_hata17b_and_hata17d(engine):
    # HATA 17B + HATA 17D birlikte: persisted final_score HAM (39.996) kalmalı,
    # decision WEAK_BUY kalmalı, threshold snapshot buy=40.0 içermeli, VE
    # reproduction da (yalnızca persisted kayıttan) WEAK_BUY üretmeli.
    decision = engine.decide(asset="TEST", technical_score=39.996, persist=False)
    assert decision.final_score == pytest.approx(39.996)
    assert decision.decision == "WEAK_BUY"
    assert decision.decision_thresholds["buy"] == pytest.approx(40.0)

    assert _reproduce_final_score(decision) == pytest.approx(39.996)
    assert _reproduce_decision(decision) == "WEAK_BUY"


# ---------------------------------------------------------------------------
# Hash sensitivity / stability
# ---------------------------------------------------------------------------


def test_threshold_change_changes_config_hash_and_may_change_score(engine):
    base_hash = compute_decision_config_sha256(DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)
    changed_thresholds = {**DEFAULT_THRESHOLDS, "buy": 30.0}  # test fixture only
    changed_hash = compute_decision_config_sha256(DEFAULT_WEIGHTS, changed_thresholds)
    assert base_hash != changed_hash

    # Doğal sonuç: aynı skor (35.0), farklı buy eşiğiyle farklı sınıflandırılır.
    repo_a = _FakeConfigRepo(thresholds=DEFAULT_THRESHOLDS)
    repo_b = _FakeConfigRepo(thresholds=changed_thresholds)
    decision_a = DecisionEngine(config_repo=repo_a, decision_repo=_CapturingDecisionRepo()).decide(
        asset="TEST", technical_score=35.0, persist=False
    )
    decision_b = DecisionEngine(config_repo=repo_b, decision_repo=_CapturingDecisionRepo()).decide(
        asset="TEST", technical_score=35.0, persist=False
    )
    assert decision_a.decision == "WEAK_BUY"
    assert decision_b.decision == "BUY"
    assert decision_a.decision_config_sha256 != decision_b.decision_config_sha256


def test_weight_change_changes_config_hash_and_may_change_score():
    base_hash = compute_decision_config_sha256(DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)
    changed_weights = {"technical": 0.80, "news": 0.10, "macro": 0.10}  # test fixture only
    changed_hash = compute_decision_config_sha256(changed_weights, DEFAULT_THRESHOLDS)
    assert base_hash != changed_hash

    repo_a = _FakeConfigRepo(weights=DEFAULT_WEIGHTS)
    repo_b = _FakeConfigRepo(weights=changed_weights)
    decision_a = DecisionEngine(config_repo=repo_a, decision_repo=_CapturingDecisionRepo()).decide(
        asset="TEST", technical_score=60.0, news_score=-40.0, macro_score=0.0, persist=False
    )
    decision_b = DecisionEngine(config_repo=repo_b, decision_repo=_CapturingDecisionRepo()).decide(
        asset="TEST", technical_score=60.0, news_score=-40.0, macro_score=0.0, persist=False
    )
    assert decision_a.final_score != pytest.approx(decision_b.final_score)
    assert decision_a.decision_config_sha256 != decision_b.decision_config_sha256


def test_config_hash_stable_across_dict_insertion_order():
    weights_a = {"technical": 0.5, "news": 0.3, "macro": 0.2}
    weights_b = {"macro": 0.2, "technical": 0.5, "news": 0.3}
    thresholds_a = {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}
    thresholds_b = {"sell": -40.0, "buy": 40.0, "weak_sell": -15.0, "weak_buy": 15.0}
    assert compute_decision_config_sha256(weights_a, thresholds_a) == compute_decision_config_sha256(
        weights_b, thresholds_b
    )


# ---------------------------------------------------------------------------
# Load-bearing invariant: mevcut config mutasyonu geçmiş kararı ETKİLEMEZ.
# ---------------------------------------------------------------------------


def test_current_config_mutation_does_not_affect_historical_reproduction():
    config_repo = _MutableConfigRepo(DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)  # CONFIG A
    decision_repo = _CapturingDecisionRepo()
    engine = DecisionEngine(config_repo=config_repo, decision_repo=decision_repo)

    decision = engine.decide(asset="TEST", technical_score=39.996, persist=True)
    assert decision.decision == "WEAK_BUY"
    assert len(decision_repo.added) == 1

    # CONFIG B: buy eşiği 39.996'nın ALTINA düşürülüyor + ağırlıklar
    # değişiyor -- reproduction CURRENT config'i OKUSAYDI artık BUY üretirdi.
    config_repo.thresholds = {"buy": 30.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}
    config_repo.weights = {"technical": 0.1, "news": 0.1, "macro": 0.8}

    # Reproduction yalnızca persisted `decision` nesnesini kullanır --
    # `config_repo`'ya HİÇ erişim yok.
    assert _reproduce_final_score(decision) == pytest.approx(39.996)
    assert _reproduce_decision(decision) == "WEAK_BUY"
    assert _reproduce_confidence(decision) == pytest.approx(decision.confidence)
    assert _reproduce_completeness(decision) == pytest.approx(decision.channel_completeness)


# ---------------------------------------------------------------------------
# None-vs-zero / stale-channel provenance regresyonu (HATA 17C ile birlikte)
# ---------------------------------------------------------------------------


def test_unavailable_channel_never_serialized_as_zero(engine):
    decision = engine.decide(asset="TEST", technical_score=60.0, news_score=None, macro_score=None, persist=False)
    assert decision.news_score is None
    assert decision.macro_score is None
    assert decision.news_analysis_ids == []
    assert decision.macro_snapshot_id is None


# ---------------------------------------------------------------------------
# Legacy compatibility / model validation
# ---------------------------------------------------------------------------


def test_legacy_decision_without_provenance_fields_deserializes_safely():
    legacy = AIDecision(
        asset="TEST",
        created_at=datetime.now(timezone.utc),
        technical_score=50.0,
        technical_weight=0.5,
        news_weight=0.3,
        macro_weight=0.2,
        final_score=25.0,
        decision="WEAK_BUY",
        confidence=100.0,
        decision_engine_version="1.1.0",
    )
    assert legacy.decision_thresholds is None
    assert legacy.decision_config_sha256 is None


def test_decision_config_sha256_rejects_malformed_string():
    with pytest.raises(ValueError):
        AIDecision(
            asset="TEST",
            created_at=datetime.now(timezone.utc),
            technical_score=50.0,
            technical_weight=0.5,
            news_weight=0.3,
            macro_weight=0.2,
            final_score=25.0,
            decision="WEAK_BUY",
            confidence=100.0,
            decision_engine_version="1.1.0",
            decision_config_sha256="not-a-valid-hash",
        )


def test_decision_config_sha256_accepts_none():
    decision = AIDecision(
        asset="TEST",
        created_at=datetime.now(timezone.utc),
        technical_score=50.0,
        technical_weight=0.5,
        news_weight=0.3,
        macro_weight=0.2,
        final_score=25.0,
        decision="WEAK_BUY",
        confidence=100.0,
        decision_engine_version="1.1.0",
        decision_config_sha256=None,
    )
    assert decision.decision_config_sha256 is None


# ---------------------------------------------------------------------------
# ENGINE_VERSION bump
# ---------------------------------------------------------------------------


def test_engine_version_bumped_for_corrected_methodology(engine):
    decision = engine.decide(asset="TEST", technical_score=32.0, persist=False)
    assert decision.decision_engine_version == "1.2.0"
