from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.completed_history import INDICATOR_WARMUP_SESSIONS, prepare_backtest_history
from app.engines.backtest.engine import BacktestEngine, simulate
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.backtest.walk_forward import WalkForwardOptimizer
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.data_quality import TradingDayContinuityError
from app.engines.technical.engine import DEFAULT_WEIGHTS
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.services.market_data.trading_calendar import (
    NonSessionClassification,
    expected_trading_sessions,
    normalize_bist_daily_sessions,
)

TZ = ZoneInfo("Europe/Istanbul")


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        # HATA 5B2D FINAL COMMIT GATE: `technical_indicator_weights` artık
        # REQUIRED (missing -> fail-fast) -- gerçek production'ı simüle etmek
        # için GEÇERLİ/TAM bir config döner. `technical_family_weights` hâlâ
        # `None` (dokümanı henüz production'da yok, pre-deploy gate ayrı).
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        # HATA 5C3B: `decision_thresholds` de artık REQUIRED (get_raw() +
        # strict resolver, bkz. decision/engine.py) -- backtest'in KENDİ
        # trade-classification'ı için gerçek production'ı simüle eder.
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


def _bday_df(periods: int, end: str, seed: int = 5) -> pd.DataFrame:
    # HATA 3C (26.08.2026): naif `pd.bdate_range` yerine gerçek BIST işlem
    # günleri (`expected_trading_sessions`) — resmi tatilleri BİLMEDİĞİNDEN
    # `UNEXPECTED_TRADING_SESSION` ile veto ediliyordu.
    end_date = pd.Timestamp(end).date()
    search_start = end_date - timedelta(days=periods * 2 + 15)
    sessions = expected_trading_sessions(search_start, end_date)[-periods:]
    dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in sessions])
    rng = np.random.default_rng(seed)
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


def _append_partial_row(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    row = pd.DataFrame(
        {"Open": [999.0], "High": [1000.0], "Low": [1.0], "Close": [1.0], "Volume": [999_000_000]},
        index=[pd.Timestamp(date_str, tz=TZ)],
    )
    return pd.concat([df, row])


# now: piyasa acik (kapanistan/finalization payindan ONCE) -- 26.08 satiri PARTIAL.
_NOW_MARKET_OPEN = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)


class _MissingIndicatorWeightsConfigRepo:
    """FINAL COMMIT GATE, madde 6: `technical_indicator_weights` dokümanı
    TAMAMEN yok -- production config corruption/deletion, fail-fast."""

    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        return None


def test_backtest_engine_run_fails_fast_on_missing_indicator_weights_document(fake_provider):
    # FINAL COMMIT GATE madde 6: geçerli/temiz OHLCV (data-quality HİÇBİR
    # kontrolü tetiklenmez) + `technical_indicator_weights` dokümanı TAMAMEN
    # yok -> ValueError -- production config corruption/deletion olarak
    # ele alınır, code DEFAULT_WEIGHTS'e SESSİZCE düşülmez.
    from app.engines.technical.data_quality import DataQualityError

    completed = _bday_df(periods=340, end="2026-08-25")
    provider = fake_provider(history_df=completed)
    engine = BacktestEngine(provider=provider, config_repo=_MissingIndicatorWeightsConfigRepo())

    with pytest.raises(ValueError) as exc_info:
        engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert not isinstance(exc_info.value, DataQualityError)
    assert "technical_indicator_weights" in str(exc_info.value)


def test_walk_forward_optimizer_run_fails_fast_on_missing_indicator_weights_document(fake_provider):
    # FINAL COMMIT GATE madde 6: `WalkForwardOptimizer`'ın production path'i
    # AYNI contract'ı kullanmalı.
    from app.engines.technical.data_quality import DataQualityError

    completed = _bday_df(periods=340, end="2026-08-25")
    provider = fake_provider(history_df=completed)
    optimizer = WalkForwardOptimizer(provider=provider, config_repo=_MissingIndicatorWeightsConfigRepo())

    with pytest.raises(ValueError) as exc_info:
        optimizer.run("TEST", period="1y", train_days=100, test_days=30, now=_NOW_MARKET_OPEN)

    assert not isinstance(exc_info.value, DataQualityError)
    assert "technical_indicator_weights" in str(exc_info.value)


def test_backtest_engine_run_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=340, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


