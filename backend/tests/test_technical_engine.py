from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical import indicators as ind
from app.engines.technical.engine import DEFAULT_WEIGHTS, ENGINE_VERSION, TECHNICAL_CACHE_TTL_SECONDS, TechnicalAnalysisEngine
from app.engines.technical.scoring import DEFAULT_TECHNICAL_FAMILY_WEIGHTS, compute_scoring_config_hash
from app.models.technical_analysis import TechnicalAnalysis
from app.services.market_data.trading_calendar import expected_trading_sessions

TZ = ZoneInfo("Europe/Istanbul")


def _bist_trading_days(end: date, n: int) -> list[date]:
    """HATA 3C (26.08.2026): gerçek BIST takvimine göre `end` (dahil) ile
    biten SON `n` işlem gününü döner — naif `pd.date_range(freq='D')`/
    `pd.bdate_range()` artık kullanılmıyor, çünkü ikisi de hafta içi resmi
    tatilleri BİLMEZ ve genişletilmiş takvimle (2021-2026) artık
    `check_trading_day_continuity`'nin `UNEXPECTED_TRADING_SESSION`
    kontrolüne takılıyordu."""
    search_start = end - timedelta(days=n * 2 + 10)  # bol pay (tatil/haftasonu için)
    sessions = expected_trading_sessions(search_start, end)
    assert sessions is not None and len(sessions) >= n, "test penceresi desteklenmeyen bir yila mi tasiyor?"
    return sessions[-n:]


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        # HATA 5B2D FINAL COMMIT GATE: `technical_indicator_weights` artık
        # REQUIRED (missing -> fail-fast) -- gerçek production'ı simüle etmek
        # için burada GEÇERLİ/TAM bir config döner. `technical_family_weights`
        # ise hâlâ `None` döner -- dokümanı henüz production'da yok (pre-deploy
        # gate ayrı), bu da `resolve_family_weights()`'in `DEFAULT_TECHNICAL_
        # FAMILY_WEIGHTS`'e (eşit 1/3) düşen gerçek dalını egzersiz eder.
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        return None


class _StaleSixKeyConfigRepo:
    """Firestore'da AŞAMA 48/9 öncesinden kalmış, "ema_slope" anahtarı OLMAYAN
    eski bir "technical_indicator_weights" belgesini simüle eder.

    HATA 5B2D FINAL PRE-COMMIT GATE, madde 8: bu senaryo eskiden (AŞAMA 48/9)
    BİLİNÇLİ OLARAK "graceful degradation" (eksik anahtar `DEFAULT_WEIGHTS`
    ile sessizce tamamlanır) olarak tasarlanmıştı -- ama bu TAM OLARAK HATA
    5B2C'nin kök nedeni olan mekanizmadır (`ema_slope`'un aylarca fark
    edilmeden eksik kalması). Family mimarisinde bu weight'ler artık
    within-family methodology'nin bir parçası olduğundan, aynı sessiz drift
    riski KAPATILDI: bu fixture artık "eski davranış hâlâ çalışıyor" DEĞİL,
    "partial config artık fail-fast" kontratını kilitliyor (bkz. aşağıdaki
    test, `test_analyze_with_id_rejects_stale_six_key_weight_config`).
    """

    def get(self, key, defaults):
        return {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667, "roc": 0.1665}

    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667, "roc": 0.1665}
        return None


class _FakeBenchmarkCacheRepo:
    """XU100 önbelleğini gerçek Firestore'a hiç dokunmadan simüle eder —
    her zaman "önbellek yok" döner, bu yüzden get_benchmark_close_series()
    provider'dan (fake_provider, gerçek ağ isteği yapmaz) okur."""

    def get(self):
        return None

    def set(self, close_by_date, fetched_at):
        pass


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


def _cached_analysis(
    age_seconds: float, engine_version: str = ENGINE_VERSION, scoring_config_hash: str | None = None
) -> TechnicalAnalysis:
    return TechnicalAnalysis(
        asset="TEST",
        technical_score=42.0,
        trend="BULLISH",
        confidence=0.9,
        components={"rsi": 42.0},
        indicators={"rsi": 55.0},
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        engine_version=engine_version,
        scoring_config_hash=scoring_config_hash,
    )


# `_FakeConfigRepo` her zaman `DEFAULT_WEIGHTS`/`DEFAULT_TECHNICAL_FAMILY_
# WEIGHTS`'e resolve olur -- "cache HIT olmalı" testleri bu GERÇEK hash'i
# kullanmalı (HATA 5B2D TRUE FINAL COMMIT GATE, madde 8-A).
_FAKE_CONFIG_REPO_SCORING_HASH = compute_scoring_config_hash(DEFAULT_WEIGHTS, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)


def test_technical_analysis_old_float_document_still_parses():
    # HATA 5B1 madde S: TÜM mevcut Firestore kayıtları `technical_score`'u
    # gerçek bir float olarak taşıyor (bug dormant'tı) -- `float | None` tip
    # birleşimi geriye dönük UYUMLUDUR, bir float bu birleşimin bir ALT
    # KÜMESİDİR. Migration YOK.
    old_style_doc = {
        "asset": "TEST",
        "technical_score": 42.0,
        "trend": "BULLISH",
        "confidence": 0.9,
        "components": {"rsi": 42.0},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**old_style_doc)
    assert analysis.technical_score == 42.0


def test_technical_analysis_new_null_score_document_parses():
    # HATA 5B1 madde T: 7 component'in tamamı unavailable olduğunda üretilen
    # YENİ `technical_score: null` kaydı da (repository `model_dump()`'ın
    # mevcut nullable-field convention'ıyla Firestore'a yazdığı hali) hatasız
    # parse edilmeli.
    new_style_doc = {
        "asset": "TEST",
        "technical_score": None,
        "trend": "NEUTRAL",
        "confidence": 0.0,
        "components": {},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**new_style_doc)
    assert analysis.technical_score is None


def test_technical_analysis_old_string_trend_document_still_parses():
    # HATA 5B1 FINAL PRE-COMMIT GATE, madde 2: TÜM mevcut Firestore kayıtları
    # `trend`'i gerçek bir `str` ("BULLISH"/"BEARISH"/"NEUTRAL") olarak
    # taşıyor -- `str | None` tip birleşimi geriye dönük UYUMLUDUR. Migration
    # YOK.
    old_style_doc = {
        "asset": "TEST",
        "technical_score": 42.0,
        "trend": "BULLISH",
        "confidence": 0.9,
        "components": {"rsi": 42.0},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**old_style_doc)
    assert analysis.trend == "BULLISH"


def test_technical_analysis_new_null_trend_document_parses():
    # HATA 5B1 FINAL PRE-COMMIT GATE, madde 2: `technical_score=None`
    # olduğunda üretilen YENİ `trend: null` kaydı da hatasız parse edilmeli.
    new_style_doc = {
        "asset": "TEST",
        "technical_score": None,
        "trend": None,
        "confidence": 0.0,
        "components": {},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**new_style_doc)
    assert analysis.trend is None


def test_technical_analysis_old_document_without_family_scores_still_parses():
    # HATA 5B2D madde 34-N: `family_scores` eklenmeden önceki (flat 7-component,
    # ENGINE_VERSION 1.6.0 ve öncesi) Firestore kayıtları bu alanı hiç
    # taşımıyor -- `default_factory=dict` bunu geriye dönük uyumlu şekilde
    # ifade eder, migration YOK.
    old_style_doc = {
        "asset": "TEST",
        "technical_score": 42.0,
        "trend": "BULLISH",
        "confidence": 0.9,
        "components": {"rsi": 42.0},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
        "engine_version": "1.6.0",
    }
    analysis = TechnicalAnalysis(**old_style_doc)
    assert analysis.family_scores == {}


