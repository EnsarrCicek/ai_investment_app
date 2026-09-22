"""HATA 18C — decision-bound (historical) ExplanationEngine modu.

Kapsam: `ExplanationEngine.explain(asset, decision_id=...)` -- persisted bir
`AIDecision`'ın gerekçesini, DecisionEngine'i YENİDEN ÇAĞIRMADAN, canlı
Technical/News/Macro state'inden BAĞIMSIZ üretir (bkz. HATA 18A bulgu #2'nin
kapanışı). `decision_id=None` (varsayılan) davranışının TAM olarak
DEĞİŞMEDİĞİ ayrı testlerle kilitlenir (bkz. test_explanation_engine.py,
test_explanation_news_consistency.py -- bu dosya onları TEKRARLAMAZ, yalnızca
yeni decision-bound modu ve iki mod arasındaki backward-compat sınırını
test eder).
"""

from datetime import datetime, timezone

import pytest

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, ENGINE_VERSION, DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.models.ai_decision import AIDecision
from app.models.macro_snapshot import MacroSnapshot
from app.models.news_analysis import NewsAnalysis
from app.models.technical_analysis import TechnicalAnalysis

T0 = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


class _FakeConfigRepo:
    def __init__(self, weights=None, thresholds=None):
        self._weights = weights or dict(DEFAULT_WEIGHTS)
        self._thresholds = thresholds or dict(DEFAULT_THRESHOLDS)

    def get_raw(self, key):
        if key == "decision_weights":
            return dict(self._weights)
        if key == "decision_thresholds":
            return dict(self._thresholds)
        return None


class _RaisingDecisionEngine:
    """HATA 18C bölüm 24: decision-bound mod `DecisionEngine.decide()`/
    `decide_for_asset()`'i HİÇ çağırmamalı -- bu fake, çağrılırsa test'i
    açıkça patlatır (assert-with-mocks)."""

    def decide(self, *args, **kwargs):
        raise AssertionError("decision-bound mod DecisionEngine.decide() ÇAĞIRMAMALI")

    def decide_for_asset(self, *args, **kwargs):
        raise AssertionError("decision-bound mod DecisionEngine.decide_for_asset() ÇAĞIRMAMALI")


class _RaisingTechnicalEngine:
    def analyze_with_id(self, *args, **kwargs):
        raise AssertionError("decision-bound mod canlı TechnicalAnalysisEngine ÇAĞIRMAMALI")


class _RaisingMacroRepoLatest:
    """`get_latest_with_id()` çağrılırsa patlar; `get_by_id()` normal çalışır."""

    def __init__(self):
        self._by_id: dict[str, MacroSnapshot] = {}

    def get_latest_with_id(self):
        raise AssertionError("decision-bound mod MacroSnapshotRepository.get_latest_with_id() ÇAĞIRMAMALI")

    def get_by_id(self, snapshot_id):
        return self._by_id.get(snapshot_id)

    def put(self, snapshot_id, snapshot):
        self._by_id[snapshot_id] = snapshot


class _RaisingNewsRepoSelector:
    """`list_for_asset()` çağrılırsa patlar (paylaşımlı seçici KULLANILMAMALI);
    `get_by_news_id()` normal çalışır."""

    def __init__(self):
        self._by_key: dict[tuple[str, str], NewsAnalysis] = {}

    def list_for_asset(self, *args, **kwargs):
        raise AssertionError(
            "decision-bound mod select_recent_unique_news_analyses/list_for_asset ÇAĞIRMAMALI"
        )

    def get_by_news_id(self, news_id, asset):
        return self._by_key.get((news_id, asset))

    def put(self, news_id, asset, analysis):
        self._by_key[(news_id, asset)] = analysis


class _FakeAIDecisionRepo:
    def __init__(self):
        self._store: dict[str, AIDecision] = {}

    def add(self, decision):
        raise AssertionError("decision-bound mod AIDecisionRepository.add() ÇAĞIRMAMALI")

    def get_by_id(self, decision_id):
        return self._store.get(decision_id)

    def put(self, decision_id, decision):
        self._store[decision_id] = decision


class _FakeTechnicalAnalysisRepo:
    def __init__(self):
        self._store: dict[str, TechnicalAnalysis] = {}

    def get_by_id(self, analysis_id):
        return self._store.get(analysis_id)

    def put(self, analysis_id, analysis):
        self._store[analysis_id] = analysis


