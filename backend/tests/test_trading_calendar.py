from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import (
    TradingCalendarUnsupportedError,
    TradingDayContinuityError,
    check_trading_day_continuity,
)
from app.services.market_data.trading_calendar import (
    BIST_CANCELLED_SESSIONS,
    BIST_EXTRAORDINARY_CLOSURES,
    BIST_FULL_DAY_CLOSURES,
    BIST_HALF_DAY_SESSIONS,
    drop_cancelled_sessions,
    expected_trading_sessions,
    is_cancelled_session,
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
    # HATA 3C (26.08.2026): takvim artik 2021-2026'yi kapsiyor -- 2027 (henuz
    # eklenmedi) yeni "unsupported" ornegi.
    assert is_year_supported(2020) is False
    assert is_year_supported(2027) is False
    assert expected_trading_sessions(date(2027, 1, 1), date(2027, 1, 5)) is None


def test_unsupported_year_raises_explicit_error_via_continuity_check():
    rng = np.random.default_rng(1)
    dates = pd.DatetimeIndex([pd.Timestamp("2027-01-04", tz=TZ), pd.Timestamp("2027-01-05", tz=TZ)])
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100]},
        index=dates,
    )
    now = datetime(2027, 1, 5, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)
    assert exc_info.value.year == 2027


# ---------------------------------------------------------------------------
# F. Bir yıllık seansta duplicate OLMAMALI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", [2021, 2022, 2023, 2024, 2025, 2026])
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


# ---------------------------------------------------------------------------
# H. HATA 3C-EX (26.08.2026): olağanüstü kapanış / iptal edilmiş seans
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extraordinary_date",
    sorted({d for closures in BIST_EXTRAORDINARY_CLOSURES.values() for d in closures}),
    ids=lambda d: d.isoformat(),
)
def test_extraordinary_closure_is_excluded_from_expected_sessions(extraordinary_date):
    assert is_full_day_closure(extraordinary_date) is True
    start, end = _year_bounds(extraordinary_date.year)
    sessions = expected_trading_sessions(start, end)
    assert extraordinary_date not in sessions


@pytest.mark.parametrize(
    "cancelled_date",
    sorted({d for sessions in BIST_CANCELLED_SESSIONS.values() for d in sessions}),
    ids=lambda d: d.isoformat(),
)
def test_cancelled_session_is_excluded_from_expected_sessions(cancelled_date):
    assert is_cancelled_session(cancelled_date) is True
    assert is_full_day_closure(cancelled_date) is True
    start, end = _year_bounds(cancelled_date.year)
    sessions = expected_trading_sessions(start, end)
    assert cancelled_date not in sessions


def test_drop_cancelled_sessions_removes_only_the_08_02_2023_bar():
    # 08.02.2023: seans fiilen açıldı ama TÜM işlemler resmi olarak iptal
    # edildi (bkz. modül docstring'i, Anadolu Ajansı/KAP kaynağı) — Yahoo
    # hâlâ bir bar döndürüyor (07.02/09-14.02/15.02'nin aksine bu tarih
    # `BIST_CANCELLED_SESSIONS`'ta AÇIKÇA tanımlı).
    dates = pd.to_datetime(["2023-02-07", "2023-02-08", "2023-02-15"])
    df = pd.DataFrame({"Close": [124.26, 112.34, 136.67]}, index=dates)

    result = drop_cancelled_sessions(df)

    assert list(result.index.date) == [date(2023, 2, 7), date(2023, 2, 15)]


def test_drop_cancelled_sessions_is_noop_when_no_cancelled_date_present():
    dates = pd.to_datetime(["2026-08-24", "2026-08-25"])
    df = pd.DataFrame({"Close": [100.0, 101.0]}, index=dates)

    result = drop_cancelled_sessions(df)

    pd.testing.assert_frame_equal(result, df)