def test_technical_analysis_new_document_with_family_scores_parses():
    # HATA 5B2D madde 34-O: yeni (1.7.0) kayıtlar `family_scores` taşır.
    new_style_doc = {
        "asset": "TEST",
        "technical_score": 27.77,
        "trend": "NEUTRAL",
        "confidence": 0.7,
        "components": {"rsi": 40.0},
        "family_scores": {"trend": 30.0, "oscillator_position": 15.0, "momentum_rate": 38.32},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
        "engine_version": "1.7.0",
    }
    analysis = TechnicalAnalysis(**new_style_doc)
    assert analysis.family_scores == {"trend": 30.0, "oscillator_position": 15.0, "momentum_rate": 38.32}


def test_engine_version_is_1_9_0():
    # HATA 7C-FIX: check_alignment()'in eksik (UNKNOWN) bir zaman dilimini
    # artık "uyumlu" saymaması ENGINE_VERSION bump'ını ZORUNLU kılar
    # (1.8.0 -> 1.9.0) -- technical_score formülü YİNE DEĞİŞMEDİ.
    assert ENGINE_VERSION == "1.9.0"


def _real_history_df(rows: int = 120) -> pd.DataFrame:
    # get_history() bu DataFrame'i asla döndürmemeli (cache hit testlerinde) —
    # provider'ın history_df'i None birakilirsa FakeMarketDataProvider
    # NotImplementedError firlatir, bu da cache'in atlanip atlanmadigini kanitlar.
    # Son bar bilinçli olarak "DÜN"e göre üretilir (bugün DEĞİL): AŞAMA 48'deki
    # STALE_DATA veto kontrolü hâlâ geçer (1 gün << 5 gün toleransı), AMA HATA
    # 2A'dan (25.08.2026) sonra "bugün"e göre üretmek testi gerçek saatin
    # okunduğu ana göre (filter_completed_daily_bars piyasa açık mı kapalı mı
    # sanıp son barı atıp atmayacağına göre) FLAKY hale getirirdi — "dün"
    # kullanmak, gerçek çalıştırma saatinden bağımsız, deterministik bir
    # şekilde her zaman "zaten tamamlanmış" sayılmasını garanti eder. HATA 3C
    # (26.08.2026): tarihler artık gerçek BIST takviminden (`_bist_trading_days`)
    # geliyor — naif ardışık takvim günü üretimi resmi tatillere rastlayıp
    # `UNEXPECTED_TRADING_SESSION` ile veto edilebiliyordu.
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    trading_days = _bist_trading_days(end, rows)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, rows),
        },
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in trading_days]),
    )


def _flat_history_df(rows: int = 120, price: float = 100.0) -> pd.DataFrame:
    """HATA 5B1 (27.08.2026): tamamen düz (sabit) ama GEÇERLİ (pozitif,
    tutarlı OHLC) bir fiyat serisi — `check_raw_ohlcv_integrity()`'yi
    (Layer 1) sorunsuz geçer, ama ATR/Bollinger band_width TAM OLARAK 0
    üretir (gerçek, "corrupt olmayan" bir piyasa koşulu: N gün boyunca hiç
    fiyat hareketi yok)."""
    end = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    trading_days = _bist_trading_days(end, rows)
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in trading_days])
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price, "Volume": 1000},
        index=idx,
    )


def test_analyze_with_id_flat_price_makes_zero_denominator_components_unavailable(fake_provider):
    # HATA 5B1 madde K/L/M/N: düz fiyatta ATR=0/band_width=0 VE bu
    # component'lerin PAYI da (macd_hist/momentum diff/close-middle) aynı
    # düzlük yüzünden 0 olduğundan bunlar 0/0 BELİRSİZLİĞİDİR -- component
    # UNAVAILABLE sayılmalı, `components` dict'inden OMIT edilmeli. RSI'ın
    # düz-seri "50" tanımı (component=0), ve trend/ema_slope/ROC'un payDA
    # SIFIR OLMAYAN (100/100 gibi) oranları ise GERÇEK geçerli sıfırlardır --
    # AVAILABLE kalmalı.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_flat_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert "macd" not in analysis.components
    assert "momentum" not in analysis.components
    assert "bollinger" not in analysis.components
    assert analysis.components["rsi"] == 0.0
    assert analysis.components["trend"] == 0.0
    assert analysis.components["ema_slope"] == 0.0
    assert analysis.components["roc"] == 0.0
    assert analysis.technical_score is not None
    assert analysis.technical_score == 0.0
    # HATA 5B2D: 3 family de (yalnızca available member'ları üzerinden)
    # finite 0.0 -- None ile karışmaz, hiçbiri unavailable DEĞİLDİR.
    assert analysis.family_scores == {"trend": 0.0, "oscillator_position": 0.0, "momentum_rate": 0.0}