def test_backtest_engine_compare_strategies_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=340, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


class _CustomFamilyWeightsConfigRepo:
    """FINAL PRE-COMMIT GATE madde 3: `technical_family_weights` dokümanı
    production'da NON-DEFAULT bir değer taşıyorsa (trend=.50/oscillator=.25/
    momentum=.25), `BacktestEngine.run()` VE `BacktestEngine.compare_
    strategies()` AYNI (bu custom) config'i kullanmalı -- ikisi FARKLI
    family_weights'e düşerse bu bir BUG'dır (denetimde tam olarak bu
    bulundu: `compare_strategies()` sessizce eşit-1/3'e düşüyordu)."""

    CUSTOM_FAMILY_WEIGHTS = {"trend": 0.50, "oscillator_position": 0.25, "momentum_rate": 0.25}

    def get(self, key, defaults):
        return defaults

    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return dict(DEFAULT_WEIGHTS)
        if key == "technical_family_weights":
            return self.CUSTOM_FAMILY_WEIGHTS
        if key == "decision_thresholds":
            return dict(DEFAULT_THRESHOLDS)
        return None


def test_backtest_engine_run_and_compare_strategies_use_identical_family_weights_config(fake_provider, monkeypatch):
    import app.engines.backtest.engine as backtest_engine_module

    captured_family_weights: list[dict] = []
    real_technical_score_series = backtest_engine_module.technical_score_series

    def _spy_technical_score_series(df, weights, family_weights):
        captured_family_weights.append(family_weights)
        return real_technical_score_series(df, weights, family_weights)

    monkeypatch.setattr(backtest_engine_module, "technical_score_series", _spy_technical_score_series)

    completed = _bday_df(periods=340, end="2026-08-25")
    config_repo = _CustomFamilyWeightsConfigRepo()

    run_engine = BacktestEngine(provider=fake_provider(history_df=completed), config_repo=config_repo)
    run_engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    compare_engine = BacktestEngine(provider=fake_provider(history_df=completed), config_repo=config_repo)
    compare_engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=_NOW_MARKET_OPEN)

    # run(): 1 çağrı; compare_strategies(): preset sayısı kadar çağrı -- HEPSİ
    # AYNI custom family_weights'i almış olmalı (eşit 1/3'e sessizce
    # DÜŞMEMİŞ olmalı).
    assert len(captured_family_weights) == 1 + len(STRATEGY_PRESETS)
    for fw in captured_family_weights:
        assert fw == _CustomFamilyWeightsConfigRepo.CUSTOM_FAMILY_WEIGHTS


def test_backtest_engine_run_reports_technical_engine_version(fake_provider):
    # HATA 5B2D madde 24/34-V: backtest sonucunun HANGİ technical scoring
    # semantics'iyle (flat 7-component vs family-level aggregation) üretildiği
    # geriye dönük tespit edilebilsin diye.
    from app.engines.technical.engine import ENGINE_VERSION as TECHNICAL_ENGINE_VERSION

    completed = _bday_df(periods=340, end="2026-08-25")
    provider = fake_provider(history_df=completed)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result["technical_engine_version"] == TECHNICAL_ENGINE_VERSION == "1.11.0"


def test_backtest_engine_compare_strategies_reports_technical_engine_version(fake_provider):
    from app.engines.technical.engine import ENGINE_VERSION as TECHNICAL_ENGINE_VERSION

    completed = _bday_df(periods=340, end="2026-08-25")
    provider = fake_provider(history_df=completed)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=_NOW_MARKET_OPEN)

    assert result["technical_engine_version"] == TECHNICAL_ENGINE_VERSION