def test_drop_cancelled_sessions_empty_dataframe_is_noop():
    df = pd.DataFrame(columns=["Close"])
    result = drop_cancelled_sessions(df)
    assert result.empty


# ---------------------------------------------------------------------------
# I. HATA 3C (26.08.2026): "unexpected" (missing-only kör noktasının düzeltmesi)
# ---------------------------------------------------------------------------


def test_continuity_detects_unexpected_bar_on_a_planned_holiday():
    # 1 Mayıs 2026 (Cuma) resmi tatil -- provider'ın burada AÇIKLANAMAYAN bir
    # bar döndürmesi (holiday'de asla olmaması gereken bir veri) artık
    # sessizce kabul edilmiyor.
    dates = pd.to_datetime(["2026-04-30", "2026-05-01", "2026-05-04"])  # 05-01 resmi tatil
    rng = np.random.default_rng(11)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100, 1200]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates]),
    )
    now = datetime(2026, 5, 4, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    err = exc_info.value
    assert err.reason_code == "UNEXPECTED_TRADING_SESSION"
    assert err.unexpected_dates == [date(2026, 5, 1)]
    assert err.unexpected_count == 1
    assert err.missing_dates == []
    assert err.severity == "HARD_VETO"


def test_continuity_detects_unexpected_bar_on_saturday():
    # HATA 3C commit-öncesi düzeltme (26.08.2026): hafta sonu için ÖZEL BİR
    # İSTİSNA YOK — Cumartesi/Pazar barı da diğer non-session barlar gibi
    # açıklanamıyorsa HARD VETO edilir. 21.08.2026 Cuma (geçerli), 22.08.2026
    # Cumartesi (bogus/açıklanamayan bar), 24.08.2026 Pazartesi (geçerli).
    dates = ["2026-08-21", "2026-08-22", "2026-08-24"]
    rng = np.random.default_rng(13)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100, 1200]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates]),
    )
    now = datetime(2026, 8, 24, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    err = exc_info.value
    assert err.reason_code == "UNEXPECTED_TRADING_SESSION"
    assert err.unexpected_dates == [date(2026, 8, 22)]
    assert err.missing_dates == []


def test_continuity_detects_unexpected_bar_on_sunday():
    # Aynı senaryo Pazar için: 21.08.2026 Cuma (geçerli), 23.08.2026 Pazar
    # (bogus), 24.08.2026 Pazartesi (geçerli).
    dates = ["2026-08-21", "2026-08-23", "2026-08-24"]
    rng = np.random.default_rng(14)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100, 1200]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates]),
    )
    now = datetime(2026, 8, 24, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    err = exc_info.value
    assert err.reason_code == "UNEXPECTED_TRADING_SESSION"
    assert err.unexpected_dates == [date(2026, 8, 23)]
    assert err.missing_dates == []


def test_continuity_reports_both_missing_and_unexpected_when_both_present():
    # HATA 3C, madde 7: ayni history'de HEM missing HEM unexpected varsa
    # ikisi de dolu tasinmali. 21.08 Cuma (gecerli), 24.08 Pazartesi
    # EKSIK (missing), 25.08 Sali (gecerli), 22.08 Cumartesi'de BOGUS bir
    # bar (unexpected).
    dates = ["2026-08-21", "2026-08-22", "2026-08-25"]  # 24.08 (Pzt) eksik, 22.08 (Cmt) bogus
    rng = np.random.default_rng(15)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100, 1200]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates]),
    )
    now = datetime(2026, 8, 25, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    err = exc_info.value
    assert err.missing_dates == [date(2026, 8, 24)]
    assert err.unexpected_dates == [date(2026, 8, 22)]
    # Geriye dönük uyumluluk: missing_dates doluyken reason_code her zaman
    # "MISSING_TRADING_SESSION" kalır (bkz. data_quality.py — mevcut
    # caller'ların hiçbiri kırılmasın diye bilinçli bir öncelik sırası).
    assert err.reason_code == "MISSING_TRADING_SESSION"
