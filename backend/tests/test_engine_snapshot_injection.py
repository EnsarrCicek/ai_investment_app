"""HATA 12M — `compute_technical_analysis()` parity + snapshot-injection
izolasyon testleri.

Amaç: `engine.py`'nin dependency-injection refactor'ünün (üretim `analyze_
with_id()` yolu ile paylaşılan `compute_technical_analysis()` fonksiyonu
arasında) HİÇBİR davranış farkı YARATMADIĞINI ve `benchmark_close_series`
verildiğinde `get_benchmark_close_series()`'in (dolayısıyla provider/
benchmark cache'in) GERÇEKTEN hiç çağrılmadığını kanıtlamak -- ileride
yazılacak prospective evidence-capture modülünün bu iki garantiye
güvenebilmesi için.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import check_data_quality, check_raw_ohlcv_integrity, check_trading_day_continuity
from app.engines.technical.engine import (
    DEFAULT_WEIGHTS,
    ENGINE_VERSION,
    MIN_HISTORY_DAYS,
    TechnicalAnalysisEngine,
    compute_technical_analysis,
)
from app.engines.technical.history_window import compute_history_window, resolve_expected_start
from app.engines.technical.scoring import (
    DEFAULT_TECHNICAL_FAMILY_WEIGHTS,
    compute_scoring_config_hash,
    resolve_family_weights,
    resolve_indicator_weights,
)
from app.models.technical_analysis import TechnicalAnalysis
from app.services.market_data.benchmark_service import get_benchmark_close_series
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.services.market_data.trading_calendar import (
    expected_trading_sessions,
    normalize_bist_daily_sessions,
    session_normalization_to_dict,
)

TZ = ZoneInfo("Europe/Istanbul")


def _bist_trading_days(end: date, n: int) -> list[date]:
    search_start = end - timedelta(days=n * 2 + 10)
    sessions = expected_trading_sessions(search_start, end)
    assert sessions is not None and len(sessions) >= n
    return sessions[-n:]


def _history_df(rows: int = 120, seed: int = 42) -> pd.DataFrame:
    """`test_technical_engine.py::_real_history_df()` ile AYNI desen (kasıtlı
    olarak buradan import EDİLMEDİ -- mevcut test suite konvansiyonu her
    dosyanın kendi bağımsız fixture'larını taşımasıdır)."""
    rng = np.random.default_rng(seed)
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


class _FakeConfigRepo:
    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        return None


class _EmptyBenchmarkCacheRepo:
    """Her zaman "önbellek yok" döner -- benchmark her seferinde provider'dan
    (fake, ağ isteği yapmaz) okunur."""

    def get(self):
        return None

    def set(self, close_by_date, fetched_at):
        pass


class _PoisonProvider:
    """`get_history()` çağrılırsa test'i FAIL ettirir -- `benchmark_close_
    series` enjekte edildiğinde provider'a HİÇ dokunulmadığını kanıtlamak
    için (bkz. HATA 12J/12K benchmark cache kimlik riski)."""

    def get_history(self, *args, **kwargs):
        raise AssertionError("get_history() cagrildi -- benchmark_close_series enjeksiyonu izolasyonu BOZULDU")


class _PoisonBenchmarkCacheRepo:
    def get(self):
        raise AssertionError("benchmark cache .get() cagrildi -- benchmark_close_series enjeksiyonu izolasyonu BOZULDU")

    def set(self, *args, **kwargs):
        raise AssertionError("benchmark cache .set() cagrildi -- benchmark_close_series enjeksiyonu izolasyonu BOZULDU")


class _FakeTechnicalAnalysisRepo:
    def get_latest_with_id(self, asset):
        return None, None

    def add(self, analysis):
        return "new-id"


def _resolve_head(df_raw: pd.DataFrame, symbol: str, config_repo, now=None):
    """`analyze_with_id()`'in DEĞİŞMEYEN girdi-sözleşmesi HEAD'ini (provider
    fetch HARİÇ -- `df_raw` zaten "provider'dan gelmiş" ham geçmiş olarak
    verilir) birebir tekrarlar, `compute_technical_analysis()`'in
    beklediği tüm resolved argümanları üretir. Bu, ileride yazılacak
    evidence-capture modülünün YAPMASI GEREKEN adımların AYNISIDIR."""
    weights = resolve_indicator_weights(config_repo.get_raw("technical_indicator_weights"))
    family_weights = resolve_family_weights(config_repo.get_raw("technical_family_weights"))
    scoring_config_hash = compute_scoring_config_hash(weights, family_weights)

    history_window = compute_history_window(now)
    provider_history = filter_completed_daily_bars(df_raw, now=now)
    provider_history, session_normalization_result = normalize_bist_daily_sessions(
        provider_history, symbol=symbol, provider="yahoo_finance"
    )
    expected_start, validation_status = resolve_expected_start(provider_history, history_window.analysis_start)
    check_trading_day_continuity(provider_history, symbol, now=now, expected_start=expected_start)
    df = provider_history[provider_history.index.date >= expected_start]
    check_raw_ohlcv_integrity(df, symbol)
    check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=now)

    return (
        df,
        weights,
        family_weights,
        scoring_config_hash,
        validation_status.value,
        session_normalization_to_dict(session_normalization_result),
    )


