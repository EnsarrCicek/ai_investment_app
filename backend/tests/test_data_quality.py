from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import (
    DataQualityError,
    TradingCalendarUnsupportedError,
    TradingDayContinuityError,
    check_data_quality,
    check_trading_day_continuity,
)

TZ = ZoneInfo("Europe/Istanbul")

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _fresh_df(rows: int = 80, end: pd.Timestamp | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(rng.normal(0, 1, rows))
    idx = pd.date_range(end=end or pd.Timestamp(_NOW), periods=rows, freq="D")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 1,
            "Low": closes - 1,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, rows),
        },
        index=idx,
    )


def test_passes_with_fresh_sufficient_data():
    df = _fresh_df(rows=80)
    check_data_quality(df, "TEST", min_history_days=60, now=_NOW)  # exception atmamalı


def test_rejects_insufficient_history():
    df = _fresh_df(rows=30)
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_rejects_missing_columns():
    df = _fresh_df(rows=80).drop(columns=["Volume"])
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "MISSING_COLUMNS"


def test_rejects_missing_ohlcv_in_last_row():
    df = _fresh_df(rows=80)
    df.iloc[-1, df.columns.get_loc("Close")] = np.nan
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "MISSING_OHLCV"


def test_rejects_stale_data():
    stale_end = pd.Timestamp(_NOW) - timedelta(days=10)
    df = _fresh_df(rows=80, end=stale_end)
    with pytest.raises(DataQualityError) as exc_info:
        check_data_quality(df, "TEST", min_history_days=60, now=_NOW)
    assert exc_info.value.reason_code == "STALE_DATA"


def test_allows_data_within_staleness_tolerance():
    recent_end = pd.Timestamp(_NOW) - timedelta(days=3)  # hafta sonu toleransı içinde
    df = _fresh_df(rows=80, end=recent_end)
    check_data_quality(df, "TEST", min_history_days=60, max_staleness_days=5, now=_NOW)


# ---------------------------------------------------------------------------
# HATA 2B (25.08.2026): BIST'in resmi işlem takvimine göre beklenen ama
# seride bulunmayan işlem günleri — bkz. trading_calendar.py.
# ---------------------------------------------------------------------------


def _df_for_dates(dates: list[str]) -> pd.DataFrame:
    n = len(dates)
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0, 1, n))
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates])
    return pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": np.arange(n) + 1000},
        index=index,
    )


def test_continuity_passes_when_no_gaps():
    # 17-21 Agustos 2026: Pzt-Cuma, tatil yok, hepsi mevcut.
    df = _df_for_dates(["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"])
    now = datetime(2026, 8, 21, 19, 0, tzinfo=TZ)  # kapanis + finalization payi gecti
    check_trading_day_continuity(df, "TEST", now=now)  # exception atmamali


def test_continuity_detects_missing_expected_trading_day():
    # 24.08.2026 regresyonu: beklenen seanslar 21-24-25 Agustos, THYAO
    # verisinde 24'u yok.
    df = _df_for_dates(["2026-08-21", "2026-08-25"])
    now = datetime(2026, 8, 25, 19, 0, tzinfo=TZ)
    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "THYAO", now=now)

    err = exc_info.value
    assert err.reason_code == "MISSING_TRADING_SESSION"
    assert err.symbol == "THYAO"
    assert err.missing_dates == [date(2026, 8, 24)]
    assert err.first_missing_date == date(2026, 8, 24)
    assert err.latest_missing_date == date(2026, 8, 24)
    assert err.missing_count == 1
    assert err.checked_period == (date(2026, 8, 21), date(2026, 8, 25))
    assert err.severity == "HARD_VETO"
    assert err.provider == "yahoo_finance"


def test_continuity_uses_now_boundary_beyond_last_observed_bar():
    # HATA 2B'de canli veriyle yakalanan regresyon: completed-bar filtresi
    # "bugunu" (25.08) cikarinca df'in son satiri 21.08'e geri cekilebilir --
    # ama 24.08'deki bosluk YINE DE goz ardi edilmemeli, cunku `now`'a gore
    # beklenen sinir (latest_expected_completed_date) 24.08'e kadar uzaniyor.
    df = _df_for_dates(["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"])
    now = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)  # piyasa acik, boundary=24.08
    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    assert exc_info.value.missing_dates == [date(2026, 8, 24)]


def test_continuity_passes_when_missing_date_is_an_official_holiday():
    # 1 Mayis 2026 Cuma resmi tatil -- seride hic olmamasi beklenen/dogru durum.
    df = _df_for_dates(["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30", "2026-05-04"])
    now = datetime(2026, 5, 4, 19, 0, tzinfo=TZ)
    check_trading_day_continuity(df, "TEST", now=now)  # exception atmamali


def test_continuity_passes_for_pre_listing_period():
    # Kontrol yalnizca serinin KENDI ilk barindan itibaren calisir --
    # ondan ONCEki hicbir gun "beklenen" sayilmaz.
    df = _df_for_dates(["2026-08-20", "2026-08-21"])
    now = datetime(2026, 8, 21, 19, 0, tzinfo=TZ)
    check_trading_day_continuity(df, "YENI_HALKA_ARZ", now=now)  # exception atmamali


def test_continuity_detects_consecutive_missing_sessions():
    # D1, D2 eksik, D3 eksik, D4 -> iki ardisik eksik gun de raporlanmali.
    df = _df_for_dates(["2026-08-17", "2026-08-20"])  # 18 (Sal) ve 19 (Car) eksik
    now = datetime(2026, 8, 20, 19, 0, tzinfo=TZ)
    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    assert exc_info.value.missing_dates == [date(2026, 8, 18), date(2026, 8, 19)]
    assert exc_info.value.missing_count == 2


def test_continuity_raises_for_unsupported_calendar_year():
    # HATA 3C (26.08.2026): takvim artik 2021-2026'yi kapsiyor -- 2027
    # (henuz eklenmedi) icin BIST_FULL_DAY_CLOSURES tanimli degil -- sessizce
    # tahmin YOK.
    df = _df_for_dates(["2027-08-23", "2027-08-24"])
    now = datetime(2027, 8, 24, 19, 0, tzinfo=TZ)
    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    assert exc_info.value.reason_code == "TRADING_CALENDAR_UNSUPPORTED_YEAR"
    assert exc_info.value.year == 2027


def test_continuity_empty_dataframe_is_noop():
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    check_trading_day_continuity(df, "TEST")  # exception atmamali
