from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.services.market_data.completed_bars import filter_completed_daily_bars

TZ = ZoneInfo("Europe/Istanbul")


def _df(dates: list[str]) -> pd.DataFrame:
    n = len(dates)
    rng = np.random.default_rng(1)
    closes = 100 + np.cumsum(rng.normal(0, 1, n))
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates])
    return pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": np.arange(n) + 1000},
        index=index,
    )


def test_market_open_excludes_todays_partial_bar():
    # 2026-08-26 Carsamba, piyasa acik (13:00), bugunun bari mevcut -> atilmali.
    df = _df(["2026-08-24", "2026-08-25", "2026-08-26"])
    now = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)

    result = filter_completed_daily_bars(df, now=now)

    assert len(result) == 2
    assert result.index[-1].date() == pd.Timestamp("2026-08-25").date()


def test_market_closed_past_finalization_delay_includes_todays_bar():
    # Kapanistan (18:00) 60 dk sonra -> DAILY_BAR_FINALIZATION_DELAY_MINUTES (30dk) asildi -> dahil et.
    df = _df(["2026-08-24", "2026-08-25", "2026-08-26"])
    now = datetime(2026, 8, 26, 19, 0, tzinfo=TZ)

    result = filter_completed_daily_bars(df, now=now)

    assert len(result) == 3
    assert result.index[-1].date() == pd.Timestamp("2026-08-26").date()


def test_just_after_close_but_within_finalization_delay_still_excluded():
    # 18:10 -> kapanistan yalnizca 10 dk sonra, 30 dk'lik pay dolmadi -> koru bekletme (haric tut).
    # Bu, kor "clock >= 18:00" kuralinin UYGULANMADIGINI kanitlar.
    df = _df(["2026-08-24", "2026-08-25", "2026-08-26"])
    now = datetime(2026, 8, 26, 18, 10, tzinfo=TZ)

    result = filter_completed_daily_bars(df, now=now)

    assert len(result) == 2


def test_weekend_preserves_last_trading_day():
    # 'now' Cumartesi, son bar Cuma -> son bar bugune ait degil, dokunulmaz.
    df = _df(["2026-08-24", "2026-08-25", "2026-08-28"])  # son bar Cuma (28)
    now = datetime(2026, 8, 29, 11, 0, tzinfo=TZ)  # Cumartesi

    result = filter_completed_daily_bars(df, now=now)

    assert len(result) == 3
    assert result.index[-1].date() == pd.Timestamp("2026-08-28").date()


def test_holiday_with_no_bar_today_does_not_delete_last_valid_bar():
    # 'now' Carsamba ama bugunku satir hic yok (resmi tatil) -> son gecerli bar (Pazartesi) silinmez.
    df = _df(["2026-08-21", "2026-08-24"])  # son bar Pazartesi (24)
    now = datetime(2026, 8, 26, 14, 0, tzinfo=TZ)  # Carsamba, bugunun satiri df'te YOK

    result = filter_completed_daily_bars(df, now=now)

    assert len(result) == 2
    assert result.index[-1].date() == pd.Timestamp("2026-08-24").date()


def test_empty_dataframe_returns_unchanged():
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    result = filter_completed_daily_bars(df, now=datetime(2026, 8, 26, 13, 0, tzinfo=TZ))
    assert result.empty


def test_deterministic_for_same_inputs():
    df = _df(["2026-08-24", "2026-08-25", "2026-08-26"])
    now = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)

    result1 = filter_completed_daily_bars(df, now=now)
    result2 = filter_completed_daily_bars(df, now=now)

    pd.testing.assert_frame_equal(result1, result2)