def test_walk_forward_optimizer_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=340, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    optimizer = WalkForwardOptimizer(provider=provider, config_repo=_FakeConfigRepo())

    result = optimizer.run("TEST", period="1y", train_days=60, test_days=20, now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    # HATA 5A: fixture genişledi (340 session, mandatory 60-session warm-up
    # için), bu yüzden son fold'un test_to'su artık fold aritmetiğine göre
    # (60+20*k) tam 2026-08-25'e denk gelmeyebilir -- asıl garanti, partial
    # (26.08) barının HİÇBİR pencereye asla girmemesidir.
    all_window_dates = [d for w in result["windows"] for d in (w["train_from"], w["train_to"], w["test_from"], w["test_to"])]
    assert "2026-08-26" not in all_window_dates
    last_window = result["windows"][-1]
    assert last_window["test_to"] <= "2026-08-25"


def test_backtest_engine_run_partial_row_content_never_changes_result(fake_provider):
    # HATA 3B ana regresyon kilidi (ucdan uca): iki AYRI partial satir --
    # sonuc BIREBIR ayni olmali.
    completed = _bday_df(periods=340, end="2026-08-25")

    row_calm = pd.DataFrame(
        {"Open": [100.0], "High": [100.5], "Low": [99.5], "Close": [100.0], "Volume": [1000]},
        index=[pd.Timestamp("2026-08-26", tz=TZ)],
    )
    row_wild = pd.DataFrame(
        {"Open": [1.0], "High": [99999.0], "Low": [0.5], "Close": [99999.0], "Volume": [999_000_000]},
        index=[pd.Timestamp("2026-08-26", tz=TZ)],
    )

    result_calm = BacktestEngine(
        provider=fake_provider(history_df=pd.concat([completed, row_calm])), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=_NOW_MARKET_OPEN)
    result_wild = BacktestEngine(
        provider=fake_provider(history_df=pd.concat([completed, row_wild])), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result_calm["total_return_pct"] == result_wild["total_return_pct"]
    assert result_calm["trade_count"] == result_wild["trade_count"]
    assert result_calm["max_drawdown_pct"] == result_wild["max_drawdown_pct"]
    assert result_calm["backtest_data_as_of"] == result_wild["backtest_data_as_of"] == "2026-08-25"


# ---------------------------------------------------------------------------
# HATA 3C-EX (26.08.2026): 08.02.2023 cancelled-session — execution semantiği.
# Resmi kaynak: Anadolu Ajansı/KAP — 8 Şubat 2023'te BIST Pay Piyasası
# devre kesiciler sonrası saat 11:00'de durduruldu VE o gün gerçekleşen TÜM
# işlemler resmi olarak iptal edildi (BİAŞ Yönetmeliği m.33); piyasa 15
# Şubat 2023'te yeniden açıldı.
# ---------------------------------------------------------------------------


def _feb_2023_earthquake_df() -> pd.DataFrame:
    rows = [
        ("2023-02-07", 135.59, 135.59, 122.0, 124.26, 48_181_521),
        ("2023-02-08", 112.34, 112.34, 112.34, 112.34, 2_500),  # CANCELLED_SESSION
        ("2023-02-15", 132.86, 136.67, 130.0, 136.67, 20_534_049),
        ("2023-02-16", 147.61, 149.27, 136.76, 136.76, 63_980_902),
    ]
    index = pd.DatetimeIndex([pd.Timestamp(r[0], tz=TZ) for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=index,
    )


def test_cancelled_session_bar_is_never_used_for_execution(fake_provider):
    # HATA 3C-EX madde 7: normalizasyon sonrası history = [07.02, 15.02, 16.02]
    # (08.02 tamamen gitti). 07.02'de manuel bir BUY sinyali kurulup execution'ın
    # 08.02'nin (Open=112.34) DEĞİL, 15.02'nin (Open=132.86) Open'ından
    # gerçekleştiği doğrudan doğrulanıyor.
    #
    # HATA 5A NOTU: bu test normalizasyon/execution mekaniğini izole test
    # eder -- bilinçli olarak `prepare_backtest_history()` (artık mandatory
    # 60-session warm-up gerektirir) YERİNE alt seviye fonksiyonları
    # (filter_completed_daily_bars + normalize_bist_daily_sessions) doğrudan
    # çağırır; bu 4 satırlık sentetik fixture 60 session warm-up sağlayamaz
    # ve bu testin amacı zaten warm-up sufficiency'yi DEĞİL, normalizasyonu
    # doğrulamaktır.
    now = datetime(2023, 2, 16, 19, 0, tzinfo=TZ)
    raw = _feb_2023_earthquake_df()

    completed = filter_completed_daily_bars(raw, now=now)
    normalized_df, _ = normalize_bist_daily_sessions(completed, symbol="THYAO", provider="yahoo_finance")
    assert list(normalized_df.index.date) == [
        pd.Timestamp("2023-02-07").date(),
        pd.Timestamp("2023-02-15").date(),
        pd.Timestamp("2023-02-16").date(),
    ]

    scores = pd.Series([0.0] * len(normalized_df), index=normalized_df.index)
    scores.iloc[0] = 50.0  # 07.02'de BUY sinyali

    result = simulate(normalized_df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    pos = result["open_position"]
    assert pos is not None
    assert pos["entry_execution_date"] == "2023-02-15"
    assert pos["entry_execution_price"] == pytest.approx(132.86)  # Open[15.02]
    assert pos["entry_execution_price"] != pytest.approx(112.34)  # Open[08.02] ASLA kullanılmadı


# ---------------------------------------------------------------------------
# HATA 3D, madde 21: 27-29 Mayıs 2026 (Kurban Bayramı) -- Yahoo'nun gerçek
# hayatta ürettiği "phantom" barlar (bkz. HATA 3D denetimi). 26 Mayıs
# Close'unda kurulan BUY sinyali, normalizasyon sonrası ASLA 27/28/29
# Mayıs'ın (var olmaması gereken, fiilen düşürülmüş) barlarında değil,
# yalnızca bir sonraki GERÇEK seans olan 01 Haziran'ın Open'ında
# gerçekleştirilmelidir.
# ---------------------------------------------------------------------------


def _may_2026_bayram_phantom_df() -> pd.DataFrame:
    before = _bday_df(periods=10, end="2026-05-26")
    close_26_may = before["Close"].iloc[-1]
    # HATA 3D phantom imzası: Open=High=Low=Close=önceki kapanış, Volume=0.
    phantom = pd.DataFrame(
        {
            "Open": [close_26_may] * 3,
            "High": [close_26_may] * 3,
            "Low": [close_26_may] * 3,
            "Close": [close_26_may] * 3,
            "Volume": [0, 0, 0],
        },
        index=pd.DatetimeIndex(
            [pd.Timestamp(d, tz=TZ) for d in ("2026-05-27", "2026-05-28", "2026-05-29")]
        ),
    )
    after_sessions = expected_trading_sessions(date(2026, 6, 1), date(2026, 6, 10))
    after_dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in after_sessions])
    rng = np.random.default_rng(11)
    after_closes = 100 + np.cumsum(rng.normal(0, 1, len(after_dates)))
    after = pd.DataFrame(
        {
            "Open": after_closes - 0.2,
            "High": after_closes + 0.5,
            "Low": after_closes - 0.5,
            "Close": after_closes,
            "Volume": rng.integers(1000, 5000, len(after_dates)),
        },
        index=after_dates,
    )
    return pd.concat([before, phantom, after]).sort_index()


def test_planned_holiday_phantom_bars_never_used_for_execution(fake_provider):
    # HATA 5A NOTU: `test_cancelled_session_bar_is_never_used_for_execution`
    # ile aynı gerekçe -- bu, warm-up sufficiency'yi DEĞİL normalizasyonu
    # test ediyor; `prepare_backtest_history()` YERİNE alt seviye
    # fonksiyonlar doğrudan çağrılıyor.
    now = datetime(2026, 6, 10, 19, 0, tzinfo=TZ)
    raw = _may_2026_bayram_phantom_df()

    completed = filter_completed_daily_bars(raw, now=now)
    normalized_df, normalization_result = normalize_bist_daily_sessions(completed, symbol="TEST", provider="yahoo_finance")

    assert pd.Timestamp("2026-05-26").date() in normalized_df.index.date
    for phantom_date in ("2026-05-27", "2026-05-28", "2026-05-29"):
        assert pd.Timestamp(phantom_date).date() not in normalized_df.index.date
    assert pd.Timestamp("2026-06-01").date() in normalized_df.index.date

    dropped = {d.date: d.classification for d in normalization_result.dropped_sessions}
    for phantom_date in ("2026-05-27", "2026-05-28", "2026-05-29"):
        assert dropped.get(pd.Timestamp(phantom_date).date()) == NonSessionClassification.PLANNED_FULL_DAY_CLOSURE.value

    scores = pd.Series([0.0] * len(normalized_df), index=normalized_df.index)
    signal_pos = list(normalized_df.index.date).index(pd.Timestamp("2026-05-26").date())
    scores.iloc[signal_pos] = 50.0  # 26.05 Close'unda BUY sinyali

    result = simulate(normalized_df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    pos = result["open_position"]
    assert pos is not None
    assert pos["entry_execution_date"] == "2026-06-01"
    expected_open = normalized_df.loc[pd.Timestamp("2026-06-01", tz=TZ), "Open"]
    assert pos["entry_execution_price"] == pytest.approx(round(expected_open, 2))
    phantom_open = raw.loc[pd.Timestamp("2026-05-27", tz=TZ), "Open"]
    assert pos["entry_execution_price"] != pytest.approx(phantom_open)  # 27.05 phantom Open'ı ASLA kullanılmadı


# ---------------------------------------------------------------------------
# HATA 3C, madde 12: history'de doğrulanmış bir middle-gap varsa
# WalkForwardOptimizer TAMAMEN HARD_VETO olur — gap içeren fold ATLANMAZ.
# ---------------------------------------------------------------------------


def test_walk_forward_optimizer_hard_vetoes_entire_run_no_fold_skip(fake_provider):
    # HATA 5A: "1y" artık mandatory 60-session warm-up + ~252 simulation
    # session gerektirdiğinden (indicator_history >= ~312 satır), fixture
    # eskisinden (200) daha geniş tutuldu -- aksi halde HARD VETO gerçek
    # (deliberately dropped) boşluktan DEĞİL, warm-up'ın kendisinin
    # yetersizliğinden tetiklenirdi.
    now = datetime(2026, 8, 27, 19, 0, tzinfo=TZ)
    df = _bday_df(periods=340, end="2026-08-27")
    gap_date = df.index[100]  # gercek bir bosluk (tatil DEGIL) ortaya sokuluyor
    df = df.drop(gap_date)

    provider = fake_provider(history_df=df)
    optimizer = WalkForwardOptimizer(provider=provider, config_repo=_FakeConfigRepo())

    with pytest.raises(TradingDayContinuityError) as exc_info:
        optimizer.run("TEST", period="1y", train_days=60, test_days=20, now=now)

    assert exc_info.value.missing_dates == [gap_date.date()]


# ---------------------------------------------------------------------------
# HATA 3C, madde 1: period validasyonu doğrudan motor çağrısında da (API'yi
# atlayarak) çalışır — defense-in-depth.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random"])
def test_backtest_engine_run_rejects_unsupported_period_directly(fake_provider, period):
    engine = BacktestEngine(provider=fake_provider(history_df=pd.DataFrame()), config_repo=_FakeConfigRepo())
    with pytest.raises(ValueError):
        engine.run("TEST", period=period)


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random"])
def test_backtest_engine_compare_strategies_rejects_unsupported_period_directly(fake_provider, period):
    engine = BacktestEngine(provider=fake_provider(history_df=pd.DataFrame()), config_repo=_FakeConfigRepo())
    with pytest.raises(ValueError):
        engine.compare_strategies("TEST", STRATEGY_PRESETS, period=period)


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random"])
def test_walk_forward_optimizer_rejects_unsupported_period_directly(fake_provider, period):
    optimizer = WalkForwardOptimizer(provider=fake_provider(history_df=pd.DataFrame()), config_repo=_FakeConfigRepo())
    with pytest.raises(ValueError):
        optimizer.run("TEST", period=period)


# ---------------------------------------------------------------------------
# HATA 3E (26.08.2026) — BACKTEST LEADING-EDGE / EXPLICIT WINDOW: uçtan uca
# (BacktestEngine/WalkForwardOptimizer) regresyonlar.
# ---------------------------------------------------------------------------


class _CountingProvider:
    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df
        self.call_count = 0

    def get_history(self, symbol: str, **kwargs):
        self.call_count += 1
        return self._history_df


def test_compare_strategies_fetches_history_exactly_once_for_all_presets():
    # HATA 3E madde 17: tek fetch, tek normalization, tek leading-edge
    # çözümü, tek analysis_history — preset sayısından (STRATEGY_PRESETS'te
    # 5 tane var) BAĞIMSIZ olarak provider TAM OLARAK bir kez çağrılmalı.
    # HATA 5A: fixture, mandatory 60-session warm-up + ~252 simulation
    # session'ı (indicator_history >= ~312 satır) karşılayacak kadar geniş
    # tutuldu -- aksi halde HARD VETO exception'ı testin assertion'ına
    # ulaşmadan fırlardı.
    completed = _bday_df(periods=340, end="2026-08-26")
    provider = _CountingProvider(completed)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=datetime(2026, 8, 26, 18, 45, tzinfo=TZ))

    assert provider.call_count == 1


def _sessions_df(start: str, end: str, seed: int = 5) -> pd.DataFrame:
    sessions = expected_trading_sessions(pd.Timestamp(start).date(), pd.Timestamp(end).date())
    dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in sessions])
    rng = np.random.default_rng(seed)
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


