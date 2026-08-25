from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import TradingCalendarUnsupportedError, check_trading_day_continuity
from app.services.market_data.trading_calendar import (
    BIST_FULL_DAY_CLOSURES,
    BIST_HALF_DAY_SESSIONS,
    expected_trading_sessions,
    is_full_day_closure,
    is_year_supported,
)

TZ = ZoneInfo("Europe/Istanbul")


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


# ---------------------------------------------------------------------------
# A. Tüm tam-gün kapanışlar expected_trading_sessions'ta BULUNMAMALI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "closure_date",
    sorted({d for closures in BIST_FULL_DAY_CLOSURES.values() for d in closures}),
    ids=lambda d: d.isoformat(),
)
def test_full_day_closure_is_excluded_from_expected_sessions(closure_date):
    assert is_full_day_closure(closure_date) is True
    start, end = _year_bounds(closure_date.year)
    sessions = expected_trading_sessions(start, end)
    assert closure_date not in sessions


# ---------------------------------------------------------------------------
# B. Tüm bilinen yarım günler expected_trading_sessions'ta KALMALI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "half_day",
    sorted({d for half_days in BIST_HALF_DAY_SESSIONS.values() for d in half_days}),
    ids=lambda d: d.isoformat(),
)
def test_half_day_session_remains_expected_trading_day(half_day):
    assert is_full_day_closure(half_day) is False
    start, end = _year_bounds(half_day.year)
    sessions = expected_trading_sessions(start, end)
    assert half_day in sessions


# ---------------------------------------------------------------------------
# C. Sıradan bir hafta içi işlem günü beklenen listede bulunmalı
# ---------------------------------------------------------------------------


def test_ordinary_weekday_is_expected_trading_day():
    # 2026-08-18 Salı — ne hafta sonu ne resmi tatil.
    ordinary_day = date(2026, 8, 18)
    assert ordinary_day.weekday() < 5
    assert is_full_day_closure(ordinary_day) is False
    sessions = expected_trading_sessions(date(2026, 8, 17), date(2026, 8, 21))
    assert ordinary_day in sessions


# ---------------------------------------------------------------------------
# D. Cumartesi/Pazar beklenen listede HİÇ bulunmamalı
# ---------------------------------------------------------------------------


def test_weekend_days_are_never_expected():
    saturday = date(2026, 8, 22)
    sunday = date(2026, 8, 23)
    assert saturday.weekday() == 5
    assert sunday.weekday() == 6
    assert is_full_day_closure(saturday) is True
    assert is_full_day_closure(sunday) is True
    sessions = expected_trading_sessions(date(2026, 8, 21), date(2026, 8, 24))
    assert saturday not in sessions
    assert sunday not in sessions


# ---------------------------------------------------------------------------
# E. Desteklenmeyen yıl — sessizce tahmin YOK, açık hata
# ---------------------------------------------------------------------------


def test_unsupported_year_returns_false_and_expected_sessions_is_none():
    assert is_year_supported(2024) is False
    assert is_year_supported(2027) is False
    assert expected_trading_sessions(date(2024, 1, 1), date(2024, 1, 5)) is None


def test_unsupported_year_raises_explicit_error_via_continuity_check():
    rng = np.random.default_rng(1)
    dates = pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz=TZ), pd.Timestamp("2024-01-03", tz=TZ)])
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100]},
        index=dates,
    )
    now = datetime(2024, 1, 3, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)
    assert exc_info.value.year == 2024


# ---------------------------------------------------------------------------
# F. Bir yıllık seansta duplicate OLMAMALI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", [2025, 2026])
def test_full_year_sessions_have_no_duplicates(year):
    start, end = _year_bounds(year)
    sessions = expected_trading_sessions(start, end)
    assert sessions is not None
    assert len(sessions) == len(set(sessions))
    assert sessions == sorted(sessions)


# ---------------------------------------------------------------------------
# G. Yıl geçişi (2025 -> 2026) doğru çalışmalı
# ---------------------------------------------------------------------------


def test_year_boundary_crossing_2025_to_2026():
    # 29.12.2025 (Pzt) - 02.01.2026 (Cuma) arasi: 1 Ocak 2026 (Persembe) tam
    # gun tatil olmali, digerleri (haftasonu haric) beklenen gun olmali.
    start = date(2025, 12, 29)
    end = date(2026, 1, 2)
    sessions = expected_trading_sessions(start, end)

    assert sessions is not None
    assert date(2026, 1, 1) not in sessions  # Yılbaşı
    assert date(2025, 12, 29) in sessions  # Pazartesi
    assert date(2025, 12, 30) in sessions  # Salı
    assert date(2025, 12, 31) in sessions  # Çarşamba
    assert date(2026, 1, 2) in sessions  # Cuma
    assert len(sessions) == len(set(sessions))


def test_year_boundary_crossing_works_through_continuity_check():
    # Ayni yil-gecisi araligi, hicbir bosluk olmadan continuity check'ten
    # de sorunsuz gecmeli (iki farkli yilin takvimi dogru birlestiriliyor).
    dates = [
        "2025-12-29",
        "2025-12-30",
        "2025-12-31",
        "2026-01-02",  # 1 Ocak (Persembe) resmi tatil, seride hic yok -> beklenmedik degil
    ]
    rng = np.random.default_rng(2)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates])
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": np.arange(len(dates)) + 1000},
        index=index,
    )
    now = datetime(2026, 1, 2, 19, 0, tzinfo=TZ)

    check_trading_day_continuity(df, "TEST", now=now)  # exception atmamalı