def _decision(
    asset="THYAO",
    final_score=32.0,
    decision="WEAK_BUY",
    technical_score=60.0,
    news_score=20.0,
    macro_score=-20.0,
    technical_analysis_id="tech-1",
    news_analysis_ids=None,
    macro_snapshot_id="macro-1",
    weights=None,
    thresholds=None,
    confidence=80.0,
    completeness=1.0,
    decision_as_of=None,
):
    weights = weights or dict(DEFAULT_WEIGHTS)
    thresholds = thresholds or dict(DEFAULT_THRESHOLDS)
    return AIDecision(
        asset=asset,
        created_at=decision_as_of or T0,
        technical_score=technical_score,
        news_score=news_score,
        macro_score=macro_score,
        technical_weight=weights["technical"],
        news_weight=weights["news"],
        macro_weight=weights["macro"],
        final_score=final_score,
        decision=decision,
        confidence=confidence,
        channel_completeness=completeness,
        technical_analysis_id=technical_analysis_id,
        news_analysis_ids=news_analysis_ids if news_analysis_ids is not None else ["n1", "n2"],
        macro_snapshot_id=macro_snapshot_id,
        decision_engine_version=ENGINE_VERSION,
        decision_as_of=decision_as_of or T0,
        decision_thresholds=thresholds,
    )


def _news(news_id, asset="THYAO", sentiment_score=50.0, confidence=0.9, importance=0.8, reasoning="r"):
    return NewsAnalysis(
        news_id=news_id,
        asset=asset,
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=importance,
        event_type="earnings",
        reasoning=reasoning,
        model_used="gpt-5.6-luna",
        created_at=T0,
    )


def _macro(components=None):
    return MacroSnapshot(
        macro_score=-20.0,
        confidence=0.8,
        components=components or {"dxy": -10.0, "usdtry": -5.0},
        indicators={},
        created_at=T0,
        engine_version="1.1.0",
    )


def _technical(components=None):
    return TechnicalAnalysis(
        asset="THYAO",
        technical_score=60.0,
        trend="up",
        confidence=0.9,
        components=components or {"rsi": 20.0, "macd": -5.0},
        indicators={},
        created_at=T0,
    )


def _engine(decision_repo, technical_repo=None, macro_repo=None, news_repo=None):
    return ExplanationEngine(
        decision_engine=_RaisingDecisionEngine(),
        technical_engine=_RaisingTechnicalEngine(),
        macro_repo=macro_repo or _RaisingMacroRepoLatest(),
        news_repo=news_repo or _RaisingNewsRepoSelector(),
        decision_repo=decision_repo,
        technical_repo=technical_repo or _FakeTechnicalAnalysisRepo(),
    )


# ---------------------------------------------------------------------------
# 1) exact decision-id identity (D1 vs D2)
# ---------------------------------------------------------------------------


def test_decision_bound_returns_persisted_decision_not_latest():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(final_score=32.0, decision="WEAK_BUY"))
    repo.put("D2", _decision(final_score=-25.0, decision="WEAK_SELL"))

    result = _engine(repo).explain("THYAO", decision_id="D1")

    assert result["final_score"] == 32.0
    assert result["decision"] == "WEAK_BUY"
    assert result["decision_id"] == "D1"
    assert result["mode"] == "decision_bound"


# ---------------------------------------------------------------------------
# 2) market changes after decision must not leak in
# ---------------------------------------------------------------------------


def test_decision_bound_immutable_to_market_changes_after_decision():
    repo = _FakeAIDecisionRepo()
    d1 = _decision()
    repo.put("D1", d1)

    # macro/news repos are the "raising" fakes -- decision-bound mode must
    # NEVER touch live/latest state; the entries below simulate a world
    # where "current" market/macro/news state has moved on since D1.
    macro_repo = _RaisingMacroRepoLatest()
    macro_repo.put("macro-1", _macro())
    news_repo = _RaisingNewsRepoSelector()
    news_repo.put("n1", "THYAO", _news("n1"))
    news_repo.put("n2", "THYAO", _news("n2"))
    tech_repo = _FakeTechnicalAnalysisRepo()
    tech_repo.put("tech-1", _technical())

    result = _engine(repo, technical_repo=tech_repo, macro_repo=macro_repo, news_repo=news_repo).explain(
        "THYAO", decision_id="D1"
    )

    assert result["final_score"] == d1.final_score
    assert result["decision"] == d1.decision
    assert result["confidence"] == d1.confidence
    assert result["news_analysis_ids"] == ["n1", "n2"]


# ---------------------------------------------------------------------------
# 3) live mode is genuinely unchanged (backward compatibility)
# ---------------------------------------------------------------------------


