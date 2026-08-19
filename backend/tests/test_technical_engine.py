from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.engine import TECHNICAL_CACHE_TTL_SECONDS, TechnicalAnalysisEngine
from app.models.technical_analysis import TechnicalAnalysis


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


class _StaleSixKeyConfigRepo:
    """Firestore'da AŞAMA 48/9 öncesinden kalmış, "ema_slope" anahtarı OLMAYAN
    eski bir "technical_indicator_weights" belgesini simüle eder — toplam
    ağırlık artık 1.0 değildir. final_score'un yine de [-100, 100] aralığında
    kalması gerekir (normalize edilmiş ağırlıklı ortalama formülü sayesinde).
    """

    def get(self, key, defaults):
        return {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667, "roc": 0.1665}


class _FakeTechnicalAnalysisRepo:
    def __init__(self, cached: TechnicalAnalysis | None = None, cached_id: str | None = None):
        self._cached = cached
        self._cached_id = cached_id
        self.added: list[TechnicalAnalysis] = []

    def get_latest_with_id(self, asset):
        return self._cached, self._cached_id

    def add(self, analysis: TechnicalAnalysis) -> str:
        self.added.append(analysis)
        return "new-id"


def _cached_analysis(age_seconds: float) -> TechnicalAnalysis:
    return TechnicalAnalysis(
        asset="TEST",
        technical_score=42.0,
        trend="BULLISH",
        confidence=0.9,
        components={"rsi": 42.0},
        indicators={"rsi": 55.0},
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


def _real_history_df(rows: int = 120) -> pd.DataFrame:
    # get_history() bu DataFrame'i asla döndürmemeli (cache hit testlerinde) —
    # provider'ın history_df'i None birakilirsa FakeMarketDataProvider
    # NotImplementedError firlatir, bu da cache'in atlanip atlanmadigini kanitlar.
    # Son bar bilinçli olarak "bugüne" göre üretilir (dun degil): AŞAMA 48'deki
    # STALE_DATA veto kontrolü, son bar gerçek "şimdi"den çok uzaksa reddeder.
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    end = pd.Timestamp.now(tz="UTC").normalize()
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, rows),
        },
        index=pd.date_range(end=end, periods=rows, freq="D"),
    )


def test_analyze_with_id_uses_cache_when_fresh(fake_provider):
    cached = _cached_analysis(age_seconds=60)  # 1 dakika önce — TTL(900s) içinde
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached, cached_id="cached-id")
    provider = fake_provider(history_df=None)  # get_history çağrılırsa NotImplementedError patlar
    engine = TechnicalAnalysisEngine(provider=provider, config_repo=_FakeConfigRepo(), analysis_repo=analysis_repo)

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is cached
    assert doc_id == "cached-id"
    assert analysis_repo.added == []  # yeniden hesaplanıp kaydedilmedi


def test_analyze_with_id_recomputes_when_stale(fake_provider):
    stale = _cached_analysis(age_seconds=TECHNICAL_CACHE_TTL_SECONDS + 60)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=stale, cached_id="stale-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(provider=provider, config_repo=_FakeConfigRepo(), analysis_repo=analysis_repo)

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not stale
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_recomputes_when_no_cache(fake_provider):
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(provider=provider, config_repo=_FakeConfigRepo(), analysis_repo=analysis_repo)

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_respects_custom_max_age(fake_provider):
    cached = _cached_analysis(age_seconds=30)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached, cached_id="cached-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(provider=provider, config_repo=_FakeConfigRepo(), analysis_repo=analysis_repo)

    # max_age_seconds=10 iken 30 saniyelik kayıt bayat sayılmalı — yeniden hesaplanır.
    analysis, doc_id = engine.analyze_with_id("TEST", max_age_seconds=10)

    assert analysis is not cached
    assert doc_id == "new-id"


def test_analyze_with_id_includes_ema_slope_component(fake_provider):
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(provider=provider, config_repo=_FakeConfigRepo(), analysis_repo=analysis_repo)

    analysis, _ = engine.analyze_with_id("TEST")

    assert "ema_slope" in analysis.components
    assert "ema_slope" in analysis.indicators
    assert -100 <= analysis.technical_score <= 100


def test_analyze_with_id_normalizes_score_with_stale_weight_config(fake_provider):
    # AŞAMA 48/9: "ema_slope" eklendiğinde, Firestore'da hâlâ eski 6 anahtarlı
    # bir kayıt varsa (toplam ağırlık != 1.0), final_score yine de sınırlar
    # içinde kalmalı — ağırlık toplamına bölünerek normalize edilir.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider, config_repo=_StaleSixKeyConfigRepo(), analysis_repo=analysis_repo
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert -100 <= analysis.technical_score <= 100