def test_technical_score_zero_vs_none_trend_signal_and_persistence_contract(fake_provider, monkeypatch):
    # HATA 5B1 FINAL PRE-COMMIT GATE, madde 1 + 2 + 5: iki kritik durumu AYNI
    # gerçek `analyze_with_id()` akışında, birbirine karşı kilitler.
    #
    # CASE A: technical_score=0.0 -- GEÇERLİ, hesaplanmış bir skor (düz fiyat
    # senaryosu). trend hâlâ "NEUTRAL" olmalı, "unavailable"/missing İLE
    # KARIŞTIRILMAMALI.
    analysis_repo_a = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    engine_a = TechnicalAnalysisEngine(
        provider=fake_provider(history_df=_flat_history_df()),
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo_a,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    case_a, _ = engine_a.analyze_with_id("TEST")

    assert case_a.technical_score == 0.0
    assert case_a.trend == "NEUTRAL"
    assert case_a.confidence > 0.0  # gerçek bir güven hesaplandı, 0'a ZORLANMADI
    # HATA 5B1 FINAL CONFIDENCE AUDIT, madde 6: skor GEÇERLİ (0.0, unavailable
    # DEĞİL) olduğundan signal classifier NORMAL şekilde çalışmış olmalı --
    # exact sınıf (mevcut classifier contract'ının kendi iç mantığı) burada
    # İDDİA EDİLMİYOR, yalnızca "unavailable skorda olduğu gibi None'a
    # DÜŞMEDİ" kilitleniyor.
    assert case_a.signal_class is not None

    # CASE B: technical_score=None -- yalnızca `scoring.py` unit seviyesinde
    # değil, GERÇEK `analyze_with_id()` akışında. Valid OHLCV kullanılır (Layer
    # 1 HARD VETO tetiklenmez); component aggregation'ı deterministik olarak
    # `None` yapan bir monkeypatch ile YALNIZCA `None`'ın engine içindeki
    # DOWNSTREAM yolu test edilir (indikatör matematiği DEĞİL) -- `stored_
    # components`'ın kendisi (gerçek matematikten üretildiği için) dolu
    # kalabilir, bu KASITLIDIR ve testin amacını etkilemez.
    monkeypatch.setattr(
        "app.engines.technical.engine.aggregate_available_scores",
        lambda *args, **kwargs: None,
    )
    analysis_repo_b = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    engine_b = TechnicalAnalysisEngine(
        provider=fake_provider(history_df=_real_history_df()),
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo_b,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    # Herhangi bir TypeError/numeric-comparison crash OLMADAN tamamlanmalı --
    # `final_score > 15`/`final_score >= 0` gibi karşılaştırmalar `None` ile
    # asla çağrılmaz (bkz. `if final_score is None:` dalı, engine.py).
    case_b, doc_id_b = engine_b.analyze_with_id("TEST")

    assert case_b.technical_score is None
    assert case_b.trend is None  # "NEUTRAL" UYDURULMADI
    # HATA 5C3A: confidence=None -- mutabakat hesaplanacak kullanılabilir
    # weighted evidence yok, "0.0" (gerçek tam uyuşmazlık) İLE KARIŞTIRILMAZ.
    assert case_b.confidence is None
    assert case_b.signal_class is None  # sahte WATCHLIST/BULLISH/BEARISH YOK
    assert case_b.investment_horizon is None
    assert case_b.investment_horizon_reason == ""
    # Firestore model construction (pydantic TechnicalAnalysis(...)) VE
    # persist (_FakeTechnicalAnalysisRepo.add) crash ETMEDİ.
    assert doc_id_b == "new-id"
    assert len(analysis_repo_b.added) == 1


class _PartialFamilyWeightsConfigRepo:
    """`technical_family_weights` dokümanı VAR ama eksik anahtarlı (HATA
    5B2C'nin kök nedenine benzer bir config-drift senaryosu) -- fail-fast
    end-to-end (madde 12) gerçek `analyze_with_id()` akışında da kilitlenmeli."""

    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        # `technical_indicator_weights` GEÇERLİ/TAM olmalı ki bu test YALNIZ
        # family-weights partial senaryosunu izole etsin (indicator weights
        # eksikliğiyle KARIŞMASIN, bkz. FINAL COMMIT GATE madde 1-4).
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "technical_family_weights":
            return {"trend": 0.5, "oscillator_position": 0.5}  # momentum_rate eksik
        return None


def test_analyze_with_id_raises_on_partial_family_weights_config(fake_provider):
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_PartialFamilyWeightsConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(cached=None, cached_id=None),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    with pytest.raises(ValueError):
        engine.analyze_with_id("TEST")


class _MissingIndicatorWeightsConfigRepo:
    """FINAL COMMIT GATE, madde 5: `technical_indicator_weights` dokümanı
    TAMAMEN yok -- bu artık "normal default case" DEĞİL, production config
    corruption/deletion olarak ele alınır (`technical_family_weights` ise
    dokümanı henüz production'da olmadığından hâlâ `None` -- eşit-1/3
    default'a düşer, bu DEĞİŞMEDİ)."""

    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        return None  # HEM indicator HEM family weights dokümanı yok


def test_analyze_with_id_fails_fast_on_missing_indicator_weights_document_not_data_quality(fake_provider):
    # FINAL COMMIT GATE, madde 5: geçerli OHLCV (Layer-1/continuity/min-history
    # HİÇBİRİ tetiklenmez) + `technical_indicator_weights` dokümanı TAMAMEN
    # yok -> ValueError, ama bu bir `DataQualityError` (`DataQualityError`
    # ValueError'ın ALT SINIFIDIR) DEĞİLDİR -- yalnızca config eksikliğinden
    # kaynaklandığı doğrudan kanıtlanır.
    from app.engines.technical.data_quality import DataQualityError

    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_MissingIndicatorWeightsConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(cached=None, cached_id=None),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    with pytest.raises(ValueError) as exc_info:
        engine.analyze_with_id("TEST")

    assert not isinstance(exc_info.value, DataQualityError)  # data-quality NEDENİYLE değil
    assert "technical_indicator_weights" in str(exc_info.value)  # doğrudan config nedeni


def test_analyze_with_id_uses_cache_when_fresh(fake_provider):
    cached = _cached_analysis(age_seconds=60, scoring_config_hash=_FAKE_CONFIG_REPO_SCORING_HASH)  # 1 dakika önce — TTL(900s) içinde, AYNI config
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached, cached_id="cached-id")
    provider = fake_provider(history_df=None)  # get_history çağrılırsa NotImplementedError patlar
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is cached
    assert doc_id == "cached-id"
    assert analysis_repo.added == []  # yeniden hesaplanıp kaydedilmedi


def test_analyze_with_id_recomputes_when_cached_engine_version_is_stale(fake_provider):
    # HATA 5B2D, madde 20/34-Q: `ENGINE_VERSION` bump'ı (1.6.0 -> 1.7.0,
    # family-level scoring) structural bir score semantics değişikliğidir --
    # TAZE (TTL içinde) ama ESKİ `engine_version` taşıyan bir kayıt cache hit
    # olarak DÖNMEMELİ, aksi halde eski flat-weighted skor yeni family-scored
    # bir sonuçmuş gibi servis edilirdi.
    stale_version_cached = _cached_analysis(age_seconds=60, engine_version="1.6.0")  # taze YAŞ, ESKİ versiyon
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=stale_version_cached, cached_id="stale-version-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not stale_version_cached  # yeniden hesaplandı, cache hit OLMADI
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1
    assert analysis.engine_version == ENGINE_VERSION


def test_analyze_with_id_reuses_cache_when_engine_version_matches(fake_provider):
    # HATA 5B2D, madde 34-R: taze VE AYNI `engine_version` -- normal cache
    # hit davranışı (item Q'nun karşıtı) hâlâ çalışmalı.
    fresh_current_version_cached = _cached_analysis(
        age_seconds=60, engine_version=ENGINE_VERSION, scoring_config_hash=_FAKE_CONFIG_REPO_SCORING_HASH
    )
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=fresh_current_version_cached, cached_id="fresh-id")
    provider = fake_provider(history_df=None)  # get_history çağrılırsa NotImplementedError patlar
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is fresh_current_version_cached
    assert doc_id == "fresh-id"
    assert analysis_repo.added == []


class _ConfiguredWeightsConfigRepo:
    """HATA 5B2D TRUE FINAL COMMIT GATE, madde 8: sabit, EXPLICIT indicator/
    family weight'ler döner -- config-change-invalidates-cache testleri
    (madde B/C) için T0/T1 config'lerini net şekilde ayırt etmek amacıyla."""

    def __init__(self, indicator_weights: dict, family_weights: dict | None = None):
        self._indicator_weights = indicator_weights
        self._family_weights = family_weights

    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return self._indicator_weights
        if key == "technical_family_weights":
            return self._family_weights
        return None


