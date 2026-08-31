from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engines.decision.engine import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    DecisionEngine,
    _aggregate_news_score,
    _classify,
    resolve_decision_thresholds,
    resolve_decision_weights,
)
from app.models.news_analysis import NewsAnalysis

NAN = float("nan")
INF = float("inf")
NEG_INF = float("-inf")


class _FakeConfigRepo:
    # HATA 5C3B: production path artık `get()` (auto-seed + sessiz partial-
    # merge, HATA 5B2C'nin kök nedeni) DEĞİL `get_raw()` kullanıyor --
    # gerçek production'ı simüle etmek için geçerli/tam config'ler döner.
    def get_raw(self, key):
        if key == "decision_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


class _NoSilentFallbackConfigRepo:
    """HATA 5C3B madde 22: `get()` çağrılırsa test FAIL etsin -- production
    Decision path'inin `decision_weights`/`decision_thresholds` için ARTIK
    `get()` kullanmadığını structurally kilitler."""

    def get(self, key, defaults):
        raise AssertionError(f"get({key!r}, ...) çağrıldı -- production path artık get_raw() kullanmalı")

    def get_raw(self, key):
        if key == "decision_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


class _MissingDecisionWeightsConfigRepo:
    def get_raw(self, key):
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None  # decision_weights dokümanı TAMAMEN yok


class _MissingDecisionThresholdsConfigRepo:
    def get_raw(self, key):
        if key == "decision_weights":
            return dict(DEFAULT_WEIGHTS)
        return None  # decision_thresholds dokümanı TAMAMEN yok


class _ZeroTechnicalWeightConfigRepo:
    """HATA 5C3B madde 8/18: config GEÇERLİ (toplam>0, hepsi non-negative)
    ama `technical=0` -- yalnız technical score mevcutken available_weight=0
    olur."""

    def get_raw(self, key):
        if key == "decision_weights":
            return {"technical": 0.0, "news": 0.7, "macro": 0.3}
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


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


# ---------------------------------------------------------------------------
# _classify() threshold parametrized test -- DEĞİŞMEDİ, tek threshold source.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HATA 5C3B — decision_weights strict resolver.
# ---------------------------------------------------------------------------


def test_resolve_decision_weights_missing_document_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights(None)


def test_resolve_decision_weights_partial_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": 0.5, "news": 0.3})  # macro eksik


def test_resolve_decision_weights_extra_key_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": 0.5, "news": 0.3, "macro": 0.2, "extra": 0.1})


@pytest.mark.parametrize("bad_value", [True, False])
def test_resolve_decision_weights_bool_fails_fast(bad_value):
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": bad_value, "news": 0.3, "macro": 0.2})


def test_resolve_decision_weights_string_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": "0.5", "news": 0.3, "macro": 0.2})


@pytest.mark.parametrize("bad_value", [NAN, INF, NEG_INF])
def test_resolve_decision_weights_non_finite_fails_fast(bad_value):
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": bad_value, "news": 0.3, "macro": 0.2})


def test_resolve_decision_weights_negative_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": -0.1, "news": 0.3, "macro": 0.2})


def test_resolve_decision_weights_all_zero_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_weights({"technical": 0.0, "news": 0.0, "macro": 0.0})


def test_resolve_decision_weights_individual_zero_with_total_positive_accepted():
    resolved = resolve_decision_weights({"technical": 0.0, "news": 0.7, "macro": 0.3})
    assert resolved == {"technical": 0.0, "news": 0.7, "macro": 0.3}


def test_resolve_decision_weights_valid_production_style_config_accepted():
    resolved = resolve_decision_weights({"technical": 0.5, "news": 0.3, "macro": 0.2})
    assert resolved == {"technical": 0.5, "news": 0.3, "macro": 0.2}


# ---------------------------------------------------------------------------
# HATA 5C3B — decision_thresholds strict resolver.
# ---------------------------------------------------------------------------


def test_resolve_decision_thresholds_missing_document_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_thresholds(None)


