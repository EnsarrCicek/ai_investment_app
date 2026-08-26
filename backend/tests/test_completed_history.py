from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.completed_history import SUPPORTED_BACKTEST_PERIODS, prepare_backtest_history
from app.engines.technical.data_quality import DataQualityError, TradingDayContinuityError
from app.services.market_data.trading_calendar import expected_trading_sessions

TZ = ZoneInfo("Europe/Istanbul")


class _FakeProvider:
    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df

    def get_history(self, symbol: str, period: str = "6mo", **_kwargs):
        return self._history_df


def _bday_df(
    start: str | None = None, end: str | None = None, periods: int | None = None, seed: int = 1,
    exclude: list[str] | None = None,
) -> pd.DataFrame:
    """HATA 3C (26.08.2026): gerçek BIST işlem günlerinden (`expected_trading_
    sessions`) üretir — naif `pd.bdate_range` resmi tatilleri BİLMEDİĞİNDEN
    artık `UNEXPECTED_TRADING_SESSION` ile veto ediliyordu. `exclude`, bir
    GERÇEK provider boşluğunu sentetik olarak simüle etmek için (holiday
    OLMAYAN) belirli tarihleri seriden çıkarır (ör. middle-gap testleri).
    """
    if start is not None:
        end_date = pd.Timestamp(end).date()
        sessions = expected_trading_sessions(pd.Timestamp(start).date(), end_date)
    else:
        end_date = pd.Timestamp(end).date()
        search_start = end_date - timedelta(days=periods * 2 + 15)
        sessions = expected_trading_sessions(search_start, end_date)[-periods:]

    if exclude:
        excluded = {pd.Timestamp(d).date() for d in exclude}
        sessions = [d for d in sessions if d not in excluded]

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


def _append_partial_row(df: pd.DataFrame, date_str: str, open_: float, close: float, volume: float) -> pd.DataFrame:
    row = pd.DataFrame(
        {"Open": [open_], "High": [max(open_, close) + 1], "Low": [min(open_, close) - 1], "Close": [close], "Volume": [volume]},
        index=pd.to_datetime([date_str]),
    )
    return pd.concat([df, row])


# ---------------------------------------------------------------------------
# HATA 3B (26.08.2026): backtest COMPLETED_DAILY_ONLY sözleşmesi.
# 24-26 Ağustos 2026 gerçek takvimi kullanılıyor (Pzt/Sal/Çar, hafta içi).
# ---------------------------------------------------------------------------


def test_pre_cutoff_excludes_partial_today_row():
    # now: piyasa acik, saat 10:44 -- bugunku (26.08) satir HENUZ tamamlanmamis.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-25")  # ...24,25 Agustos completed
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    df, backtest_data_as_of = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert backtest_data_as_of == pd.Timestamp("2026-08-25").date()
    assert df.index[-1].date() == pd.Timestamp("2026-08-25").date()
    assert len(df) == len(completed)  # partial satir hic girmedi


def test_post_cutoff_includes_todays_now_completed_row():
    # now: kapanis (18:00) + finalization payi (30dk) GECTI -- bugunku satir artik tamamlanmis kabul edilir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    df, backtest_data_as_of = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert backtest_data_as_of == pd.Timestamp("2026-08-26").date()
    assert df.index[-1].date() == pd.Timestamp("2026-08-26").date()
    assert len(df) == len(raw)  # artik hicbir satir cikarilmadi


def test_partial_row_cannot_satisfy_minimum_history():
    # HATA 3B madde 3/12: raw=60 (59 completed + 1 partial) -> completed=59 -> INSUFFICIENT_HISTORY.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df(end="2026-08-25", periods=59)
    assert len(completed) == 59
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)
    assert len(raw) == 60  # raw MIN_HISTORY_DAYS(60) sartini "karsiliyormus gibi" gorunuyor

    with pytest.raises(DataQualityError) as exc_info:
        prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_partial_contamination_isolation_two_wildly_different_partial_rows_produce_identical_output():
    # HATA 3B'nin ana regresyon kilidi: iki AYRI partial "bugun" satiri
    # (biri sakin, biri asiri oynak) -- backtest'e HICBIR SEKILDE girmemeli.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-25")

    raw_a = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)
    raw_b = _append_partial_row(completed, "2026-08-26", open_=500.0, close=900.0, volume=999_000_000)

    df_a, as_of_a = prepare_backtest_history(_FakeProvider(raw_a), "TEST", "1y", min_history_days=60, now=now)
    df_b, as_of_b = prepare_backtest_history(_FakeProvider(raw_b), "TEST", "1y", min_history_days=60, now=now)

    assert as_of_a == as_of_b
    pd.testing.assert_frame_equal(df_a, df_b)