def test_analyze_with_id_cache_miss_when_indicator_weights_changed_within_ttl(fake_provider):
    # madde B / TRUE FINAL COMMIT GATE regresyon kilidi: T0'da CONFIG_A ile
    # cache'lenmiş bir kayıt, T1'de (<TTL) `technical_indicator_weights`
    # DEĞİŞTİYSE (`engine_version` AYNI kalsa bile) artık GEÇERSİZ sayılmalı.
    config_a = dict(DEFAULT_WEIGHTS)
    config_b = dict(DEFAULT_WEIGHTS, rsi=DEFAULT_WEIGHTS["rsi"] + 0.05)  # T1: FARKLI indicator config
    hash_a = compute_scoring_config_hash(config_a, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)

    cached_under_config_a = _cached_analysis(age_seconds=60, scoring_config_hash=hash_a)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached_under_config_a, cached_id="config-a-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_ConfiguredWeightsConfigRepo(config_b),  # T1: config DEĞİŞTİ
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not cached_under_config_a  # cache MISS -- yeniden hesaplandı
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_cache_miss_when_family_weights_changed_within_ttl(fake_provider):
    # madde C: AYNI indicator weights, ama `technical_family_weights`
    # DEĞİŞTİ (F1 -> F2) -- cache GEÇERSİZ sayılmalı.
    family_f1 = {"trend": 1.0 / 3.0, "oscillator_position": 1.0 / 3.0, "momentum_rate": 1.0 / 3.0}
    family_f2 = {"trend": 0.5, "oscillator_position": 0.25, "momentum_rate": 0.25}
    hash_f1 = compute_scoring_config_hash(DEFAULT_WEIGHTS, family_f1)

    cached_under_f1 = _cached_analysis(age_seconds=60, scoring_config_hash=hash_f1)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached_under_f1, cached_id="family-f1-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_ConfiguredWeightsConfigRepo(dict(DEFAULT_WEIGHTS), family_f2),  # T1: family DEĞİŞTİ
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not cached_under_f1  # cache MISS -- yeniden hesaplandı
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_fresh_cache_does_not_bypass_missing_indicator_config(fake_provider):
    # madde D: FRESH, AYNI engine_version'lı bir cache kaydı MEVCUT olsa
    # bile, `technical_indicator_weights` TAMAMEN eksikse FAIL-FAST olmalı --
    # required production config, cache tarafından ASLA bypass edilemez.
    from app.engines.technical.data_quality import DataQualityError

    some_fresh_cache = _cached_analysis(age_seconds=60, scoring_config_hash="irrelevant-would-mismatch-anyway")
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=some_fresh_cache, cached_id="some-fresh-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_MissingIndicatorWeightsConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    with pytest.raises(ValueError) as exc_info:
        engine.analyze_with_id("TEST")

    assert not isinstance(exc_info.value, DataQualityError)
    assert "technical_indicator_weights" in str(exc_info.value)
    assert analysis_repo.added == []  # sahte/eksik bir kayıt PERSIST EDİLMEDİ


def test_analyze_with_id_fresh_cache_does_not_bypass_partial_indicator_config(fake_provider):
    # madde E: partial (stale 6-key) `technical_indicator_weights` + FRESH
    # cache -- AYNI şekilde FAIL-FAST, cache DÖNMEMELİ.
    from app.engines.technical.data_quality import DataQualityError

    some_fresh_cache = _cached_analysis(age_seconds=60, scoring_config_hash="irrelevant-would-mismatch-anyway")
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=some_fresh_cache, cached_id="some-fresh-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_StaleSixKeyConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    with pytest.raises(ValueError):
        engine.analyze_with_id("TEST")

    assert analysis_repo.added == []


def test_analyze_with_id_old_cache_without_scoring_config_hash_is_cache_miss_not_crash(fake_provider):
    # madde G: `scoring_config_hash` alanı eklenmeden ÖNCEki (ama zaten
    # 1.7.0 `engine_version` taşıyan, teorik bir ara-durum) bir kayıt --
    # `None` ile GERÇEK bir hash asla eşleşmez, bu yüzden CACHE MISS olur;
    # `None == str` karşılaştırması hiçbir TypeError/crash ÜRETMEZ.
    old_cache_without_hash = _cached_analysis(age_seconds=60, engine_version=ENGINE_VERSION, scoring_config_hash=None)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=old_cache_without_hash, cached_id="no-hash-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")  # crash ATMAMALI

    assert analysis is not old_cache_without_hash  # cache MISS
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1
    assert analysis.scoring_config_hash is not None  # YENİ kayıt hash'i taşır


def test_analyze_with_id_recomputes_when_stale(fake_provider):
    stale = _cached_analysis(age_seconds=TECHNICAL_CACHE_TTL_SECONDS + 60)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=stale, cached_id="stale-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not stale
    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_recomputes_when_no_cache(fake_provider):
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert doc_id == "new-id"
    assert len(analysis_repo.added) == 1


def test_analyze_with_id_respects_custom_max_age(fake_provider):
    cached = _cached_analysis(age_seconds=30)
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=cached, cached_id="cached-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    # max_age_seconds=10 iken 30 saniyelik kayıt bayat sayılmalı — yeniden hesaplanır.
    analysis, doc_id = engine.analyze_with_id("TEST", max_age_seconds=10)

    assert analysis is not cached
    assert doc_id == "new-id"


def test_analyze_with_id_includes_ema_slope_component(fake_provider):
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert "ema_slope" in analysis.components
    assert "ema_slope" in analysis.indicators
    assert -100 <= analysis.technical_score <= 100


def test_analyze_with_id_rejects_stale_six_key_weight_config(fake_provider):
    # HATA 5B2D FINAL PRE-COMMIT GATE, madde 8: partial `technical_indicator_
    # weights` (eski AŞAMA 48/9-öncesi 6-key doküman, `ema_slope` eksik)
    # artık SESSİZCE `DEFAULT_WEIGHTS` ile tamamlanmaz -- fail-fast. Bu,
    # HATA 5B2C'nin kök nedenini (aynı mekanizma) kod seviyesinde kapatır.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_StaleSixKeyConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    with pytest.raises(ValueError):
        engine.analyze_with_id("TEST")


def test_analyze_with_id_includes_relative_strength_class(fake_provider):
    # AŞAMA 48/17: benchmark (XU100) verisi de aynı fake_provider'dan geliyor
    # (aynı history_df hem asset hem benchmark için döner) — gerçek Firestore'a
    # hiç dokunulmadan (_FakeBenchmarkCacheRepo) relative_strength hesaplanmalı.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert analysis.relative_strength_class in ("OUTPERFORMING", "UNDERPERFORMING", "IN_LINE", "UNKNOWN")


def test_analyze_with_id_includes_multi_timeframe_alignment(fake_provider):
    # AŞAMA 48/18: haftalık yön, günlük df'ten (ek istek olmadan) türetilir.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert isinstance(analysis.mtf_aligned, bool)
    assert analysis.mtf_consensus in ("UP", "DOWN", "FLAT", "CONFLICTING", "MIXED", "UNKNOWN")


# ---------------------------------------------------------------------------
# HATA 2A (25.08.2026): günlük teknik analiz yalnızca TAMAMLANMIŞ barları
# kullanmalı. Aşağıdaki senaryo, "bugünün" (henüz oluşmakta olan) barını,
# D-1'den (son tamamlanmış bar) KASITLI OLARAK çok farklı kılacak şekilde
# kurar (büyük fiyat sıçraması + anormal hacim + doji şekli) — böylece
# motorun bu farkı GÖRÜP GÖRMEDİĞİ (yanlışlıkla sızdırıp sızdırmadığı)
# doğrudan gözlemlenebilir.
# ---------------------------------------------------------------------------

_D1_DATE = "2026-08-25"  # Sali — son TAMAMLANMIŞ gün
_TODAY_DATE = "2026-08-26"  # Carsamba — piyasa acikken hala olusan gun