def test_compute_technical_analysis_matches_analyze_with_id_via_provider_path(fake_provider):
    """Üretim yolu (`analyze_with_id`, provider/cache'ten otomatik benchmark
    çekimi) ile `compute_technical_analysis()`'in DOĞRUDAN, aynı resolved
    girdilerle çağrılması AYNI (created_at HARİÇ) sonucu üretmeli --
    HATA 12M'in "iki yol AYNI hesaplama mantığına yakınsamalı" gereksinimi."""
    df_raw = _history_df()
    provider = fake_provider(history_df=df_raw)
    config_repo = _FakeConfigRepo()
    benchmark_cache_repo = _EmptyBenchmarkCacheRepo()

    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=config_repo,
        analysis_repo=_FakeTechnicalAnalysisRepo(),
        benchmark_cache_repo=benchmark_cache_repo,
    )
    legacy_analysis, _ = engine.analyze_with_id("TEST")

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        df_raw, "TEST", config_repo
    )
    direct_analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=provider,
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
    )

    legacy_dump = legacy_analysis.model_dump(exclude={"created_at"})
    direct_dump = direct_analysis.model_dump(exclude={"created_at"})
    assert legacy_dump == direct_dump


def test_compute_technical_analysis_injected_benchmark_bypasses_provider_and_cache(fake_provider):
    """`benchmark_close_series` verildiğinde `get_benchmark_close_series()`
    HİÇ çağrılmaz -- ne provider ne benchmark cache dokunulur (poison
    nesneler herhangi bir metodu çağrılırsa AssertionError fırlatır).
    Sonuç, AYNI benchmark verisiyle provider/cache üzerinden hesaplanan
    sonuca eşit olmalı (izolasyon, DEĞERİ değiştirmez)."""
    df_raw = _history_df()
    config_repo = _FakeConfigRepo()
    legit_provider = fake_provider(history_df=df_raw)

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        df_raw, "TEST", config_repo
    )

    benchmark_series = get_benchmark_close_series(provider=legit_provider, cache_repo=_EmptyBenchmarkCacheRepo())

    reference_analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=legit_provider,
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
        benchmark_close_series=benchmark_series,
    )

    injected_analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=_PoisonProvider(),
        benchmark_cache_repo=_PoisonBenchmarkCacheRepo(),
        benchmark_close_series=benchmark_series,
    )

    assert injected_analysis.model_dump(exclude={"created_at"}) == reference_analysis.model_dump(exclude={"created_at"})


def test_compute_technical_analysis_empty_injected_benchmark_yields_unknown_without_touching_provider(fake_provider):
    """Boş (hiç ortak tarih olmayan) bir `benchmark_close_series` enjekte
    edilirse `relative_strength_score()` ValueError fırlatır (mevcut,
    değişmemiş davranış), `_compute_enrichment` bunu yakalayıp
    `relative_strength_class="UNKNOWN"` üretir -- provider/cache'e YİNE
    dokunulmaz (poison nesneler)."""
    df_raw = _history_df()
    config_repo = _FakeConfigRepo()

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        df_raw, "TEST", config_repo
    )

    empty_benchmark = pd.Series(dtype=float)

    analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=_PoisonProvider(),
        benchmark_cache_repo=_PoisonBenchmarkCacheRepo(),
        benchmark_close_series=empty_benchmark,
    )

    assert analysis.relative_strength_class == "UNKNOWN"


def test_compute_technical_analysis_has_no_persistence_or_cache_parameters():
    """`compute_technical_analysis()`'in imzası, persist/cache-lookup
    katmanına (ör. `TechnicalAnalysisRepository`, `persist`, `max_age_
    seconds`) HİÇBİR referans TAŞIMAMALI -- izolasyon bir bayrakla değil,
    bu fonksiyonun bunları hiç KABUL ETMEMESİYLE garanti edilir."""
    import inspect

    params = set(inspect.signature(compute_technical_analysis).parameters)
    assert "persist" not in params
    assert "max_age_seconds" not in params
    assert "analysis_repo" not in params