def test_resolve_decision_thresholds_partial_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_thresholds({"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0})  # sell eksik


def test_resolve_decision_thresholds_extra_key_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_thresholds(
            {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0, "extra": 1.0}
        )


@pytest.mark.parametrize("bad_value", [True, False])
def test_resolve_decision_thresholds_bool_fails_fast(bad_value):
    with pytest.raises(ValueError):
        resolve_decision_thresholds({"buy": bad_value, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0})


def test_resolve_decision_thresholds_string_fails_fast():
    with pytest.raises(ValueError):
        resolve_decision_thresholds({"buy": "40.0", "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0})


@pytest.mark.parametrize("bad_value", [NAN, INF, NEG_INF])
def test_resolve_decision_thresholds_non_finite_fails_fast(bad_value):
    with pytest.raises(ValueError):
        resolve_decision_thresholds({"buy": bad_value, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0})


@pytest.mark.parametrize(
    "thresholds",
    [
        {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -15.0},  # sell >= weak_sell
        {"buy": 40.0, "weak_buy": -15.0, "weak_sell": -15.0, "sell": -40.0},  # weak_sell >= weak_buy
        {"buy": 15.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0},  # weak_buy >= buy
    ],
)
def test_resolve_decision_thresholds_invalid_ordering_fails_fast(thresholds):
    with pytest.raises(ValueError):
        resolve_decision_thresholds(thresholds)


def test_resolve_decision_thresholds_valid_production_style_config_accepted():
    resolved = resolve_decision_thresholds({"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0})
    assert resolved == {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}


def test_resolve_decision_thresholds_does_not_enforce_range_constraint():
    # HATA 5C3B madde 4/20: [-100,100] gibi YENİ bir range invariant'ı
    # KASITLI OLARAK eklenmedi -- sıralama sağlandığı sürece kabul edilir.
    resolved = resolve_decision_thresholds({"buy": 400.0, "weak_buy": 150.0, "weak_sell": -150.0, "sell": -400.0})
    assert resolved == {"buy": 400.0, "weak_buy": 150.0, "weak_sell": -150.0, "sell": -400.0}


# ---------------------------------------------------------------------------
# HATA 5C3B — production path artık get() kullanmıyor (structural lock).
# ---------------------------------------------------------------------------


def test_decide_never_calls_get_only_get_raw():
    engine = DecisionEngine(config_repo=_NoSilentFallbackConfigRepo(), decision_repo=_FakeDecisionRepo())
    # `_NoSilentFallbackConfigRepo.get()` çağrılırsa AssertionError fırlatır --
    # sessizce tamamlanması production path'in gerçekten get_raw() kullandığını
    # kanıtlar.
    engine.decide(asset="TEST", technical_score=50.0, persist=False)


def test_decide_missing_decision_weights_document_fails_fast_with_correct_reason():
    engine = DecisionEngine(config_repo=_MissingDecisionWeightsConfigRepo(), decision_repo=_FakeDecisionRepo())
    with pytest.raises(ValueError) as exc_info:
        engine.decide(asset="TEST", technical_score=50.0, news_score=10.0, macro_score=5.0, persist=False)
    assert "decision_weights" in str(exc_info.value)


def test_decide_missing_decision_thresholds_document_fails_fast_with_correct_reason():
    engine = DecisionEngine(config_repo=_MissingDecisionThresholdsConfigRepo(), decision_repo=_FakeDecisionRepo())
    with pytest.raises(ValueError) as exc_info:
        engine.decide(asset="TEST", technical_score=50.0, news_score=10.0, macro_score=5.0, persist=False)
    assert "decision_thresholds" in str(exc_info.value)


# ---------------------------------------------------------------------------
# HATA 5C3B madde 8/18 — zero positive available weight guard.
# ---------------------------------------------------------------------------


def test_decide_zero_positive_available_weight_raises_explicit_error_not_zero_division():
    engine = DecisionEngine(config_repo=_ZeroTechnicalWeightConfigRepo(), decision_repo=_FakeDecisionRepo())
    with pytest.raises(ValueError) as exc_info:
        engine.decide(asset="TEST", technical_score=80.0, persist=False)  # yalnız technical (weight=0) mevcut
    assert "NO_POSITIVE_WEIGHT_AVAILABLE" in str(exc_info.value)


def test_decide_zero_positive_available_weight_does_not_raise_zero_division_error():
    engine = DecisionEngine(config_repo=_ZeroTechnicalWeightConfigRepo(), decision_repo=_FakeDecisionRepo())
    try:
        engine.decide(asset="TEST", technical_score=80.0, persist=False)
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError fırlatıldı -- explicit ValueError bekleniyordu")
    except ValueError:
        pass


def test_decide_raises_when_no_scores_available(engine):
    with pytest.raises(ValueError):
        engine.decide(asset="TEST", persist=False)


def test_decide_with_persist_false_does_not_call_repository(engine):
    engine.decide(asset="TEST", technical_score=10.0, persist=False)


# ---------------------------------------------------------------------------
# HATA 5C3B madde 23 — technical_confidence artık DecisionEngine input'u
# DEĞİL: parametre signature'dan TAMAMEN kaldırıldı, source seviyesinde
# imkânsız (TypeError).
# ---------------------------------------------------------------------------


def test_decide_no_longer_accepts_technical_confidence_kwarg(engine):
    with pytest.raises(TypeError):
        engine.decide(asset="TEST", technical_score=50.0, technical_confidence=0.73, persist=False)


# ---------------------------------------------------------------------------
# HATA 5C3B madde 7/24 — final_score/classification regresyon (confidence
# HARİÇ, formül DEĞİŞMEDİ).
# ---------------------------------------------------------------------------


def test_decide_normalizes_weight_when_only_technical_available(engine):
    decision = engine.decide(asset="TEST", technical_score=50.0, persist=False)
    assert decision.final_score == 50.0
    assert decision.decision == "BUY"
    assert decision.channel_completeness == pytest.approx(0.5)  # .5/1.0


def test_decide_combines_available_scores_by_weight(engine):
    decision = engine.decide(asset="TEST", technical_score=100.0, news_score=-100.0, macro_score=0.0, persist=False)
    # 100*.5 + -100*.3 + 0*.2 = 50 - 30 = 20
    assert decision.final_score == pytest.approx(20.0)
    assert decision.decision == "WEAK_BUY"
    assert decision.channel_completeness == pytest.approx(1.0)


def test_decide_renormalizes_when_technical_score_is_none(engine):
    # HATA 5B1: `technical_score=None` -- kalan ağırlıklar üzerinden
    # renormalize edilmiş bir karar üretilir, crash YOK.
    decision = engine.decide(asset="TEST", technical_score=None, news_score=-100.0, macro_score=0.0, persist=False)
    # news(.3)+macro(.2) = .5 -- (-100*.3 + 0*.2) / .5 = -60
    assert decision.final_score == pytest.approx(-60.0)
    assert decision.technical_score is None
    assert decision.decision == "SELL"
    assert decision.channel_completeness == pytest.approx(0.5)


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


# ---------------------------------------------------------------------------
# HATA 5C3B madde 17 — valid zero score: AVAILABLE, missing İLE
# KARIŞTIRILMAZ, direction NEUTRAL.
# ---------------------------------------------------------------------------


def test_decide_valid_zero_scores_are_available_not_missing(engine):
    decision = engine.decide(asset="TEST", technical_score=0.0, news_score=0.0, macro_score=0.0, persist=False)
    assert decision.technical_score == 0.0  # None DEĞİL
    assert decision.decision == "HOLD"  # _classify(0, ...) == HOLD
    # Üç kanal da NEUTRAL yönde final (NEUTRAL) ile eşleşir -- tam mutabakat.
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(1.0)


def test_decide_missing_technical_channel_excludes_it_from_agreement_and_coverage(engine):
    # HATA 5C3B: technical=None -- agreement'tan TAMAMEN dışlanır (eski 0.6
    # fallback YOK), coverage düşer. news(+60)/macro(+40) ikisi de final
    # (BUY) ile aynı yönde -- tam mutabakat, ama eksik kanal nedeniyle
    # coverage < 1.
    decision = engine.decide(asset="TEST", technical_score=None, news_score=60.0, macro_score=40.0, persist=False)
    assert decision.final_score == pytest.approx(52.0)
    assert decision.decision == "BUY"
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(0.5)


def test_decide_available_zero_technical_channel_participates_as_neutral_vote(engine):
    # KARŞIT durum: technical_score=0.0 GEÇERLİ bir skordur (kanal MEVCUT) --
    # agreement'a NEUTRAL bir oy olarak katılır (final WEAK_BUY/POSITIVE ile
    # eşleşmez), coverage TAM kalır. Aynı news/macro ile yalnızca technical_
    # score None mı 0.0 mı olduğuna göre confidence VE coverage NET olarak
    # farklı çıkar.
    decision = engine.decide(asset="TEST", technical_score=0.0, news_score=60.0, macro_score=40.0, persist=False)
    assert decision.final_score == pytest.approx(26.0)
    assert decision.decision == "WEAK_BUY"
    # yalnız news+macro (ağırlık .3+.2=.5) final ile eşleşiyor / toplam mevcut ağırlık 1.0
    assert decision.confidence == pytest.approx(50.0)
    assert decision.channel_completeness == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# HATA 5C3B madde 16 — permanent decision fixtures (production-style
# weights/thresholds, gerçek `decide()` ile hesaplandı).
# ---------------------------------------------------------------------------


def test_decision_fixture_a_all_positive_full_agreement(engine):
    decision = engine.decide(asset="TEST", technical_score=80.0, news_score=60.0, macro_score=20.0, persist=False)
    # NOT: ticket taslağındaki "final=52" aritmetik olarak yanlıştı --
    # 80*.5+60*.3+20*.2=62.0 (production formülüyle doğrulandı, elle
    # varsayılmadı). confidence/coverage ticket'ın beklentisiyle eşleşiyor.
    assert decision.final_score == pytest.approx(62.0)
    assert decision.decision == "BUY"
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(1.0)


def test_decision_fixture_b_technical_vs_news_conflict_macro_missing(engine):
    decision = engine.decide(asset="TEST", technical_score=80.0, news_score=-80.0, macro_score=None, persist=False)
    assert decision.final_score == pytest.approx(20.0)
    assert decision.decision == "WEAK_BUY"
    assert decision.confidence == pytest.approx(62.5)  # .5/.8
    assert decision.channel_completeness == pytest.approx(0.8)


def test_decision_fixture_c_technical_vs_news_conflict_macro_valid_zero(engine):
    decision = engine.decide(asset="TEST", technical_score=80.0, news_score=-80.0, macro_score=0.0, persist=False)
    assert decision.final_score == pytest.approx(16.0)
    assert decision.decision == "WEAK_BUY"
    assert decision.confidence == pytest.approx(50.0)  # .5/1.0 -- yalnız technical eşleşiyor
    assert decision.channel_completeness == pytest.approx(1.0)


def test_decision_fixture_d_only_technical_available(engine):
    decision = engine.decide(asset="TEST", technical_score=80.0, persist=False)
    assert decision.final_score == pytest.approx(80.0)
    assert decision.decision == "BUY"
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(0.5)


def test_decision_fixture_e_only_macro_available(engine):
    decision = engine.decide(asset="TEST", macro_score=-80.0, persist=False)
    assert decision.final_score == pytest.approx(-80.0)
    assert decision.decision == "SELL"
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(0.2)


def test_decision_fixture_f_neutral_final_only_neutral_channel_matches(engine):
    decision = engine.decide(asset="TEST", technical_score=20.0, news_score=-20.0, macro_score=0.0, persist=False)
    assert decision.final_score == pytest.approx(4.0)
    assert decision.decision == "HOLD"
    # technical POSITIVE, news NEGATIVE, macro NEUTRAL -- yalnız macro (.2) final (NEUTRAL) ile eşleşir.
    assert decision.confidence == pytest.approx(20.0)
    assert decision.channel_completeness == pytest.approx(1.0)


def test_decision_fixture_g_all_neutral_full_agreement(engine):
    decision = engine.decide(asset="TEST", technical_score=10.0, news_score=10.0, macro_score=10.0, persist=False)
    assert decision.final_score == pytest.approx(10.0)
    assert decision.decision == "HOLD"
    # üç kanal da NEUTRAL (final de NEUTRAL) -- tam mutabakat.
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _aggregate_news_score -- DEĞİŞMEDİ.
# ---------------------------------------------------------------------------


def test_aggregate_news_score_returns_none_when_no_analyses():
    assert _aggregate_news_score([]) is None


def test_aggregate_news_score_weights_by_confidence():
    analyses = [_news(sentiment_score=100.0, confidence=0.9), _news(sentiment_score=-100.0, confidence=0.1)]
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


class _FakeTechnicalEngineUnavailableScore:
    def analyze_with_id(self, symbol, persist=True):
        return SimpleNamespace(technical_score=None, confidence=None), "tech-id-unavailable"


def test_decide_for_asset_missing_technical_channel_excludes_it(engine):
    # HATA 5C3B uçtan uca (decide_for_asset() -> decide()) regresyon kilidi --
    # technical_score=None -- ve `analysis.confidence`/None'ı Decision'a
    # AKTARILMIYOR (parametre signature'dan kalktı).
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
    assert decision.final_score == pytest.approx(60.0)
    assert decision.decision == "BUY"
    # yalnız news (.3) mevcut, final ile aynı yönde -- tam mutabakat, düşük coverage.
    assert decision.confidence == pytest.approx(100.0)
    assert decision.channel_completeness == pytest.approx(0.3)