def test_walk_forward_windows_are_identical_with_and_without_pre_roll_evidence():
    # HATA 3E madde 16: pre-roll (evidence-only) barlarının VARLIĞI/YOKLUĞU
    # walk-forward'ın train/test pencere sınırlarını (`train_from`/`test_from`
    # vb.) HİÇ ETKİLEMEMELİDİR — ikisi de AYNI `analysis_history`'ye
    # (target_start'tan itibaren) crop edilir.
    # HATA 5A: fixture artık mandatory 60-session warm-up'ı da İÇERİR --
    # `warmup_history_start` (2025-05-29, gerçek BIST takviminden, "1y" için
    # simulation_start=2025-08-26'dan tam 60 seans önce) .. target_end.
    # Evidence pre-roll artık BUNUN öncesine (target_start'ın DEĞİL) eklenir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> target_start(1y)=simulation_start=2025-08-26
    warmup_and_simulation = _sessions_df("2025-05-29", "2026-08-26")  # warmup_history_start..target_end

    with_pre_roll = pd.concat(
        [_sessions_df("2025-03-01", "2025-05-28", seed=9), warmup_and_simulation]
    ).sort_index()  # evidence, warmup_history_start'IN ÖNCESİNDE

    optimizer_no_evidence = WalkForwardOptimizer(
        provider=_CountingProvider(warmup_and_simulation), config_repo=_FakeConfigRepo()
    )
    optimizer_with_evidence = WalkForwardOptimizer(
        provider=_CountingProvider(with_pre_roll), config_repo=_FakeConfigRepo()
    )

    result_no_evidence = optimizer_no_evidence.run("TEST", period="1y", train_days=60, test_days=20, now=now)
    result_with_evidence = optimizer_with_evidence.run("TEST", period="1y", train_days=60, test_days=20, now=now)

    assert result_no_evidence["history_validation_status"] == "LEADING_EDGE_UNVERIFIED"
    assert result_with_evidence["history_validation_status"] == "VERIFIED_PRE_WINDOW"
    assert result_no_evidence["windows"] == result_with_evidence["windows"]
    assert result_no_evidence["requested_window_start"] == result_with_evidence["requested_window_start"] == "2025-08-26"
    assert result_no_evidence["simulation_start"] == result_with_evidence["simulation_start"] == "2025-08-26"
    assert result_no_evidence["actual_history_start"] == result_with_evidence["actual_history_start"] == "2025-08-26"