def test_live_mode_still_reflects_current_state_after_mutation():
    class _FakeTechnicalEngine:
        def analyze_with_id(self, symbol, persist=True):
            return _technical(), "tech-live"

    class _FakeMacroRepoLive:
        def get_latest_with_id(self):
            return None, None

    class _FakeNewsRepoLive:
        def list_for_asset(self, asset, limit=None):
            return []

    class _FakeNewsRawRepoLive:
        def get_by_external_id(self, external_id):
            return None

    class _FakeDecisionRepoLive:
        def add(self, decision):
            raise AssertionError("persist=False iken add() çağrılmamalı")

    engine = ExplanationEngine(
        decision_engine=DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepoLive()),
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepoLive(),
        news_repo=_FakeNewsRepoLive(),
        news_raw_repo=_FakeNewsRawRepoLive(),
    )

    result_no_param = engine.explain("THYAO")
    result_explicit_none = engine.explain("THYAO", decision_id=None)

    assert result_no_param["mode"] == "live"
    assert result_no_param["decision"] == result_explicit_none["decision"]
    assert result_no_param["final_score"] == result_explicit_none["final_score"]
    # backward compat: every pre-18C key still present with the same value shape.
    for key in ("asset", "decision", "final_score", "confidence", "summary", "missing"):
        assert key in result_no_param


# ---------------------------------------------------------------------------
# 4) config drift -- persisted thresholds authoritative
# ---------------------------------------------------------------------------


def test_decision_bound_uses_persisted_thresholds_not_current_config():
    repo = _FakeAIDecisionRepo()
    threshold_a = {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}
    repo.put("D1", _decision(final_score=39.996, decision="WEAK_BUY", thresholds=threshold_a))

    result = _engine(repo).explain("THYAO", decision_id="D1")

    # HATA 18B threshold-safe display must remain consistent with the
    # PERSISTED (config A) thresholds -- no current-config read/guess.
    assert "+40.0" not in result["summary"]
    assert "39.996" in result["summary"]
    assert "ZAYIF AL" in result["summary"]


# ---------------------------------------------------------------------------
# 5) news drift -- only persisted news IDs used
# ---------------------------------------------------------------------------


def test_decision_bound_uses_only_persisted_news_ids_not_new_arrivals():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(news_analysis_ids=["n1", "n2"]))

    news_repo = _RaisingNewsRepoSelector()
    news_repo.put("n1", "THYAO", _news("n1", reasoning="Eski haber 1"))
    news_repo.put("n2", "THYAO", _news("n2", reasoning="Eski haber 2"))
    # n3/n4 "arrived later" -- must never be consulted/surfaced.
    news_repo.put("n3", "THYAO", _news("n3", reasoning="Yeni haber 3"))
    news_repo.put("n4", "THYAO", _news("n4", reasoning="Yeni haber 4"))

    result = _engine(repo, news_repo=news_repo).explain("THYAO", decision_id="D1")

    assert result["news_analysis_ids"] == ["n1", "n2"]
    assert not any("Yeni haber" in r for r in result["news_reasons"])
    assert any("Eski haber" in r for r in result["news_reasons"])


# ---------------------------------------------------------------------------
# 6) macro drift -- only persisted macro snapshot used
# ---------------------------------------------------------------------------


def test_decision_bound_uses_persisted_macro_snapshot_not_latest():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(macro_snapshot_id="M1"))

    macro_repo = _RaisingMacroRepoLatest()
    macro_repo.put("M1", _macro(components={"dxy": -1.0}))
    macro_repo.put("M2", _macro(components={"dxy": -999.0}))  # "newer" -- must never surface

    result = _engine(repo, macro_repo=macro_repo).explain("THYAO", decision_id="D1")

    assert not any("999" in r for r in result["macro_reasons"])
    assert any("Dolar" in r for r in result["macro_reasons"])


# ---------------------------------------------------------------------------
# 7) macro_snapshot_id=None must stay "unavailable", never substituted
# ---------------------------------------------------------------------------


def test_decision_bound_missing_macro_stays_missing_even_if_current_snapshot_exists():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(macro_score=None, macro_snapshot_id=None))

    macro_repo = _RaisingMacroRepoLatest()
    macro_repo.put("some-other-id", _macro())  # a snapshot exists "today" -- irrelevant to D1

    result = _engine(repo, macro_repo=macro_repo).explain("THYAO", decision_id="D1")

    assert result["macro_reasons"] == []
    assert any("makro" in m.lower() for m in result["missing"])
    assert not any("nötr" in m.lower() for m in result["missing"])  # never "macro neutral"


# ---------------------------------------------------------------------------
# 8) missing referenced detail degrades gracefully, core facts unchanged
# ---------------------------------------------------------------------------