def _breakout_scenario_df() -> pd.DataFrame:
    # index 0-39: 90 -> 130 yukselis (bar 39 acik bir fraktal swing high olur)
    # index 40-78: 130 -> 105 alcalis/konsolidasyon (D-1 direncin ALTINDA kalir)
    # index 79 ("bugun"): 135 -> direncin (130) USTUNE sicrama + doji sekli + cok dusuk hacim
    up = np.linspace(90.0, 130.0, 40)
    down = np.linspace(130.0, 105.0, 39)
    closes = np.concatenate([up, down])  # 79 gun, son (D-1) = 105

    n_history = len(closes)
    # HATA 3C (26.08.2026): naif ardışık takvim günü yerine gerçek BIST
    # işlem günleri kullanılıyor (bkz. `_bist_trading_days`) — 79 takvim
    # günü 2026-07-15 (Demokrasi ve Milli Birlik Günü) gibi resmi tatilleri
    # içerebiliyordu, bu da `UNEXPECTED_TRADING_SESSION` ile veto ediyordu.
    trading_days = _bist_trading_days(date(2026, 8, 25), n_history)
    history_index = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in trading_days])

    df = pd.DataFrame(
        {
            "Open": closes - 0.3,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": np.full(n_history, 5000.0),
        },
        index=history_index,
    )
    # D-1: buyuk govdeli, doji OLMAYAN normal bir bar + normal hacim.
    df.loc[df.index[-1], ["Open", "High", "Low", "Close", "Volume"]] = [100.0, 106.0, 99.0, 105.0, 5200.0]

    today_row = pd.DataFrame(
        {"Open": [135.0], "High": [140.0], "Low": [130.0], "Close": [135.05], "Volume": [50.0]},
        index=[pd.Timestamp(_TODAY_DATE, tz=TZ)],
    )
    return pd.concat([df, today_row])


def _run_breakout_scenario(fake_provider, now: datetime):
    provider = fake_provider(history_df=_breakout_scenario_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(cached=None, cached_id=None),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    analysis, _ = engine.analyze_with_id("TEST", now=now)
    return analysis


def test_market_open_uses_d_minus_1_as_market_data_as_of(fake_provider):
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)  # piyasa acik
    analysis = _run_breakout_scenario(fake_provider, now_open)

    assert analysis.market_data_as_of is not None
    assert analysis.market_data_as_of.date() == pd.Timestamp(_D1_DATE).date()


def test_market_closed_past_finalization_delay_uses_today(fake_provider):
    now_closed = datetime(2026, 8, 26, 19, 0, tzinfo=TZ)  # kapanis + finalization payi gecti
    analysis = _run_breakout_scenario(fake_provider, now_closed)

    assert analysis.market_data_as_of is not None
    assert analysis.market_data_as_of.date() == pd.Timestamp(_TODAY_DATE).date()


def test_intraday_breakout_does_not_create_daily_breakout_candidate(fake_provider):
    # Piyasa acikken: D-1 kapanisi (105) direncin (130) ALTINDA -> daily breakout OLUSMAMALI,
    # "bugunku" 135 sicramasi goz ardi edilmis olmali.
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)
    analysis = _run_breakout_scenario(fake_provider, now_open)

    assert analysis.breakout is None


def test_completed_close_above_resistance_creates_daily_breakout_candidate(fake_provider):
    # Ayni veri, ama piyasa kapanip finalization payi da gectikten SONRA "bugun" (135, direncin
    # ustunde) artik TAMAMLANMIS kabul edilir -> daily breakout adayi olusmali.
    now_closed = datetime(2026, 8, 26, 19, 0, tzinfo=TZ)
    analysis = _run_breakout_scenario(fake_provider, now_closed)

    assert analysis.breakout is not None
    assert analysis.breakout["direction"] == "BULLISH"


def test_partial_bar_doji_pattern_not_used_when_market_open(fake_provider):
    # "Bugunku" satir bilincli olarak doji sekilli kuruldu (Open≈Close, uzun fitiller);
    # piyasa acikken bu satir disarida birakildigindan DOJI raporlanmamali.
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)
    analysis = _run_breakout_scenario(fake_provider, now_open)

    assert "DOJI" not in analysis.candlestick_patterns


def test_partial_bar_doji_pattern_used_after_finalization(fake_provider):
    now_closed = datetime(2026, 8, 26, 19, 0, tzinfo=TZ)
    analysis = _run_breakout_scenario(fake_provider, now_closed)

    assert "DOJI" in analysis.candlestick_patterns


def test_partial_day_volume_not_used_in_relative_volume_when_market_open(fake_provider):
    # "Bugunku" hacim (50) tarihin en dusugu -- eger yanlislikla kullanilsaydi
    # relative_volume LOW/cok dusuk cikardi. D-1'in normal hacmi (5200) kullanildiginda
    # NORMAL/HIGH civarinda kalmali, asla en dusuk sinifta olmamali.
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)
    analysis = _run_breakout_scenario(fake_provider, now_open)

    assert analysis.relative_volume_class != "LOW"


def test_daily_rsi_matches_manually_precomputed_completed_series(fake_provider):
    # Motorun RSI'si, "bugunku" satiri elle cikarilmis AYNI seri uzerinde
    # dogrudan hesaplanan RSI ile BIREBIR aynı olmalı (float esitligi) --
    # bu, RSI'nin filtrelenmis df'ten geldigini, ham df'ten degil, kanitlar.
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)
    raw_df = _breakout_scenario_df()
    analysis = _run_breakout_scenario(fake_provider, now_open)

    expected_rsi = round(float(ind.rsi(raw_df["Close"].iloc[:-1]).iloc[-1]), 2)
    assert analysis.indicators["rsi"] == pytest.approx(expected_rsi, abs=1e-9)


def test_completed_history_technical_score_is_deterministic(fake_provider):
    now_open = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)

    analysis1 = _run_breakout_scenario(fake_provider, now_open)
    analysis2 = _run_breakout_scenario(fake_provider, now_open)

    assert analysis1.technical_score == analysis2.technical_score
    assert analysis1.indicators == analysis2.indicators


# ---------------------------------------------------------------------------
# HATA 2B (25.08.2026): BIST'in resmi işlem takvimine göre beklenen ama
# seride bulunmayan bir işlem günü varsa (bkz. 24.08.2026 örneği) analiz hiç
# ÜRETİLMEMELİ (HARD VETO) — completed-bar filtresinden SONRA, herhangi bir
# gösterge hesaplanmadan ÖNCE çalışan check_trading_day_continuity() ile.
# ---------------------------------------------------------------------------


def _history_with_trading_day_gap(missing_date: str) -> pd.DataFrame:
    # HATA 3C (26.08.2026): naif `pd.bdate_range` yerine gerçek BIST işlem
    # günleri (`expected_trading_sessions`) kullanılıyor — 2026-04-01/08-24
    # aralığı 04-23/05-01/05-19/05-27-29/07-15 resmi tatillerini içeriyor,
    # `pd.bdate_range` bunları BİLMEDİĞİNDEN `UNEXPECTED_TRADING_SESSION`
    # ile veto ediliyordu.
    sessions = expected_trading_sessions(date(2026, 4, 1), date(2026, 8, 24))
    dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in sessions if d.isoformat() != missing_date])
    rng = np.random.default_rng(3)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    return pd.DataFrame(
        {
            "Open": closes - 0.2,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, len(dates)),
        },
        index=dates,
    )


def test_analyze_with_id_raises_and_does_not_persist_on_trading_day_gap(fake_provider):
    from app.engines.technical.data_quality import TradingDayContinuityError

    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_history_with_trading_day_gap("2026-06-17"))
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    now = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        engine.analyze_with_id("TEST", now=now)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-06-17").date()]
    # HATA 2B madde 11: veto nedeniyle sahte/eksik bir kayıt Firestore'a YAZILMAMALI.
    assert analysis_repo.added == []


