"""HATA 18B — threshold-safe, adaptif-hassasiyetli `final_score` sunumu.

HATA 18A bulgu #1'in düzeltmesi: `ExplanationEngine`/`fcm_sender.py`'nin
sabit `:+.1f` formatı, eşiğe yeterince yakın bir skoru (ör. 39.996/WEAK_BUY,
BUY eşiği 40.0) yanlış katmana ("+40.0") yuvarlayabiliyordu. Bu dosya:

1. `format_decision_score()`'un kendisini (birim testler) -- yük-taşıyan
   invariant: gösterilen değer, `_classify()` ile yeniden sınıflandırıldığında
   DAİMA `decision` ile eşleşir.
2. `ExplanationEngine`/`fcm_sender.py`'nin AYNI paylaşımlı yardımcıyı
   kullandığını (parity) -- iki sunum yüzeyi bir daha SESSİZCE sürüklenemez.
"""

from datetime import datetime, timezone

from app.engines.decision.engine import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, DecisionEngine, _classify
from app.engines.explanation.engine import ExplanationEngine
from app.models.ai_decision import AIDecision
from app.models.technical_analysis import TechnicalAnalysis
from app.services.notifications import fcm_sender
from app.utils.decision_score_format import format_decision_score

_T = dict(DEFAULT_THRESHOLDS)  # {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}


# ---------------------------------------------------------------------------
# 1) format_decision_score() birim testleri
# ---------------------------------------------------------------------------


def test_buy_boundary_39996_does_not_display_40():
    """HATA 18A'nın ana örneği: 39.996/WEAK_BUY, buy=40 -- gösterim "+40.0"
    veya "+40.00" OLAMAZ, 40'ın altında kalan ve WEAK_BUY ile görsel olarak
    tutarlı bir değer göstermeli."""
    text = format_decision_score(39.996, "WEAK_BUY", _T)
    assert text not in {"+40.0", "+40.00"}
    assert float(text) < 40.0
    assert _classify(float(text), _T) == "WEAK_BUY"


def test_sell_boundary_minus_39996_does_not_display_minus_40():
    text = format_decision_score(-39.996, "WEAK_SELL", _T)
    assert text not in {"-40.0", "-40.00"}
    assert float(text) > -40.0
    assert _classify(float(text), _T) == "WEAK_SELL"


def test_weak_buy_hold_boundary_14996_does_not_round_onto_weak_buy():
    text = format_decision_score(14.996, "HOLD", _T)
    assert float(text) < 15.0
    assert _classify(float(text), _T) == "HOLD"


def test_weak_sell_hold_boundary_minus_14996_does_not_round_onto_weak_sell():
    text = format_decision_score(-14.996, "HOLD", _T)
    assert float(text) > -15.0
    assert _classify(float(text), _T) == "HOLD"


def test_exact_buy_boundary_stays_compact():
    assert format_decision_score(40.0, "BUY", _T) == "+40.0"


def test_exact_weak_buy_boundary_stays_compact():
    assert format_decision_score(15.0, "WEAK_BUY", _T) == "+15.0"


def test_exact_weak_sell_boundary_stays_compact():
    assert format_decision_score(-15.0, "WEAK_SELL", _T) == "-15.0"


def test_exact_sell_boundary_stays_compact():
    assert format_decision_score(-40.0, "SELL", _T) == "-40.0"


def test_normal_scores_stay_human_friendly_one_decimal():
    """Sınıra yakın OLMAYAN normal skorlar, adaptif hassasiyet gereksiz yere
    tetiklenmeden kompakt 1-ondalık formatta kalmalı."""
    assert format_decision_score(32.0, "WEAK_BUY", _T) == "+32.0"
    assert format_decision_score(45.0, "BUY", _T) == "+45.0"
    assert format_decision_score(0.0, "HOLD", _T) == "+0.0"
    assert format_decision_score(-18.5, "WEAK_SELL", _T) == "-18.5"


def test_small_magnitude_scores_display_without_ugly_negative_zero():
    """+0.04/-0.04 ikisi de meşru HOLD/nötr bandında -- 1 ondalıkta ikisi de
    sıfıra yuvarlanır. Bu bir eşik-çelişkisi DEĞİL (ikisi de aynı nötr
    sınıfa ait); yalnızca çirkin "-0.0" kozmetik olarak "+0.0"'a normalize
    edilir, bilimsel işaret (final_score'un kendisi, girdi olarak) değişmez."""
    assert format_decision_score(0.04, "HOLD", _T) == "+0.0"
    assert format_decision_score(-0.04, "HOLD", _T) == "+0.0"


def test_display_classification_parity_invariant_across_near_boundary_fixtures():
    """YÜK TAŞIYAN invariant (ticket bölüm 24): her eşiğe-yakın fixture için,
    gösterilen string parse edilip AYNI eşiklerle sınıflandırıldığında
    persisted `decision` ile TAM eşleşmeli."""
    fixtures = [
        (39.996, "WEAK_BUY"),
        (-39.996, "WEAK_SELL"),
        (14.996, "HOLD"),
        (-14.996, "HOLD"),
        (40.0, "BUY"),
        (15.0, "WEAK_BUY"),
        (-15.0, "WEAK_SELL"),
        (-40.0, "SELL"),
        (32.0, "WEAK_BUY"),
        (0.0, "HOLD"),
        (0.04, "HOLD"),
        (-0.04, "HOLD"),
    ]
    for final_score, decision in fixtures:
        rendered = format_decision_score(final_score, decision, _T)
        assert _classify(float(rendered), _T) == decision, (final_score, decision, rendered)


