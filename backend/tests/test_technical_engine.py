from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical import indicators as ind
from app.engines.technical.engine import TECHNICAL_CACHE_TTL_SECONDS, TechnicalAnalysisEngine
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


class _StaleSixKeyConfigRepo:
    """Firestore'da AŞAMA 48/9 öncesinden kalmış, "ema_slope" anahtarı OLMAYAN
    eski bir "technical_indicator_weights" belgesini simüle eder — toplam
    ağırlık artık 1.0 değildir. final_score'un yine de [-100, 100] aralığında
    kalması gerekir (normalize edilmiş ağırlıklı ortalama formülü sayesinde).
    """

    def get(self, key, defaults):
        return {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667, "roc": 0.1665}


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


def test_analyze_with_id_uses_cache_when_fresh(fake_provider):
    cached = _cached_analysis(age_seconds=60)  # 1 dakika önce — TTL(900s) içinde
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


def test_analyze_with_id_normalizes_score_with_stale_weight_config(fake_provider):
    # AŞAMA 48/9: "ema_slope" eklendiğinde, Firestore'da hâlâ eski 6 anahtarlı
    # bir kayıt varsa (toplam ağırlık != 1.0), final_score yine de sınırlar
    # içinde kalmalı — ağırlık toplamına bölünerek normalize edilir.
    analysis_repo = _FakeTechnicalAnalysisRepo(cached=None, cached_id=None)
    provider = fake_provider(history_df=_real_history_df())
    engine = TechnicalAnalysisEngine(
        provider=provider,
        config_repo=_StaleSixKeyConfigRepo(),
        analysis_repo=analysis_repo,
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )

    analysis, _ = engine.analyze_with_id("TEST")

    assert -100 <= analysis.technical_score <= 100


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
