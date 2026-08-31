from datetime import datetime, timezone

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.models.news_analysis import NewsAnalysis
from app.models.technical_analysis import TechnicalAnalysis


class _FakeConfigRepo:
    # HATA 5C3B: production path artık `get()` DEĞİL `get_raw()` kullanıyor
    # (`decision_weights`/`decision_thresholds` dahil) -- gerçek production'ı
    # simüle etmek için geçerli/tam config'ler döner.
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


class _FakeTechnicalEngineWithScore:
    """HATA 5C-UI3 (31.08.2026): `summary`'nin gerçek `DecisionEngine` 1.1.0
    formülünden ürettiği confidence/channel_completeness değerlerini elle
    varsaymadan (gerçek `_classify()`/agreement hesabıyla) test edebilmek için
    `technical_score` parametrik hale getirildi."""

    def __init__(self, technical_score):
        self._technical_score = technical_score

    def analyze_with_id(self, symbol, persist=True):
        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=self._technical_score,
            trend="up",
            confidence=0.9,
            components={"rsi": 20.0, "macd": -5.0},
            indicators={},
            created_at=datetime.now(timezone.utc),
        )
        return analysis, "tech-id"


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


def test_explain_summary_uses_sinyal_mutabakati_and_veri_kapsami_not_generic_guven():
    """HATA 5C-UI3 (31.08.2026): eski "güven: %XX" ifadesi, DecisionEngine
    1.1.0'ın iki AYRI metriğini (Sinyal Mutabakatı / Veri Kapsamı) tek bir
    generic kelimeye sıkıştırıyordu -- artık ikisi de summary'de ayrı ayrı
    görünmeli.

    Fixture (gerçek `decide()` formülüyle DOĞRULANDI, elle varsayılmadı):
    technical=+80, news=-80, macro=YOK (yalnızca 2 kanal mevcut).
      available_weight = .5+.3 = .8
      final_score = (80*.5 + (-80)*.3) / .8 = (40-24)/.8 = 20.0 -> WEAK_BUY (POSITIVE)
      technical(+80) -> BUY (POSITIVE, final ile AYNI) -> dahil (.5)
      news(-80)      -> SELL (NEGATIVE, final ile FARKLI) -> hariç
      agreement = .5 / .8 = .625 -> confidence = 62.5
      channel_completeness = .8 / 1.0 = .8 -> "%80"

    HATA 5C-UI4 (31.08.2026): önceki turda `f"%{62.5:.0f}"` Python'un
    round-half-to-even (banker's rounding) davranışı yüzünden "%62" üretmişti
    (62 çift, 63 tek) -- Flutter/Dart'ın `toStringAsFixed(0)`'ı ise 62.5 için
    "63" üretir (round-half-away-from-zero). `format_percent_value()` artık
    `Decimal`/`ROUND_HALF_UP` ile Flutter'la PRESENTATION-EŞDEĞER "%63"
    üretir -- bu değişiklik STORED `decision.confidence` değerini (hâlâ tam
    olarak 62.5) DEĞİŞTİRMEZ, yalnızca gösterim string'ini düzeltir.
    """
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    engine = ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngineWithScore(80.0),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo([_news(-80.0, 0.9, 0.9, "Beklenenden kötü sonuç açıklandı.")]),
    )

    result = engine.explain("TEST")

    assert result["confidence"] == 62.5
    assert "sinyal mutabakatı: %63" in result["summary"].lower()
    assert "veri kapsamı: %80" in result["summary"].lower()
    assert "güven:" not in result["summary"].lower()


def test_explain_summary_only_one_channel_shows_high_agreement_and_low_coverage_together():
    """HATA 5C-UI3 madde 7 -- 5C'nin ana semantic invariant'ı: yalnızca TEK
    kanal mevcutken Sinyal Mutabakatı yüksek/tam olsa bile Veri Kapsamı bunu
    YANSITMAZ -- ikisi AYNI cümlede birlikte görünmeli, tek başına "%100
    sinyal mutabakatı" yanıltıcı bırakılmamalı.

    Fixture (gerçek `decide()` formülüyle DOĞRULANDI): yalnızca technical=+100
    mevcut (news=[] -> None, macro=YOK).
      available_weight = .5 (yalnızca technical)
      final_score = 100*.5/.5 = 100.0 -> BUY (POSITIVE)
      technical(+100) -> BUY (POSITIVE, final ile AYNI) -> agreement = .5/.5 = 1.0 -> confidence=100.0 -> "%100"
      channel_completeness = .5 / 1.0 = .5 -> "%50"
    """
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    engine = ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngineWithScore(100.0),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo([]),
    )

    result = engine.explain("TEST")

    assert result["confidence"] == 100.0
    summary_lower = result["summary"].lower()
    assert "sinyal mutabakatı: %100" in summary_lower
    assert "veri kapsamı: %50" in summary_lower