def test_weekend_now_does_not_alter_friday_completed_history():
    # Cumartesi (2026-08-29) frozen now -- Cuma (2026-08-28) zaten tamamlanmis,
    # hafta sonu icin hicbir satir yok -- hicbir sey degismemeli.
    now = datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-28")

    df, backtest_data_as_of = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", min_history_days=60, now=now)

    assert backtest_data_as_of == pd.Timestamp("2026-08-28").date()
    assert len(df) == len(completed)


def test_provider_gap_at_boundary_is_hard_vetoed_not_silently_accepted():
    # HATA 3C (26.08.2026): onceki (HATA 3B) davranis "25.08 eksikse
    # backtest_data_as_of sessizce 24.08'e gerilesin, PASS etsin" idi --
    # bu, tam olarak HATA 2B/3'un canli olarak defalarca gozlemledigi gercek
    # senaryo (24.08 var, 25.08 provider'da YOK, 26.08 partial). Artik bu
    # ARTIK sessizce kabul edilmiyor -- latest_expected_completed_date(now)
    # (=2026-08-25) beklenen ust sinira gore 25.08 hala "expected" ve
    # gozlemlenmedigi icin HARD_VETO (MISSING_TRADING_SESSION) olmali.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed_through_24 = _bday_df(end="2026-08-24", periods=120)  # 25.08 hic YOK (holiday DEGIL, gercek bosluk)
    raw = _append_partial_row(completed_through_24, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-08-25").date()]


def test_middle_gap_not_at_boundary_is_hard_vetoed():
    # HATA 3C madde 9: gap tam ortada (ne son bar ne bugunun sinirinda).
    now = datetime(2026, 8, 27, 19, 0, tzinfo=TZ)  # boundary = 27.08 (son gercek bar ile ayni)
    df = _bday_df("2026-01-05", "2026-08-27", exclude=["2026-08-25"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=60, now=now)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-08-25").date()]
    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"


def test_holiday_now_does_not_alter_prior_session_history():
    # Resmi BIST tam gun kapanisi (2026-01-01) frozen now -- son gercek
    # islem gunu (2025-12-31) zaten tamamlanmis, o gun icin Yahoo hic satir
    # dondurmez -- filtre hicbir seyi degistirmemeli (bkz. completed_bars.py
    # docstring: resmi tatilde bu modulun hicbir etkisi yok).
    now = datetime(2026, 1, 1, 12, 0, tzinfo=TZ)
    completed = _bday_df("2025-09-01", "2025-12-31")

    df, backtest_data_as_of = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", min_history_days=60, now=now)

    assert backtest_data_as_of == pd.Timestamp("2025-12-31").date()
    assert len(df) == len(completed)


def test_half_day_2024_04_09_missing_is_hard_vetoed():
    # HATA 3C madde 10: 2024-04-09 (Ramazan Bayramı Arefesi) authoritative
    # HALF-DAY expected session'dır -- eksikse ignore/interpolation YAPILMAZ,
    # tıpkı tam gün bir eksiklik gibi HARD_VETO edilir.
    now = datetime(2024, 4, 30, 19, 0, tzinfo=TZ)
    df = _bday_df("2024-01-02", "2024-04-30", exclude=["2024-04-09"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=60, now=now)

    assert date(2024, 4, 9) in exc_info.value.missing_dates


# ---------------------------------------------------------------------------
# HATA 3C, madde 1: authoritative backtest period sözleşmesi.
# ---------------------------------------------------------------------------


class _AssertNotCalledProvider:
    def get_history(self, symbol: str, period: str = "6mo", **_kwargs):
        raise AssertionError("get_history çağrılmamalıydı — period validasyonu ÖNCE çalışmalı")


@pytest.mark.parametrize("period", sorted(SUPPORTED_BACKTEST_PERIODS))
def test_supported_period_passes_validation(period):
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df(end="2026-08-26", periods=120)
    prepare_backtest_history(_FakeProvider(df), "TEST", period, min_history_days=60, now=now)  # exception atmamalı


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random", ""])
def test_unsupported_period_is_rejected_before_fetching_provider_history(period):
    # Period validasyonu provider.get_history()'DEN ÖNCE çalışır -- ağa hiç
    # gidilmez (bkz. _AssertNotCalledProvider).
    with pytest.raises(ValueError):
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", period, min_history_days=60)


# ---------------------------------------------------------------------------
# HATA 3C-EX (26.08.2026): 08.02.2023 cancelled-session normalizasyonu.
# Resmi kaynak: Anadolu Ajansı, KAP duyurusunu doğrudan aktarıyor — 6 Şubat
# 2023 depremi sonrası devre kesiciler tetiklendi, Borsa İstanbul Pay
# Piyasası'nı 8 Şubat 2023 saat 11:00'den itibaren 5 iş günü kapattı VE
# 8 Şubat 2023'te gerçekleşen TÜM işlemleri BİAŞ Yönetmeliği m.33 uyarınca
# resmi olarak iptal etti. Piyasa 15 Şubat 2023'te yeniden açıldı.
# ---------------------------------------------------------------------------


def _feb_2023_earthquake_df() -> pd.DataFrame:
    # Gerçek gözlemle birebir: 08.02 Open=High=Low=Close (donmuş), ihmal
    # edilebilir hacim -- 09-14.02 Yahoo'da hiç yok (olağanüstü kapanış).
    rows = [
        ("2023-02-07", 135.59, 135.59, 122.0, 124.26, 48_181_521),
        ("2023-02-08", 112.34, 112.34, 112.34, 112.34, 2_500),  # CANCELLED_SESSION
        ("2023-02-15", 132.86, 136.67, 130.0, 136.67, 20_534_049),
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


def test_prepare_backtest_history_drops_08_02_2023_cancelled_bar():
    now = datetime(2023, 2, 15, 19, 0, tzinfo=TZ)  # boundary = 15.02 (son gercek bar ile ayni)
    df = _feb_2023_earthquake_df()

    result_df, backtest_data_as_of = prepare_backtest_history(
        _FakeProvider(df), "THYAO", "1y", min_history_days=2, now=now
    )

    # 08.02 normalizasyon sonrası TAMAMEN gitti -- 07.02 -> 15.02 ardışık.
    assert list(result_df.index.date) == [date(2023, 2, 7), date(2023, 2, 15)]
    assert date(2023, 2, 8) not in result_df.index.date
    assert backtest_data_as_of == date(2023, 2, 15)
    # 09-14.02 (olağanüstü kapanış) veya 08.02'nin kendisi "missing"/"unexpected"
    # olarak HARD_VETO tetiklemiyor -- ikisi de authoritative takvimde
    # "expected" DEĞİL (bkz. BIST_EXTRAORDINARY_CLOSURES/BIST_CANCELLED_SESSIONS).


def test_unexpected_bar_on_planned_holiday_is_hard_vetoed_not_silently_dropped():
    # Genel ("bilinmeyen") bir anomali -- CANCELLED_SESSION olarak
    # TANIMLANMAMIŞ bir tatilde provider bar döndürürse bu authoritative
    # olarak düşürülmez, HARD VETO edilir (drop_cancelled_sessions yalnızca
    # BIST_CANCELLED_SESSIONS'ta AÇIKÇA tanımlı tarihler için çalışır).
    now = datetime(2026, 5, 8, 19, 0, tzinfo=TZ)
    valid_before = _bday_df("2026-04-01", "2026-04-30")
    bogus_holiday_row = pd.DataFrame(
        {"Open": [50.0], "High": [51.0], "Low": [49.0], "Close": [50.0], "Volume": [100]},
        index=[pd.Timestamp("2026-05-01", tz=TZ)],  # 1 Mayıs -- resmi tatil, gerçekte hiç bar olmamalı
    )
    valid_after = _bday_df("2026-05-04", "2026-05-08")
    df = pd.concat([valid_before, bogus_holiday_row, valid_after]).sort_index()

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=10, now=now)

    assert exc_info.value.reason_code == "UNEXPECTED_TRADING_SESSION"
    assert exc_info.value.unexpected_dates == [date(2026, 5, 1)]
    assert exc_info.value.missing_dates == []