def test_backtest_engine_run_warm_up_boundary_is_identical_with_and_without_pre_roll_evidence():
    # HATA 3E madde 3 + HATA 5A: walk-forward'ın YANINDA, normal
    # `BacktestEngine.run()` seviyesinde de AYNI garanti kilitlenir -- pre-roll
    # bar sayısı `from_date`/`to_date`/`backtest_data_as_of`'u VEYA
    # `simulation_start`'ı DEĞİŞTİRMEMELİDİR. Fixture artık mandatory
    # 60-session warm-up'ı da İÇERİR.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> target_start(1y)=simulation_start=2025-08-26
    warmup_and_simulation = _sessions_df("2025-05-29", "2026-08-26")  # warmup_history_start..target_end
    with_pre_roll = pd.concat(
        [_sessions_df("2025-03-01", "2025-05-28", seed=9), warmup_and_simulation]
    ).sort_index()  # evidence, warmup_history_start'IN ÖNCESİNDE

    result_no_evidence = BacktestEngine(
        provider=_CountingProvider(warmup_and_simulation), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=now)
    result_with_evidence = BacktestEngine(
        provider=_CountingProvider(with_pre_roll), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=now)

    assert result_no_evidence["history_validation_status"] == "LEADING_EDGE_UNVERIFIED"
    assert result_with_evidence["history_validation_status"] == "VERIFIED_PRE_WINDOW"

    assert result_no_evidence["from_date"] == result_with_evidence["from_date"]
    assert result_no_evidence["to_date"] == result_with_evidence["to_date"]
    assert result_no_evidence["backtest_data_as_of"] == result_with_evidence["backtest_data_as_of"]

    # HATA 5A: from_date artık `simulation_start`'IN KENDİSİDİR -- warm-up
    # pencere DIŞINDA fetch edildiğinden hiçbir slicing offset'i YOKTUR
    # (eski `main_window.index[MIN_HISTORY_DAYS]` deseni KALDIRILDI).
    expected_from_date = "2025-08-26"
    assert result_no_evidence["from_date"] == expected_from_date
    assert result_with_evidence["from_date"] == expected_from_date
    assert result_no_evidence["simulation_start"] == result_with_evidence["simulation_start"] == expected_from_date

    # Trade timeline'ı (equity_curve üzerinden) da birebir aynı olmalı.
    assert result_no_evidence["total_return_pct"] == result_with_evidence["total_return_pct"]
    assert result_no_evidence["trade_count"] == result_with_evidence["trade_count"]
    assert result_no_evidence["equity_curve"] == result_with_evidence["equity_curve"]