def test_legacy_no_thresholds_formats_safely_without_guessing():
    """`decision_thresholds=None` (17D-öncesi kayıt): config lookup YOK, crash
    YOK, uydurulmuş eşik YOK -- doğrudan round-trip-safe temsil."""
    assert format_decision_score(39.996, "WEAK_BUY", None) == "+39.996"
    assert format_decision_score(-39.996, "WEAK_SELL", None) == "-39.996"
    assert format_decision_score(45.0, "BUY", None) == "+45.0"
    assert format_decision_score(-0.04, "HOLD", None) == "-0.04"  # normal sign, sıfıra YUVARLANMADI


def test_config_drift_does_not_affect_persisted_decision_display():
    """HATA 17D'nin threshold-snapshot ilkesiyle AYNI -- formatlama, güncel
    (drift etmiş) config'e HİÇBİR ŞEKİLDE erişmez/ihtiyaç duymaz; yalnızca
    persisted `decision_thresholds` kullanılır. Bu test, `format_decision_
    score`'a doğrudan bir config repo bile GEÇİRİLMEDİĞİNİ -- fonksiyonun
    imzasının böyle bir bağımlılığı yapısal olarak imkansız kıldığını
    kanıtlar (aşağıdaki sürüklenme testiyle aynı ilke)."""
    persisted_thresholds_a = {"buy": 40.0, "weak_buy": 15.0, "weak_sell": -15.0, "sell": -40.0}
    drifted_thresholds_b = {"buy": 30.0, "weak_buy": 10.0, "weak_sell": -10.0, "sell": -30.0}

    # final_score=35.0 CONFIG A altında WEAK_BUY, CONFIG B altında BUY olurdu.
    text_with_a = format_decision_score(35.0, "WEAK_BUY", persisted_thresholds_a)
    assert _classify(float(text_with_a), persisted_thresholds_a) == "WEAK_BUY"
    # Aynı final_score, decision hâlâ (persisted) WEAK_BUY olarak geçilirse
    # -- fonksiyon drifted_thresholds_b'yi HİÇ görmese bile -- yine WEAK_BUY
    # ile tutarlı bir string üretmeye devam eder (persisted decision + persisted
    # thresholds tek kaynak, ikinci bir config asla karışmaz).
    assert _classify(35.0, drifted_thresholds_b) == "BUY"  # kontrol: B altında gerçekten farklı


# ---------------------------------------------------------------------------
# 2) ExplanationEngine / FCM parity + no-scientific-change regresyonu
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


class _FakeTechnicalEngineWithScore:
    def __init__(self, technical_score):
        self._technical_score = technical_score

    def analyze_with_id(self, symbol, persist=True):
        analysis = TechnicalAnalysis(
            asset=symbol,
            technical_score=self._technical_score,
            trend="up",
            confidence=0.9,
            components={"rsi": 20.0},
            indicators={},
            created_at=datetime.now(timezone.utc),
        )
        return analysis, "tech-id"


class _FakeMacroRepo:
    def get_latest_with_id(self):
        return None, None


class _FakeNewsRepo:
    def list_for_asset(self, asset, limit=10):
        return []


class _FakeNewsRawRepo:
    def get_by_external_id(self, external_id):
        return None


def _explanation_engine(technical_score):
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    return ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngineWithScore(technical_score),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo(),
        news_raw_repo=_FakeNewsRawRepo(),
    )


def test_explanation_engine_summary_never_displays_score_that_implies_wrong_tier():
    """technical=79.992 (yalnızca technical mevcut -> final_score=79.992,
    tek kanal olduğundan renormalizasyon SONRASI DEĞİŞMEZ) -- WEAK_BUY/BUY
    eşiği 40'ın oldukça üzerinde, gerçek bir eşik testi için weak_buy=15
    civarına düşürelim: technical=14.996 tek kanalda final_score=14.996 ->
    HOLD (14.996 < 15). Eski `:+.1f` "+15.0" gösterirdi (WEAK_BUY'a ait)."""
    result = _explanation_engine(14.996).explain("TEST")

    assert result["decision"] == "HOLD"
    assert "final skor: +15.0" not in result["summary"].lower()
    assert "final skor: +14.996" in result["summary"].lower()


def _decision_for_fcm(final_score, decision, decision_thresholds):
    now = datetime.now(timezone.utc)
    return AIDecision(
        asset="THYAO",
        created_at=now,
        technical_score=final_score,
        news_score=None,
        macro_score=None,
        technical_weight=0.5,
        news_weight=0.3,
        macro_weight=0.2,
        final_score=final_score,
        decision=decision,
        confidence=70.0,
        channel_completeness=0.8,
        decision_engine_version="1.2.0",
        decision_thresholds=decision_thresholds,
    )