def test_analyze_with_id_passes_when_no_trading_day_gap(fake_provider):
    # "" hiçbir gerçek tarihle eşleşmediğinden hiçbir gün çıkarılmaz — tam,
    # boşluksuz bir BIST işlem günleri serisi.
    df = _history_with_trading_day_gap("")
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=df)
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    now = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)

    analysis, _ = engine.analyze_with_id("TEST", now=now)

    assert analysis is not None
    assert len(analysis_repo.added) == 1


# ---------------------------------------------------------------------------
# HATA 2C (25.08.2026): pre-roll / leading-edge doğrulama sözleşmesi —
# `analysis_start`'tan (now - 6 ay) ÖNCEye uzanan bir gözlem bölgesinde en az
# bir bar bulunması "VERIFIED_PRE_WINDOW", bulunmaması "LEADING_EDGE_
# UNVERIFIED" olarak işaretlenir; ikinci durum ARTIK otomatik HARD VETO
# DEĞİLDİR (bkz. history_window.py). NOT: FakeMarketDataProvider start/end
# parametrelerini YOK SAYAR (bkz. conftest.py) — bu yüzden aşağıdaki
# testlerde motora verilen tam DataFrame'in KENDİSİ senaryoyu belirler,
# provider'a "hangi aralık istendiği" değil.
# ---------------------------------------------------------------------------

_NOW_2C = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)  # analysis_start = 2026-02-25, boundary = 2026-08-24
_ANALYSIS_START_2C = pd.Timestamp("2026-02-25").date()
_BOUNDARY_2C = pd.Timestamp("2026-08-24").date()


def _bday_df(start: str, end: str, base_price: float = 100.0, seed: int = 7) -> pd.DataFrame:
    # HATA 3C (26.08.2026): naif `pd.bdate_range` yerine gerçek BIST işlem
    # günleri (`expected_trading_sessions`) — bu aralık birden fazla 2026
    # resmi tatilini (03-20, 04-23, 05-01, 05-19, 05-27/28/29, 07-15) kapsıyor,
    # `pd.bdate_range` bunları BİLMEDİĞİNDEN `UNEXPECTED_TRADING_SESSION`
    # ile veto ediliyordu.
    sessions = expected_trading_sessions(pd.Timestamp(start).date(), pd.Timestamp(end).date())
    dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in sessions])
    rng = np.random.default_rng(seed)
    closes = base_price + np.cumsum(rng.normal(0, 1, len(dates)))
    return pd.DataFrame(
        {
            "Open": closes - 0.2,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, len(dates)),
        },
        index=dates,
    )


def _run_2c_scenario(fake_provider, df: pd.DataFrame):
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=df)
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )
    return engine.analyze_with_id("TEST", now=_NOW_2C), analysis_repo


def test_established_symbol_clean_history_is_verified_pre_window(fake_provider):
    # analysis_start'tan (2026-02-25) çok ÖNCE (2025-09-01) başlayan, tamamen
    # kesintisiz bir seri -- "köklü/established" bir sembolü simüle eder.
    df = _bday_df("2025-09-01", "2026-08-24")

    (analysis, _doc_id), analysis_repo = _run_2c_scenario(fake_provider, df)

    assert analysis.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert len(analysis_repo.added) == 1


def test_established_symbol_gap_after_analysis_start_still_hard_vetoes(fake_provider):
    from app.engines.technical.data_quality import TradingDayContinuityError

    df = _bday_df("2025-09-01", "2026-08-24")
    df = df.drop(pd.Timestamp("2026-06-17", tz=TZ))  # analysis_start'tan SONRA bir boşluk

    with pytest.raises(TradingDayContinuityError) as exc_info:
        _run_2c_scenario(fake_provider, df)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-06-17").date()]


def test_pre_roll_internal_gap_before_analysis_start_is_not_a_veto(fake_provider):
    # Boşluk analysis_start'tan ÖNCE (pre-roll bölgesinin içinde) -- pre-roll
    # barları hiçbir zaman continuity kontrolüne dahil edilmez, sadece "kanıt
    # var mı" sorusuna cevap verir (bkz. resolve_expected_start).
    df = _bday_df("2025-09-01", "2026-08-24")
    df = df.drop(pd.Timestamp("2025-10-15", tz=TZ))  # analysis_start'tan ONCE bir boşluk

    (analysis, _doc_id), analysis_repo = _run_2c_scenario(fake_provider, df)

    assert analysis.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert len(analysis_repo.added) == 1


def test_new_listing_no_pre_roll_evidence_passes_as_unverified(fake_provider):
    # İlk bar analysis_start'tan (2026-02-25) SONRA -- pre-roll'da hiç kanıt
    # yok. Bu ARTIK otomatik PRE_LISTING/HARD_VETO sayılmaz (HATA 2C öncesi
    # tasarımdan fark budur) -- sembolün GÖZLEMLENEN ilk barından itibaren
    # normal continuity kontrolüne tabi olur.
    df = _bday_df("2026-05-01", "2026-08-24")  # ~82 iş günü, MIN_HISTORY_DAYS(60) üstü

    (analysis, _doc_id), analysis_repo = _run_2c_scenario(fake_provider, df)

    assert analysis.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert len(analysis_repo.added) == 1


def test_new_listing_with_middle_gap_still_hard_vetoes(fake_provider):
    from app.engines.technical.data_quality import TradingDayContinuityError

    df = _bday_df("2026-05-01", "2026-08-24")
    df = df.drop(pd.Timestamp("2026-06-17", tz=TZ))  # gözlemlenen ilk bardan SONRAKİ bir boşluk

    with pytest.raises(TradingDayContinuityError) as exc_info:
        _run_2c_scenario(fake_provider, df)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-06-17").date()]


def test_new_listing_with_insufficient_history_raises_insufficient_history_not_veto(fake_provider):
    from app.engines.technical.data_quality import DataQualityError

    # Cok yeni bir sembol: ilk bar boundary'ye (2026-08-24) cok yakin, kesintisiz
    # ama MIN_HISTORY_DAYS(60)'in COK altinda -- continuity kontrolu GECER
    # (kesinti yok), ama check_data_quality INSUFFICIENT_HISTORY ile veto eder.
    df = _bday_df("2026-08-01", "2026-08-24")  # ~17 iş günü

    with pytest.raises(DataQualityError) as exc_info:
        _run_2c_scenario(fake_provider, df)

    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_pre_roll_content_never_leaks_into_score_or_enrichment(fake_provider):
    # analysis_start'tan (2026-02-25) İTİBAREN BİREBİR AYNI "kuyruk" (tail),
    # ama analysis_start'tan ÖNCEki pre-roll bölgesi biri "sakin" (calm) biri
    # aşırı oynak (wild) iki AYRI DataFrame -- pre-roll'un skora/indikatörlere/
    # zenginleştirmeye SIZMADIĞI, yalnızca "kanıt var mı" sorusuna cevap
    # verdiği doğrudan kanıtlanır.
    tail = _bday_df(_ANALYSIS_START_2C.isoformat(), _BOUNDARY_2C.isoformat(), base_price=100.0, seed=99)

    pre_roll_index = pd.bdate_range(start="2025-09-01", end="2026-02-24", tz=TZ)
    n_pre_roll = len(pre_roll_index)
    calm_pre_roll = pd.DataFrame(
        {"Open": 50.0, "High": 50.5, "Low": 49.5, "Close": 50.0, "Volume": 1000},
        index=pre_roll_index,
    )
    wild_close = np.resize([1.0, 99999.0], n_pre_roll)
    wild_pre_roll = pd.DataFrame(
        {
            "Open": wild_close - 0.5,
            "High": wild_close + 1.0,
            "Low": wild_close - 1.0,
            "Close": wild_close,
            "Volume": np.resize([1, 9_999_999], n_pre_roll),
        },
        index=pre_roll_index,
    )

    df_calm = pd.concat([calm_pre_roll, tail]).sort_index()
    df_wild = pd.concat([wild_pre_roll, tail]).sort_index()

    (analysis_calm, _), _ = _run_2c_scenario(fake_provider, df_calm)
    (analysis_wild, _), _ = _run_2c_scenario(fake_provider, df_wild)

    assert analysis_calm.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert analysis_wild.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert analysis_calm.technical_score == analysis_wild.technical_score
    assert analysis_calm.components == analysis_wild.components
    assert analysis_calm.indicators == analysis_wild.indicators
    assert analysis_calm.market_structure == analysis_wild.market_structure
    assert analysis_calm.signal_class == analysis_wild.signal_class
    assert analysis_calm.investment_horizon == analysis_wild.investment_horizon
    assert analysis_calm.mtf_aligned == analysis_wild.mtf_aligned
    assert analysis_calm.mtf_consensus == analysis_wild.mtf_consensus


