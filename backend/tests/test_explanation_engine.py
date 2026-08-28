from datetime import datetime, timezone

from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.models.news_analysis import NewsAnalysis
from app.models.technical_analysis import TechnicalAnalysis


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


class _FakeDecisionRepo:
    def add(self, decision):
        raise AssertionError("persist=False iken add() çağrılmamalı")


class _FakeTechnicalEngine:
    def analyze_with_id(self, symbol, persist=True):
        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=60.0,
            trend="up",
            confidence=0.9,
            components={"rsi": 20.0, "macd": -5.0},
            indicators={},
            created_at=datetime.now(timezone.utc),
        )
        return analysis, "tech-id"


class _FakeTechnicalEngineUnavailableScore:
    """HATA 5B1 (27.08.2026): `technical_score=None` üretildiğinde (7
    component'in tamamı unavailable, son derece nadir bir durum) --
    `components` dict'i de PRODUCTION davranışıyla tutarlı şekilde
    unavailable component'leri OMIT eder (boş kalır)."""

    def analyze_with_id(self, symbol, persist=True):
        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=None,
            # HATA 5B1 FINAL PRE-COMMIT GATE (27.08.2026, madde 2): trend de
            # None -- "NEUTRAL" skorun hesaplandığı ama nötr olduğu anlamına
            # gelir, skor hiç üretilemediğinde bu UYDURULMAZ.
            trend=None,
            confidence=0.0,
            components={},
            indicators={},
            created_at=datetime.now(timezone.utc),
        )
        return analysis, "tech-id-unavailable"


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeNewsRepo:
    def __init__(self, analyses):
        self._analyses = analyses

    def list_for_asset(self, asset, limit=10):
        return self._analyses


def _news(sentiment_score, confidence, importance, reasoning, news_id="n"):
    return NewsAnalysis(
        news_id=news_id,
        asset="TEST",
        sentiment_score=sentiment_score,
        confidence=confidence,
        importance=importance,
        event_type="earnings",
        reasoning=reasoning,
        model_used="gpt-5.6-luna",
        created_at=datetime.now(timezone.utc),
    )


def _engine(news_analyses):
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    return ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngine(),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo(news_analyses),
    )


def test_explain_reports_missing_news_when_no_analyses():
    result = _engine([]).explain("TEST")

    assert any("haber" in m.lower() for m in result["missing"])
    assert result["news_reasons"] == []


def test_explain_includes_news_reasons_when_analyses_exist():
    news = [_news(80.0, 0.9, 0.9, "Kâr beklentinin üzerinde geldi.")]
    result = _engine(news).explain("TEST")

    assert not any("haber" in m.lower() for m in result["missing"])
    assert len(result["news_reasons"]) == 1
    assert "Kâr beklentinin üzerinde geldi." in result["news_reasons"][0]


def test_explain_still_reports_missing_macro():
    result = _engine([]).explain("TEST")

    assert any("makro" in m.lower() for m in result["missing"])
    assert result["macro_reasons"] == []


def test_explain_does_not_crash_when_technical_score_is_unavailable():
    # HATA 5B1 madde U: `technical_score=None` + boş `components` dict --
    # `_top_reasons()`'ın `abs(kv[1])` çağrısı (component'ler unavailable
    # olduğunda OMIT edildiği için) bir `None`/NaN sentinel'e HİÇ rastlamaz;
    # `DecisionEngine.decide()` de `technical_score=None`'ı zaten doğru
    # dışlayıp kalan (haber) ağırlığı üzerinden renormalize eder. Bu, uçtan
    # uca (ExplanationEngine -> DecisionEngine) crash olmadığını kilitler.
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    engine = ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngineUnavailableScore(),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo([_news(60.0, 0.8, 0.7, "Güçlü bilanço açıklandı.")]),
    )

    result = engine.explain("TEST")  # exception atmamalı

    assert result["technical_reasons"] == []
    assert result["decision"] in {"BUY", "WEAK_BUY", "HOLD", "WEAK_SELL", "SELL"}