class _FakeTokenRepo:
    def get(self, user_id):
        return "tok"


class _FakeRecordRepo:
    def __init__(self):
        self.added = []

    def add(self, record):
        self.added.append(record)
        return "fake-record-id"


def test_explanation_and_fcm_render_identical_safe_score_representation(monkeypatch):
    """Parity invariant (ticket bölüm 25): AYNI AIDecision için Explanation
    özeti ve FCM bildirim body'si, AYNI güvenli skor temsilini içermeli --
    iki yüzey bir daha SESSİZCE ayrı formatlama mantığına sürüklenemez.

    NOT: `fcm_sender._compose_and_send()` yalnızca STRONG_DECISIONS (BUY/SELL)
    için çağrılır (`_DECISION_LABELS` yalnızca bu ikisini tanır). BUY/SELL
    eşikleri VARSAYILAN (yuvarlak, ör. 40.0) olduğunda 1-ondalık formatlama
    ASLA eşik-yanlış-katman göstermez (bkz. modül raporu: `score>=buy` gibi
    tek-yönlü kapsayıcı bir eşik, eşiğin KENDİSİ 1-ondalık ızgara noktasıysa,
    zaten >= eşik olan bir değerin 1-ondalığa yuvarlanması matematiksel
    olarak ASLA eşiğin ALTINA düşemez) -- bu yüzden gerçek bir escalation'ı
    (ve dolayısıyla eski `:+.1f` ile YENİ paylaşımlı fonksiyon arasında
    GERÇEK bir metin farkını) BUY/SELL yüzeyinde göstermek için, Firestore'un
    (round OLMAYAN bir threshold config'i de teknik olarak GEÇERLİDİR)
    izin verdiği gerçekçi bir senaryo kullanılır: buy=45.04 (round DEĞİL),
    final_score=45.041 (BUY, eşiğin az üzerinde). 1 ondalıkta "+45.0" ->
    45.0 < 45.04 -> YANLIŞLIKLA WEAK_BUY'a düşer -- adaptif fonksiyon 2
    ondalığa çıkar ("+45.04"), eski sabit `:+.1f` ise "+45.0"'da KALIRDI."""
    monkeypatch.setattr(fcm_sender, "NotificationRecordRepository", _FakeRecordRepo)

    final_score, decision = 45.041, "BUY"
    thresholds = {**DEFAULT_THRESHOLDS, "buy": 45.04}
    expected_text = format_decision_score(final_score, decision, thresholds)
    assert expected_text == "+45.04"  # gerçekten escalate ettiğini doğrula (1 ondalık DEĞİL)

    class _FakeConfigRepoCustomThresholds:
        def get_raw(self, key):
            if key == "decision_weights":
                return dict(DEFAULT_WEIGHTS)
            if key == "decision_thresholds":
                return dict(thresholds)
            return None

    decision_engine = DecisionEngine(config_repo=_FakeConfigRepoCustomThresholds(), decision_repo=_FakeDecisionRepo())
    explanation_engine = ExplanationEngine(
        decision_engine=decision_engine,
        technical_engine=_FakeTechnicalEngineWithScore(final_score),
        macro_repo=_FakeMacroRepo(),
        news_repo=_FakeNewsRepo(),
        news_raw_repo=_FakeNewsRawRepo(),
    )
    explanation = explanation_engine.explain("TEST")
    assert explanation["decision"] == decision
    assert f"final skor: {expected_text}" in explanation["summary"].lower()

    captured = {}

    def _fake_send(message):
        captured["body"] = message.notification.body

    monkeypatch.setattr(fcm_sender.messaging, "send", _fake_send)
    fcm_sender._compose_and_send(
        "u1",
        _decision_for_fcm(final_score, decision, thresholds),
        _FakeTokenRepo(),
        _FakeRecordRepo(),
        quantity_held=None,
        suggested_buy_quantity=None,
        budget_tl=None,
    )
    assert f"Final skor: {expected_text}" in captured["body"]


def test_no_scientific_fields_changed_by_presentation_fix():
    """Bu ticket YALNIZCA sunum katmanını değiştirir -- final_score/decision/
    confidence/channel_completeness/weights/threshold snapshot/config hash
    HİÇBİRİ etkilenmez (yalnızca string çıktısı değişir)."""
    decision_engine = DecisionEngine(config_repo=_FakeConfigRepo(), decision_repo=_FakeDecisionRepo())
    decision = decision_engine.decide(
        asset="TEST",
        technical_score=39.996,
        persist=False,
    )
    assert decision.final_score == 39.996
    assert decision.decision == "WEAK_BUY"
    assert decision.decision_thresholds == dict(DEFAULT_THRESHOLDS)
    # format_decision_score çağrısı bu alanlardan HİÇBİRİNİ mutasyona uğratmaz.
    format_decision_score(decision.final_score, decision.decision, decision.decision_thresholds)
    assert decision.final_score == 39.996
    assert decision.decision == "WEAK_BUY"