# ---------------------------------------------------------------------------
# HATA 3D, madde 22: normalizasyon `resolve_expected_start()`'TAN ÖNCE
# çalışmalıdır -- aksi halde pre-roll bölgesindeki bir "phantom" (Yahoo'nun
# planlı bir tatilde ürettiği sahte) bar, sembolün analysis_start'tan ÖNCE
# ZATEN işlem gördüğüne dair YANLIŞ bir kanıt (VERIFIED_PRE_WINDOW) üretebilir.
# Bu test, HATA 2C (pre-roll evidence) ile HATA 3D (normalization) arasındaki
# sıralama sözleşmesini kilitler.
# ---------------------------------------------------------------------------


def test_pre_roll_region_with_only_a_phantom_holiday_bar_is_not_verified_pre_window(fake_provider):
    # Pre-roll bölgesindeki TEK bar, 2026-01-01 (Yılbaşı -- planlı tam gün
    # kapanış) tarihli bir "phantom" bar (bkz. HATA 3D: Open=High=Low=Close=
    # önceki kapanış, Volume=0) -- normalize edilmeden ÖNCE bu, index'te
    # analysis_start'tan (2026-02-25) daha ESKİ bir tarih olarak GÖRÜNÜR ve
    # eski (HATA 3D öncesi) kodda yanlışlıkla "kanıt" sayılırdı. Normalization
    # bunu düşürdükten SONRA pre-roll bölgesi tamamen BOŞ kalır.
    tail = _bday_df(_ANALYSIS_START_2C.isoformat(), _BOUNDARY_2C.isoformat(), base_price=100.0, seed=99)
    phantom_pre_roll = pd.DataFrame(
        {"Open": [100.0], "High": [100.0], "Low": [100.0], "Close": [100.0], "Volume": [0]},
        index=[pd.Timestamp("2026-01-01", tz=TZ)],
    )
    df = pd.concat([phantom_pre_roll, tail]).sort_index()

    (analysis, _doc_id), analysis_repo = _run_2c_scenario(fake_provider, df)

    assert analysis.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert len(analysis_repo.added) == 1
    dropped = {d["date"]: d["classification"] for d in analysis.normalized_dropped_sessions}
    assert dropped.get("2026-01-01") == "PLANNED_FULL_DAY_CLOSURE"


def test_pre_roll_region_with_real_evidence_plus_phantom_bar_still_verifies(fake_provider):
    # Phantom barın YANINDA GERÇEK bir pre-roll bar da varsa (sembol gerçekten
    # analysis_start'tan önce işlem görmüş), normalization phantom'u düşürse
    # bile GERÇEK kanıt hâlâ VERIFIED_PRE_WINDOW üretmelidir -- normalization
    # yalnızca sahte barı temizler, gerçek kanıtı ETKİLEMEZ.
    tail = _bday_df(_ANALYSIS_START_2C.isoformat(), _BOUNDARY_2C.isoformat(), base_price=100.0, seed=99)
    real_pre_roll = pd.DataFrame(
        {"Open": [95.0], "High": [96.0], "Low": [94.0], "Close": [95.5], "Volume": [12345]},
        index=[pd.Timestamp("2025-09-01", tz=TZ)],
    )
    phantom_pre_roll = pd.DataFrame(
        {"Open": [100.0], "High": [100.0], "Low": [100.0], "Close": [100.0], "Volume": [0]},
        index=[pd.Timestamp("2026-01-01", tz=TZ)],
    )
    df = pd.concat([real_pre_roll, phantom_pre_roll, tail]).sort_index()

    (analysis, _doc_id), analysis_repo = _run_2c_scenario(fake_provider, df)

    assert analysis.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert len(analysis_repo.added) == 1
    dropped = {d["date"]: d["classification"] for d in analysis.normalized_dropped_sessions}
    assert dropped.get("2026-01-01") == "PLANNED_FULL_DAY_CLOSURE"


# ---------------------------------------------------------------------------
# HATA 5C3A (28.08.2026) — "Sinyal Mutabakatı" (confidence) + "Veri Kapsamı"
# (evidence_coverage) implementasyonu: gerçek analyze_with_id() akışında
# permanent regresyon kilitleri.
# ---------------------------------------------------------------------------


def test_technical_analysis_old_confidence_float_document_still_parses_after_5c3a():
    # HATA 5C3A: `confidence: float | None`'a geçiş -- eski TÜM kayıtlar
    # gerçek bir float taşıdığından geriye dönük okuma BOZULMAZ, migration YOK.
    old_style_doc = {
        "asset": "TEST",
        "technical_score": 42.0,
        "trend": "BULLISH",
        "confidence": 0.9,
        "components": {"rsi": 42.0},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**old_style_doc)
    assert analysis.confidence == 0.9
    # `evidence_coverage` bu alan eklenmeden önceki kayıtlarda yok -- None.
    assert analysis.evidence_coverage is None


def test_technical_analysis_new_none_confidence_document_parses():
    # HATA 5C3A: `technical_score is None` iken üretilen YENİ `confidence:
    # null` kaydı hatasız parse edilmeli (0.0 UYDURULMADI).
    new_style_doc = {
        "asset": "TEST",
        "technical_score": None,
        "trend": None,
        "confidence": None,
        "evidence_coverage": 0.0,
        "components": {},
        "indicators": {"rsi": 55.0},
        "created_at": datetime.now(timezone.utc),
    }
    analysis = TechnicalAnalysis(**new_style_doc)
    assert analysis.confidence is None
    assert analysis.evidence_coverage == 0.0


def test_analyze_with_id_evidence_coverage_matches_full_availability(fake_provider):
    # `_FakeConfigRepo` -> DEFAULT_WEIGHTS (indicator) + eşit 1/3 (family,
    # doküman yok). Gerçek fiyat serisinde 7/7 component available olduğundan
    # (bkz. `test_analyze_with_id_includes_ema_slope_component`) evidence_
    # coverage tam olmalı.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert len(analysis.components) == 7
    assert analysis.evidence_coverage == pytest.approx(1.0, abs=1e-9)
    assert analysis.confidence is not None
    assert 0.0 <= analysis.confidence <= 1.0