# ---------------------------------------------------------------------------
# HATA 5A REQUIRED TEST TRACE MATRIX, madde C/D/E/F/G/H/S: `indicator_history`/
# `simulation_history` ayrımının uçtan uca (BacktestEngine.run()) garantileri.
# ---------------------------------------------------------------------------


def test_indicator_and_simulation_history_partition_with_no_overlap_no_gap():
    # C + D: `indicator_history` TAM OLARAK warm-up + simulation'ın BİRLEŞİMİ
    # (aralarında ne boşluk ne çakışma), `simulation_history` warm-up'ın
    # HİÇBİR tarihini içermiyor.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> simulation_start(1y)=2025-08-26
    df = _sessions_df("2025-05-29", "2026-08-26")  # warmup_history_start(=2025-05-29)..target_end

    prepared = prepare_backtest_history(_CountingProvider(df), "TEST", "1y", now=now)

    warmup_dates = [d for d in prepared.indicator_history.index if d.date() < prepared.simulation_start]
    assert len(warmup_dates) == prepared.indicator_warmup_sessions == 60
    assert len(prepared.indicator_history) == len(warmup_dates) + len(prepared.simulation_history)
    assert prepared.indicator_history.index[len(warmup_dates)] == prepared.simulation_history.index[0]
    assert all(d.date() >= prepared.simulation_start for d in prepared.simulation_history.index)
    assert not any(d.date() < prepared.simulation_start for d in prepared.simulation_history.index)


