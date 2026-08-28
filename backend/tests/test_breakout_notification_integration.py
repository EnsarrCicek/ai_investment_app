"""HATA 4B — ROOT-CAUSE regression: kilitlenmesi gereken asıl bug, tek tek
fonksiyonların (find_swing_points/build_zones/breakout_timeline/classify_
signal) ayrı ayrı DOĞRU olması DEĞİLDİ — hepsi zaten doğruydu. Bug, bunların
`TechnicalAnalysisEngine._compute_enrichment()` içindeki ESKİ WIRING'inde
(`detect_breakout(..., index=len(df)-1)` her gün "bugün"e yeniden
ankorlanıyordu) saklıydı ve yalnızca UÇTAN UCA, gerçek `analyze_with_id()`
çağrısıyla ortaya çıkarılabilirdi (bkz. HATA 4B audit'i — mock'lanmış
`signal_class="STRONG_BULLISH_INITIATION"` fixture'ları bu wiring hatasını
tamamen gizliyordu).

Bu dosyadaki testler HİÇBİR KATMANI mock'lamaz (market_structure, build_zones,
breakout_timeline, to_legacy_breakout_event, classify_signal hepsi GERÇEK
production kodu, gerçek `TechnicalAnalysisEngine.analyze_with_id()` üzerinden
çalışır) — yalnızca ağ bağımlılıkları (fiyat geçmişi, XU100 benchmark, FCM)
fake'lenir. Bu, bug'ın bir daha geri dönemeyeceğini kilitleyen asıl testtir.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.engine import DEFAULT_WEIGHTS, TechnicalAnalysisEngine
from app.models.ai_decision import AIDecision
from app.models.market_data import Quote
from app.models.technical_analysis import TechnicalAnalysis
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.trading_calendar import expected_trading_sessions
from app.services.notifications import fcm_sender

TZ = ZoneInfo("Europe/Istanbul")


def _bist_trading_days(end: date, n: int) -> list[date]:
    search_start = end - timedelta(days=n * 2 + 10)
    sessions = expected_trading_sessions(search_start, end)
    return sessions[-n:]


class _FakeProvider(MarketDataProvider):
    def __init__(self, history_df: pd.DataFrame):
        self._df = history_df

    def get_latest(self, symbol):
        raise NotImplementedError

    def get_quote(self, symbol):
        return Quote(
            asset_id=symbol, timestamp=datetime.now(timezone.utc), last_price=100.0, previous_close=100.0,
            change=0.0, change_percent=0.0, open=100.0, high=100.0, low=100.0, volume=1000, source="fake",
        )

    def get_history(self, symbol, period="6mo", interval="1d", start=None, end=None):
        return self._df


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        # HATA 5B2D FINAL COMMIT GATE: `technical_indicator_weights` artık
        # REQUIRED (missing -> fail-fast).
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        return None


class _FakeBenchmarkCacheRepo:
    def get(self):
        return None

    def set(self, close_by_date, fetched_at):
        pass


class _FakeTechnicalAnalysisRepo:
    def get_latest_with_id(self, asset):
        return None, None

    def add(self, analysis):
        return "new-id"


class _FakeAnalysisRepo:
    def __init__(self, analysis: TechnicalAnalysis):
        self._analysis = analysis

    def get_latest(self, asset):
        return self._analysis


class _FakeTokenRepo:
    def get(self, user_id):
        return "tok"


class _FakeNewOpportunityLogRepo:
    """Gerçek `NewOpportunityNotificationRepository`'nin atomic claim/mark/
    release sözleşmesini in-memory taklit eder (bkz. test_fcm_sender.py'deki
    ikizi)."""

    def __init__(self):
        self._docs: dict[tuple, dict] = {}

    def claim_new_opportunity(self, user_id, asset, event_id):
        import uuid

        key = (user_id, asset, event_id)
        if key in self._docs:
            return None
        token = uuid.uuid4().hex
        self._docs[key] = {"status": "PENDING", "claim_token": token}
        return token

    def mark_new_opportunity_sent(self, user_id, asset, event_id, claim_token):
        doc = self._docs.get((user_id, asset, event_id))
        if doc is not None and doc["status"] == "PENDING" and doc["claim_token"] == claim_token:
            doc["status"] = "SENT"

    def release_new_opportunity_claim(self, user_id, asset, event_id, claim_token):
        key = (user_id, asset, event_id)
        doc = self._docs.get(key)
        if doc is not None and doc["status"] == "PENDING" and doc["claim_token"] == claim_token:
            del self._docs[key]


def _decision(decision: str = "BUY") -> AIDecision:
    now = datetime.now(timezone.utc)
    return AIDecision(
        asset="TEST", created_at=now, technical_score=60.0, news_score=None, macro_score=None,
        technical_weight=1.0, news_weight=0.0, macro_weight=0.0, final_score=60.0,
        decision=decision, confidence=80.0, decision_engine_version="1.0.0",
    )


def _build_strong_bullish_df(n_up: int = 138) -> pd.DataFrame:
    """Staircase uptrend (10-bar rise + 6-bar pullback, tekrarlanan) -- her
    döngü kendi HH/HL swing'ini ve bir önceki döngünün tepesini kıran, gerçek
    (transition-based) bir CONFIRMED breakout üretir. `n_up=138` deneysel
    olarak seçildi: son event (idx 132) CONFIRMED + retest PENDING, age=5 --
    hem "confirmed" hem "henüz açıkça broken değil" (retest_held=None)
    koşullarını sağlıyor, tam STRONG_BULLISH_INITIATION'ın ihtiyaç duyduğu
    şekilde. Bugünkü (son bar) hacim ayrıca güçlü bir spike ile VERY_HIGH
    relative-volume üretecek şekilde kuruldu; haftalık/günlük EMA eğimi aynı
    yönde olduğundan mtf_aligned=True/consensus=UP doğal olarak oluşuyor.
    """
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    trading_days = _bist_trading_days(end, n_up)
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in trading_days])

    closes = []
    level = 50.0
    for _ in range(n_up // 16 + 3):
        for _ in range(10):
            level += 1.5
            closes.append(level)
        for _ in range(6):
            level -= 1.0
            closes.append(level)
    closes = np.array(closes[:n_up])

    volume = np.full(n_up, 5000.0)
    volume[-1] = 20000.0

    return pd.DataFrame(
        {"Open": closes - 0.2, "High": closes + 0.6, "Low": closes - 0.6, "Close": closes, "Volume": volume},
        index=idx,
    )


def _run_engine(df: pd.DataFrame) -> TechnicalAnalysis:
    engine = TechnicalAnalysisEngine(
        provider=_FakeProvider(df),
        config_repo=_FakeConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    now = datetime(df.index[-1].year, df.index[-1].month, df.index[-1].day, 19, 0, tzinfo=TZ)
    analysis, _ = engine.analyze_with_id("TEST", now=now)
    return analysis


@pytest.fixture(scope="module")
def real_strong_bullish_analysis() -> TechnicalAnalysis:
    return _run_engine(_build_strong_bullish_df())


# ---------------------------------------------------------------------------
# HATA 4B'nin asıl kilidi: hiçbir katman mock'lanmadan STRONG_BULLISH_
# INITIATION'ın gerçekten üretilebildiğini kanıtlar.
# ---------------------------------------------------------------------------


def test_root_cause_regression_confirmed_breakout_reaches_strong_bullish_initiation(real_strong_bullish_analysis):
    analysis = real_strong_bullish_analysis

    assert analysis.breakout is not None
    assert analysis.breakout["confirmed"] is True
    assert analysis.breakout_event_id is not None
    assert analysis.signal_class == "STRONG_BULLISH_INITIATION"


# ---------------------------------------------------------------------------
# Aynı gerçek analysis nesnesi, gerçek notify_if_new_opportunity() yoluna
# veriliyor -- signal_class hiçbir yerde elle "STRONG_BULLISH_INITIATION"
# diye YAZILMADI, tamamen yukarıdaki gerçek pipeline'dan geldi.
# ---------------------------------------------------------------------------


def test_end_to_end_new_opportunity_notification_from_real_pipeline(monkeypatch, real_strong_bullish_analysis):
    analysis = real_strong_bullish_analysis
    real_event_id = analysis.breakout_event_id

    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))
    log_repo = _FakeNewOpportunityLogRepo()

    def _notify(event_id):
        a = analysis.model_copy(update={"breakout_event_id": event_id})
        return fcm_sender.notify_if_new_opportunity(
            "u1", _decision(), analysis_repo=_FakeAnalysisRepo(a), provider=_FakeProvider(pd.DataFrame()),
            token_repo=_FakeTokenRepo(), new_opportunity_log_repo=log_repo,
        )

    event1 = real_event_id
    event2 = "TEST:BULLISH:2026-09-05"

    sent_event1_first = _notify(event1)
    sent_event1_repeat = _notify(event1)
    sent_event2 = _notify(event2)
    sent_event1_fallback = _notify(event1)  # live selector event1'e geri dönmüş gibi -- SUPPRESSED kalmalı

    assert sent_event1_first is True
    assert sent_event1_repeat is False
    assert sent_event2 is True
    assert sent_event1_fallback is False
    assert len(sent_messages) == 2


# ---------------------------------------------------------------------------
# Backward compatibility: breakout_event_id'siz eski bir Firestore kaydı.
# ---------------------------------------------------------------------------


def test_technical_analysis_parses_old_record_without_breakout_event_id():
    old_record = dict(
        asset="THYAO", technical_score=10.0, trend="NEUTRAL", confidence=0.5,
        components={}, indicators={}, created_at=datetime.now(timezone.utc),
    )
    analysis = TechnicalAnalysis(**old_record)
    assert analysis.breakout_event_id is None