def test_analyze_with_id_evidence_coverage_is_zero_when_technical_score_unavailable(fake_provider, monkeypatch):
    # HATA 5C2B madde 4: `technical_score is None` olsa BİLE evidence_coverage
    # HER ZAMAN hesaplanabilir bir [0,1] orandır, None DEĞİLDİR.
    monkeypatch.setattr(
        "app.engines.technical.engine.aggregate_available_scores",
        lambda *args, **kwargs: None,
    )
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert analysis.technical_score is None
    assert analysis.confidence is None
    assert analysis.evidence_coverage is not None
    assert 0.0 <= analysis.evidence_coverage <= 1.0


def test_analyze_with_id_confidence_uses_full_precision_family_scores_not_rounded(fake_provider, monkeypatch):
    # HATA 5C3A madde 7 (double-rounding regresyon kilidi): compute_family_
    # agreement() PERSISTED (round(2)) stored_family_scores DEĞİL, tam-
    # hassasiyetli raw_family_scores ile çağrılmalı -- aksi halde bir
    # family'nin skoru ±15 sınırına çok yakınken persisted rounding,
    # agreement'ın yönünü YANLIŞLIKLA değiştirebilirdi (HATA 5B2D'nin "double
    # rounding" dersi, bkz. scoring.py::aggregate_available_components).
    import app.engines.technical.engine as engine_module

    real_compute_family_agreement = engine_module.compute_family_agreement
    captured = {}

    def _spy(raw_family_scores, final_score, family_weights):
        captured["raw_family_scores"] = dict(raw_family_scores)
        return real_compute_family_agreement(raw_family_scores, final_score, family_weights)

    monkeypatch.setattr(engine_module, "compute_family_agreement", _spy)

    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert "raw_family_scores" in captured
    rounded_would_be = {k: round(v, 2) for k, v in captured["raw_family_scores"].items()}
    # Sabit seed'li (`_real_history_df`, seed=42) gerçek piyasa verisiyle en az
    # bir family skoru zaten kendi 2-ondalık yuvarlamasına TAM EŞİT DEĞİLDİR --
    # bu, motorun GERÇEKTEN tam-hassasiyetli değeri kullandığını, persisted
    # (`analysis.family_scores`) rounded değerleri DEĞİL, kanıtlar.
    assert captured["raw_family_scores"] != rounded_would_be
    assert any(
        captured["raw_family_scores"][k] != analysis.family_scores.get(k) for k in captured["raw_family_scores"]
    )


def test_analyze_with_id_confidence_is_independent_of_volume(fake_provider):
    # HATA 5C3A madde 9: eski "volume_confirmation" (0.2 katsayı, volume_sma
    # fallback 0.5) confidence'tan TAMAMEN KALDIRILDI -- AYNI fiyat serisiyle,
    # yalnızca Volume sütunu dramatik şekilde farklı iki DataFrame AYNI
    # confidence'ı üretmeli (volume artık confidence'ı hiç ETKİLEMEZ).
    low_volume_df = _real_history_df()
    high_volume_df = low_volume_df.copy()
    high_volume_df["Volume"] = high_volume_df["Volume"] * 1000

    analysis_low, _ = TechnicalAnalysisEngine(
        provider=fake_provider(history_df=low_volume_df),
        config_repo=_FakeConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(cached=None, cached_id=None),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    ).analyze_with_id("TEST")

    analysis_high, _ = TechnicalAnalysisEngine(
        provider=fake_provider(history_df=high_volume_df),
        config_repo=_FakeConfigRepo(),
        analysis_repo=_FakeTechnicalAnalysisRepo(cached=None, cached_id=None),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    ).analyze_with_id("TEST")

    assert analysis_low.confidence == analysis_high.confidence
    assert analysis_low.technical_score == analysis_high.technical_score
    # Volume enrichment/sinyal tarafında YAŞAMAYA DEVAM ediyor -- yalnızca
    # confidence'la bağlantısı kesildi, volume analizi SİLİNMEDİ.
    assert "volume" in analysis_low.indicators
    assert "volume_sma" in analysis_low.indicators


def test_analyze_with_id_recomputes_fresh_1_7_record_due_to_version_and_parses_legacy_float_confidence(fake_provider):
    # RESPONSIBILITY A -- 1.7.0 GERİYE DÖNÜK UYUMLULUK / eski confidence
    # şeklinin parse edilmesi. `age_seconds=60` -- kayıt TTL açısından TAZE
    # (900s'lik pencerenin çok içinde); cache MISS zaman-bazlı bayatlıktan
    # DEĞİL, `engine_version="1.7.0" != ENGINE_VERSION` uyuşmazlığından
    # kaynaklanıyor (HATA 5C3A madde 20). Yeniden hesaplanan güncel kayıt
    # `confidence`'ı (float veya None) VE `evidence_coverage`'ı taşımalı.
    # Bu test SPESİFİK OLARAK 1.8->1.9 geçişini DEĞİL, 1.7'nin (herhangi bir
    # sonraki sürüme göre) hâlâ eski float confidence şeklini doğru
    # PARSE ETTİĞİNİ doğrular -- bkz. aşağıdaki AYRI 1.8->1.9 testi
    # (RESPONSIBILITY B) spesifik cache-invalidation semantics'i için.
    old_1_7_cache = _cached_analysis(age_seconds=60, engine_version="1.7.0")
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=old_1_7_cache, cached_id="old-1-7-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert analysis is not old_1_7_cache  # cache MISS -- yeniden hesaplandı
    assert analysis.engine_version == ENGINE_VERSION
    assert doc_id == "new-id"
    assert old_1_7_cache.confidence == 0.9  # eski float kayıt hâlâ parse edilebiliyor
    assert analysis.evidence_coverage is not None


def test_analyze_with_id_cached_1_8_record_misses_under_1_9_engine_version(fake_provider):
    # RESPONSIBILITY B -- HATA 7C-FIX'in SPESİFİK cache-invalidation
    # semantics'i: `check_alignment()` düzeltmesi (eksik/UNKNOWN bir MTF
    # zaman diliminin artık "uyumlu" sayılmaması) ENGINE_VERSION'ı 1.8.0'dan
    # 1.9.0'a yükseltti (bkz. engine.py değişiklik geçmişi). Bu test, TTL
    # içinde (fresh) bir 1.8.0 kaydının -- 1.7.0 testinin aksine eski bir
    # confidence şekli parse etme senaryosu DEĞİL, doğrudan bu spesifik
    # versiyon geçişi -- artık cache HIT ÜRETMEDİĞİNİ, gerçek 1.9.0
    # motoruyla YENİDEN hesaplandığını ve dönen doküman kimliğinin eski
    # (cache'lenmiş) kayıt DEĞİL, yeni persist edilen kayıt olduğunu kanıtlar.
    old_1_8_cache = _cached_analysis(
        age_seconds=60, engine_version="1.8.0", scoring_config_hash=_FAKE_CONFIG_REPO_SCORING_HASH
    )
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=old_1_8_cache, cached_id="old-1-8-id")
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_FakeConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, doc_id = engine.analyze_with_id("TEST")

    assert ENGINE_VERSION == "1.9.0"  # bu testin varsaydığı ön koşul -- kayarsa test adı/yorumu da güncellenmeli
    assert analysis is not old_1_8_cache  # cache MISS -- age/hash eşleşse bile engine_version farklı
    assert analysis.engine_version == "1.9.0"
    assert doc_id == "new-id"  # eski "old-1-8-id" DEĞİL -- gerçekten yeniden persist edildi