def test_simulation_start_score_is_finite_valid_after_full_warmup():
    # E: `technical_score_series(indicator_history)` tam 60 seanslık warm-up
    # SONRASI hesaplandığından, `simulation_start`'taki (indicator_history'nin
    # 61. satırı) skor ASLA NaN olmamalı -- RSI/MACD/EMA/.../ROC'un ısınma
    # payı tamamen `indicator_history`'nin İÇİNDE tüketilir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _sessions_df("2025-05-29", "2026-08-26")
    prepared = prepare_backtest_history(_CountingProvider(df), "TEST", "1y", now=now)

    from app.engines.backtest.engine import technical_score_series
    from app.engines.technical.engine import DEFAULT_WEIGHTS
    from app.engines.technical.scoring import DEFAULT_TECHNICAL_FAMILY_WEIGHTS

    scores_all = technical_score_series(prepared.indicator_history, DEFAULT_WEIGHTS, DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    simulation_start_score = scores_all.loc[prepared.simulation_history.index[0]]
    assert pd.notna(simulation_start_score)
    assert not (simulation_start_score != simulation_start_score)  # NaN != NaN olurdu
    assert abs(simulation_start_score) <= 100.0  # _clamp_series garantisi


def test_equity_curve_first_date_equals_simulation_start_and_never_predates_it():
    # F + S: `equity_curve` (ve dolayısıyla trade/mark-to-market) YALNIZ
    # `simulation_history` üzerinden inşa edilir -- ilk kayıt `simulation_
    # start`'ın KENDİSİDİR, warm-up'a ait TEK bir tarih bile equity_curve'e
    # sızmaz.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _sessions_df("2025-05-29", "2026-08-26")
    engine = BacktestEngine(provider=_CountingProvider(df), config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=now)

    assert result["equity_curve"][0]["date"] == result["simulation_start"] == "2025-08-26"
    assert len(result["equity_curve"]) == len(_sessions_df("2025-08-26", "2026-08-26"))
    all_equity_dates = [point["date"] for point in result["equity_curve"]]
    assert all(d >= result["simulation_start"] for d in all_equity_dates)


def test_benchmark_buy_and_hold_uses_simulation_start_close_not_warmup_close():
    # H: `buy_and_hold_return_pct`, warm-up'ın (çok daha ERKEN, dolayısıyla
    # FARKLI bir Close'a sahip) ilk barından DEĞİL, `simulation_history`'nin
    # (yani `simulation_start`'ın) İLK Close'undan hesaplanmalı. İki farklı
    # (warm-up başlangıcı vs simulation başlangıcı) Close değerinden hangisi
    # kullanıldığını doğrudan ayırt etmek için beklenen değer, gerçek
    # `simulation_history` dilimi üzerinden BAĞIMSIZ olarak yeniden hesaplanır.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _sessions_df("2025-05-29", "2026-08-26")
    engine = BacktestEngine(provider=_CountingProvider(df), config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=now)

    simulation_only = df[[ts.date() >= date(2025, 8, 26) for ts in df.index]]
    expected_bh = round(
        (float(simulation_only["Close"].iloc[-1]) - float(simulation_only["Close"].iloc[0]))
        / float(simulation_only["Close"].iloc[0])
        * 100,
        2,
    )
    warmup_only_bh = round(
        (float(simulation_only["Close"].iloc[-1]) - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0]) * 100, 2
    )
    assert result["buy_and_hold_return_pct"] == expected_bh
    assert result["buy_and_hold_return_pct"] != warmup_only_bh  # warm-up'ın Close'u YANLIŞLIKLA kullanılmadı