@pytest.mark.parametrize("seed", [1, 7, 99])
def test_compute_technical_analysis_matches_analyze_with_id_across_seeds(fake_provider, seed):
    """Birden fazla rastgele seed'de (farklı bullish/bearish/karma skor
    profilleri) parite tekrar doğrulanır -- HATA 12M'in "8 fixture
    senaryosu" gereksiniminin (bullish/bearish/nötr çeşitliliği) bir
    parçası, tekil sabit-fixture yerine parametrized rastgele seed ile."""
    df_raw = _history_df(seed=seed)
    provider = fake_provider(history_df=df_raw)
    config_repo = _FakeConfigRepo()

    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=config_repo,
        analysis_repo=_FakeTechnicalAnalysisRepo(),
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
    )
    legacy_analysis, _ = engine.analyze_with_id("TEST")

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        df_raw, "TEST", config_repo
    )
    direct_analysis = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=provider,
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
    )

    assert legacy_analysis.model_dump(exclude={"created_at"}) == direct_analysis.model_dump(exclude={"created_at"})


class _CountingCachedTechnicalAnalysisRepo:
    """`_FakeTechnicalAnalysisRepo`'nun aksine GERÇEK bir (taze, hash-eşleşen)
    cache kaydı döner -- `get_latest_with_id()`'in KAÇ kez çağrıldığını da
    sayar. `add()` çağrılırsa test FAIL eder (evidence compute path ASLA
    persist etmemeli)."""

    def __init__(self, cached: TechnicalAnalysis, cached_id: str):
        self._cached = cached
        self._cached_id = cached_id
        self.get_latest_with_id_calls = 0

    def get_latest_with_id(self, asset):
        self.get_latest_with_id_calls += 1
        return self._cached, self._cached_id

    def add(self, analysis):
        raise AssertionError("compute_technical_analysis() cagri zinciri PERSIST etmemeli")


def test_compute_technical_analysis_cannot_reach_conflicting_fresh_technical_cache(fake_provider):
    """HATA 12M-V madde 6: aynı symbol/ENGINE_VERSION/scoring_config_hash'e
    sahip, `age < 900s` (TTL içi) GERÇEKTEN GEÇERLİ bir cache kaydı mevcut
    olsa BİLE (`analyze_with_id()`'te bu bir cache HIT üretirdi),
    `compute_technical_analysis()` DOĞRUDAN çağrıldığında bu kaydı ASLA
    döndürmez -- çünkü imzasında bir repo/cache parametresi YOK (bu nesneyi
    fonksiyona VERMENİN bile bir yolu yok, bkz. `test_compute_technical_
    analysis_has_no_persistence_or_cache_parameters`). Bu test, o statik
    imza-kontrolünü DAVRANIŞSAL olarak da kanıtlar: cache kaydına kasıtlı,
    ayırt edici bir "zehir" değer (`technical_score=999.0`) konur; doğrudan
    `compute_technical_analysis()` çağrısının sonucu bu değeri ASLA taşımaz
    VE `get_latest_with_id()` hiç çağrılmaz (referans bile edilmez).

    Kontrast kontrolü: AYNI zehirli repo, `analyze_with_id()` (gerçek üretim
    yolu) üzerinden verilirse GERÇEKTEN bir cache HIT oluşturup 999.0 döner
    -- bu, fixture'ın "zaten hiçbir zaman eşleşmeyen" anlamsız bir kurulum
    olmadığını, GERÇEKTEN geçerli/eşleşen bir cache kaydı olduğunu kanıtlar.
    """
    df_raw = _history_df()
    provider = fake_provider(history_df=df_raw)
    config_repo = _FakeConfigRepo()

    df, weights, family_weights, scoring_hash, validation_status, session_fields = _resolve_head(
        df_raw, "TEST", config_repo
    )

    conflicting_cached = TechnicalAnalysis(
        asset="TEST",
        technical_score=999.0,
        trend="BULLISH",
        confidence=0.99,
        components={"rsi": 999.0},
        indicators={"rsi": 999.0},
        created_at=datetime.now(timezone.utc),  # age=0s < 900s TTL
        engine_version=ENGINE_VERSION,  # tam eşleşme
        scoring_config_hash=scoring_hash,  # tam eşleşme
    )
    poisoned_repo = _CountingCachedTechnicalAnalysisRepo(conflicting_cached, "poisoned-doc-id")

    direct_result = compute_technical_analysis(
        df,
        "TEST",
        weights,
        family_weights,
        scoring_hash,
        validation_status,
        session_fields,
        provider=provider,
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
    )

    assert direct_result.technical_score != 999.0
    assert poisoned_repo.get_latest_with_id_calls == 0

    # Kontrast: ayni zehirli repo, GERCEK uretim yolunda (analyze_with_id)
    # kullanilirsa GERCEKTEN cache HIT uretir -- fixture'in gecerliligini kanitlar.
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=config_repo,
        analysis_repo=poisoned_repo,
        benchmark_cache_repo=_EmptyBenchmarkCacheRepo(),
    )
    legacy_result, legacy_doc_id = engine.analyze_with_id("TEST")
    assert legacy_result.technical_score == 999.0
    assert legacy_doc_id == "poisoned-doc-id"
    assert poisoned_repo.get_latest_with_id_calls == 1
