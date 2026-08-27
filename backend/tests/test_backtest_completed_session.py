from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.completed_history import prepare_backtest_history
from app.engines.backtest.engine import MIN_HISTORY_DAYS, BacktestEngine, simulate
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.backtest.walk_forward import WalkForwardOptimizer
from app.engines.decision.engine import DEFAULT_THRESHOLDS
from app.engines.technical.data_quality import TradingDayContinuityError
from app.services.market_data.trading_calendar import NonSessionClassification, expected_trading_sessions

TZ = ZoneInfo("Europe/Istanbul")


class _FakeConfigRepo:
    def get(self, key, defaults):
        return defaults


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


def test_backtest_engine_run_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=120, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.run("TEST", period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


def test_backtest_engine_compare_strategies_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=120, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    engine = BacktestEngine(provider=provider, config_repo=_FakeConfigRepo())

    result = engine.compare_strategies("TEST", STRATEGY_PRESETS, period="1y", now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    assert result["to_date"] == "2026-08-25"


def test_walk_forward_optimizer_excludes_partial_bar_and_reports_as_of(fake_provider):
    completed = _bday_df(periods=200, end="2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26")
    provider = fake_provider(history_df=raw)
    optimizer = WalkForwardOptimizer(provider=provider, config_repo=_FakeConfigRepo())

    result = optimizer.run("TEST", period="1y", train_days=60, test_days=20, now=_NOW_MARKET_OPEN)

    assert result["backtest_data_as_of"] == "2026-08-25"
    assert result["data_policy"] == "COMPLETED_DAILY_ONLY"
    last_window = result["windows"][-1]
    assert last_window["test_to"] == "2026-08-25"  # partial (26.08) hicbir pencereye girmedi


def test_backtest_engine_run_partial_row_content_never_changes_result(fake_provider):
    # HATA 3B ana regresyon kilidi (ucdan uca): iki AYRI partial satir --
    # sonuc BIREBIR ayni olmali.
    completed = _bday_df(periods=120, end="2026-08-25")

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
    now = datetime(2023, 2, 16, 19, 0, tzinfo=TZ)
    raw = _feb_2023_earthquake_df()
    provider = fake_provider(history_df=raw)

    prepared = prepare_backtest_history(provider, "THYAO", "1y", min_history_days=2, now=now)
    normalized_df = prepared.history
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
    now = datetime(2026, 6, 10, 19, 0, tzinfo=TZ)
    raw = _may_2026_bayram_phantom_df()
    provider = fake_provider(history_df=raw)

    prepared = prepare_backtest_history(provider, "TEST", "1y", min_history_days=2, now=now)
    normalized_df = prepared.history
    normalization_result = prepared.normalization

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
    now = datetime(2026, 8, 27, 19, 0, tzinfo=TZ)
    df = _bday_df(periods=200, end="2026-08-27")
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
    completed = _bday_df(periods=120, end="2026-08-26")
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
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> target_start(1y)=2025-08-26
    main_window = _sessions_df("2025-08-26", "2026-08-26")  # target_start'IN KENDİSİNDEN başlıyor

    with_pre_roll = pd.concat([_sessions_df("2025-06-01", "2025-08-25", seed=9), main_window]).sort_index()

    optimizer_no_evidence = WalkForwardOptimizer(
        provider=_CountingProvider(main_window), config_repo=_FakeConfigRepo()
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
    assert result_no_evidence["actual_history_start"] == result_with_evidence["actual_history_start"] == "2025-08-26"


def test_backtest_engine_run_warm_up_boundary_is_identical_with_and_without_pre_roll_evidence():
    # HATA 3E madde 3 (commit-öncesi ek talep): walk-forward'ın YANINDA,
    # normal `BacktestEngine.run()` seviyesinde de AYNI garanti kilitlenir --
    # pre-roll bar sayısı `from_date`/`to_date`/`backtest_data_as_of`'u VEYA
    # indicator warm-up sınırını (`iloc[MIN_HISTORY_DAYS:]`) DEĞİŞTİRMEMELİDİR.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> target_start(1y)=2025-08-26
    main_window = _sessions_df("2025-08-26", "2026-08-26")  # target_start'IN KENDİSİNDEN başlıyor -- crop sonrası
    # analysis_history her iki senaryoda da BİREBİR bu DataFrame'in kendisi olmalı.
    with_pre_roll = pd.concat([_sessions_df("2025-06-01", "2025-08-25", seed=9), main_window]).sort_index()

    result_no_evidence = BacktestEngine(
        provider=_CountingProvider(main_window), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=now)
    result_with_evidence = BacktestEngine(
        provider=_CountingProvider(with_pre_roll), config_repo=_FakeConfigRepo()
    ).run("TEST", period="1y", now=now)

    assert result_no_evidence["history_validation_status"] == "LEADING_EDGE_UNVERIFIED"
    assert result_with_evidence["history_validation_status"] == "VERIFIED_PRE_WINDOW"

    assert result_no_evidence["from_date"] == result_with_evidence["from_date"]
    assert result_no_evidence["to_date"] == result_with_evidence["to_date"]
    assert result_no_evidence["backtest_data_as_of"] == result_with_evidence["backtest_data_as_of"]

    # from_date, analysis_history'nin (pre-roll HARİÇ, `main_window`'un kendisi)
    # MIN_HISTORY_DAYS'INCİ satırının tarihidir -- pre-roll bar sayısından
    # (with_pre_roll'da ~60 EK satır var) BAĞIMSIZ.
    expected_from_date = str(main_window.index[MIN_HISTORY_DAYS].date())
    assert result_no_evidence["from_date"] == expected_from_date
    assert result_with_evidence["from_date"] == expected_from_date

    # Trade timeline'ı (equity_curve üzerinden) da birebir aynı olmalı.
    assert result_no_evidence["total_return_pct"] == result_with_evidence["total_return_pct"]
    assert result_no_evidence["trade_count"] == result_with_evidence["trade_count"]
    assert result_no_evidence["equity_curve"] == result_with_evidence["equity_curve"]