def test_first_bar_of_simulation_signal_still_executes_at_next_session_open():
    # G: `simulation_start`'IN KENDİSİNDE (simulation_history'nin 0. satırı)
    # oluşan bir sinyal bile NEXT_SESSION_OPEN kuralına tabidir -- warm-up'a
    # ait HİÇBİR barın Open'ı execution için kullanılamaz (`simulate()`
    # yapısal olarak warm-up'ı hiç GÖRMEZ, yalnızca `simulation_history`
    # alır) çünkü execution zaten yalnızca simulation_history.index[1]'den
    # itibaren mümkündür.
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in ["2026-01-05", "2026-01-06", "2026-01-07"]])
    df = pd.DataFrame(
        {"Open": [50.0, 60.0, 70.0], "High": [51, 61, 71], "Low": [49, 59, 69], "Close": [50.0, 60.0, 70.0], "Volume": [1000] * 3},
        index=idx,
    )
    scores = pd.Series([50.0, 0.0, 0.0], index=idx)  # simulation_history'nin İLK barında (idx[0]) güçlü BUY

    result = simulate(df, scores, DEFAULT_THRESHOLDS, initial_capital=1000.0)

    assert result["open_position"]["entry_execution_date"] == "2026-01-06"  # idx[0]'ın DEĞİL, T+1'in Open'ı
    assert result["open_position"]["entry_execution_price"] == pytest.approx(60.0)
    assert result["open_position"]["entry_execution_price"] != pytest.approx(50.0)  # idx[0]'ın (T0) Open'ı KULLANILMADI


def test_walk_forward_first_train_slice_starts_exactly_at_simulation_start():
    # Q: eski `start = MIN_HISTORY_DAYS` deseni KALDIRILDIĞINDAN, ilk fold'un
    # `train_from`'u artık `simulation_history.index[0]`'dır -- yani DOĞRUDAN
    # `simulation_start`'IN KENDİSİ, warm-up'ın hiçbir ekstra satırı yok.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> simulation_start(1y)=2025-08-26
    df = _sessions_df("2025-05-29", "2026-08-26")  # warmup_history_start..target_end
    optimizer = WalkForwardOptimizer(provider=_CountingProvider(df), config_repo=_FakeConfigRepo())

    result = optimizer.run("TEST", period="1y", train_days=60, test_days=20, now=now)

    assert result["simulation_start"] == "2025-08-26"
    assert result["windows"][0]["train_from"] == result["simulation_start"]