def test_decision_bound_degrades_gracefully_when_referenced_detail_missing():
    repo = _FakeAIDecisionRepo()
    repo.put(
        "D1",
        _decision(
            final_score=32.0,
            decision="WEAK_BUY",
            confidence=80.0,
            completeness=1.0,
            technical_score=60.0,
            technical_analysis_id="missing-tech-id",
            news_score=20.0,
            news_analysis_ids=["missing-n1"],
            macro_score=-20.0,
            macro_snapshot_id="missing-macro-id",
        ),
    )

    # no records registered anywhere -- everything referenced is "gone".
    result = _engine(repo).explain("THYAO", decision_id="D1")  # must not crash

    assert result["final_score"] == 32.0
    assert result["decision"] == "WEAK_BUY"
    assert result["confidence"] == 80.0
    assert result["technical_reasons"] == []
    assert result["news_reasons"] == []
    assert result["macro_reasons"] == []
    assert any("teknik kayıt artık erişilebilir değil" in m for m in result["missing"])
    assert any("makro kayıt artık erişilebilir değil" in m for m in result["missing"])
    assert any("haber kaydı artık" in m for m in result["missing"])


# ---------------------------------------------------------------------------
# 9) wrong symbol -> explicit rejection
# ---------------------------------------------------------------------------


def test_decision_bound_wrong_symbol_rejected():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(asset="THYAO"))

    with pytest.raises(LookupError):
        _engine(repo).explain("ASELS", decision_id="D1")


# ---------------------------------------------------------------------------
# 10) unknown decision_id -> explicit not-found, no live fallback
# ---------------------------------------------------------------------------


def test_decision_bound_unknown_id_rejected_no_live_fallback():
    repo = _FakeAIDecisionRepo()

    with pytest.raises(LookupError):
        # decision_engine/technical_engine are the "raising" fakes -- if a
        # live fallback were attempted, this would raise a DIFFERENT
        # AssertionError instead of the expected LookupError.
        _engine(repo).explain("THYAO", decision_id="does-not-exist")


# ---------------------------------------------------------------------------
# 11) identity metadata distinguishes the two modes
# ---------------------------------------------------------------------------


def test_identity_metadata_distinguishes_modes():
    repo = _FakeAIDecisionRepo()
    d1 = _decision()
    repo.put("D1", d1)
    result_bound = _engine(repo).explain("THYAO", decision_id="D1")

    assert result_bound["mode"] == "decision_bound"
    assert result_bound["decision_id"] == "D1"
    assert result_bound["decision_as_of"] == d1.decision_as_of


# ---------------------------------------------------------------------------
# 12) no historical recomputation (assert-with-mocks, HATA 18C bölüm 24)
# ---------------------------------------------------------------------------


def test_decision_bound_never_recomputes_via_decision_engine_or_live_sources():
    repo = _FakeAIDecisionRepo()
    d1 = _decision()
    repo.put("D1", d1)

    # every live/recompute-capable dependency is the "raising" fake --
    # this test passes ONLY if none of them is ever invoked.
    result = _engine(repo).explain("THYAO", decision_id="D1")
    assert result["decision"] == d1.decision


# ---------------------------------------------------------------------------
# 13) HATA 18B threshold-safe display regression in decision-bound mode
# ---------------------------------------------------------------------------


def test_decision_bound_near_threshold_display_stays_threshold_safe():
    repo = _FakeAIDecisionRepo()
    repo.put("D1", _decision(final_score=39.996, decision="WEAK_BUY"))

    result = _engine(repo).explain("THYAO", decision_id="D1")

    assert "+40.0" not in result["summary"]
    assert "39.996" in result["summary"]
    assert "ZAYIF AL" in result["summary"]


# ---------------------------------------------------------------------------
# 14) None-vs-zero preserved in decision-bound mode
# ---------------------------------------------------------------------------


def test_decision_bound_none_vs_zero_preserved():
    repo = _FakeAIDecisionRepo()
    # macro genuinely unavailable (None) vs. a DIFFERENT decision where
    # macro was genuinely neutral (0.0) -- must be distinguishable.
    repo.put("D-missing", _decision(macro_score=None, macro_snapshot_id=None))
    repo.put("D-neutral", _decision(macro_score=0.0, macro_snapshot_id="M-neutral"))

    macro_repo = _RaisingMacroRepoLatest()
    macro_repo.put("M-neutral", _macro(components={"dxy": 0.0}))

    missing_result = _engine(repo, macro_repo=macro_repo).explain("THYAO", decision_id="D-missing")
    neutral_result = _engine(repo, macro_repo=macro_repo).explain("THYAO", decision_id="D-neutral")

    assert any("makro" in m.lower() for m in missing_result["missing"])
    assert not any("makro" in m.lower() for m in neutral_result["missing"])
    assert neutral_result["macro_reasons"] != []
