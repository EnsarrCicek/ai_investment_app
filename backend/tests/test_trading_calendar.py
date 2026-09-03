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
    SUPPORTED_BIST_CALENDAR_YEARS,
    DroppedSession,
    NonSessionClassification,
    SessionNormalizationResult,
    classify_non_session_day,
    expected_trading_sessions,
    first_expected_session_on_or_after,
    is_cancelled_session,
    is_full_day_closure,
    is_year_supported,
    last_expected_trading_session_of_week,
    normalize_bist_daily_sessions,
    session_normalization_to_dict,
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


# ---------------------------------------------------------------------------
# E2. HATA 10E — last_expected_trading_session_of_week(): "tamamlanmış hafta"
# artık Cuma DEĞİL, o ISO haftanın authoritative takvimdeki SON beklenen
# BIST işlem günüdür. Gerçek, belgelenmiş takvim örnekleri kullanılır --
# sentetik/uydurma tarih YOK (yalnızca F için, gerçek takvimde sıfır-seanslı
# bir hafta bulunmadığından, `expected_trading_sessions`'ı monkeypatch eder).
# ---------------------------------------------------------------------------


def test_last_expected_session_of_week_normal_week_is_friday():
    # 2026-08-17 haftası (Pzt-Cuma), hiçbir tatil yok.
    assert last_expected_trading_session_of_week(date(2026, 8, 18)) == date(2026, 8, 21)


def test_last_expected_session_of_week_friday_holiday_is_thursday():
    # 2026-03-20 Cuma = Ramazan Bayramı (tam kapanış) -- hafta Perşembe (19) biter.
    assert date(2026, 3, 20) in BIST_FULL_DAY_CLOSURES[2026]
    assert last_expected_trading_session_of_week(date(2026, 3, 17)) == date(2026, 3, 19)
    assert last_expected_trading_session_of_week(date(2026, 3, 19)) == date(2026, 3, 19)


def test_last_expected_session_of_week_thursday_and_friday_holiday_is_wednesday():
    # 2021-05-13/14 = Ramazan Bayramı (tam kapanış, Per+Cuma) -- hafta Çarşamba (12) biter.
    assert date(2021, 5, 13) in BIST_FULL_DAY_CLOSURES[2021]
    assert date(2021, 5, 14) in BIST_FULL_DAY_CLOSURES[2021]
    assert last_expected_trading_session_of_week(date(2021, 5, 10)) == date(2021, 5, 12)


def test_last_expected_session_of_week_multiday_holiday_is_tuesday():
    # 2026-05-27/28/29 = Kurban Bayramı (Çrş-Per-Cuma tam kapanış) -- hafta Salı (26) biter.
    for d in (date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29)):
        assert d in BIST_FULL_DAY_CLOSURES[2026]
    assert last_expected_trading_session_of_week(date(2026, 5, 25)) == date(2026, 5, 26)


def test_last_expected_session_of_week_half_day_final_session_still_eligible():
    # 2026-03-19 (Ramazan Bayramı Arefesi) ve 2026-05-26 (Kurban Bayramı
    # Arefesi) yarım gündür AMA authoritative takvimde expected session'dır
    # -- her ikisi de kendi haftalarının SON beklenen günü olarak dönmeli.
    assert date(2026, 3, 19) in BIST_HALF_DAY_SESSIONS[2026]
    assert is_full_day_closure(date(2026, 3, 19)) is False
    assert last_expected_trading_session_of_week(date(2026, 3, 19)) == date(2026, 3, 19)

    assert date(2026, 5, 26) in BIST_HALF_DAY_SESSIONS[2026]
    assert is_full_day_closure(date(2026, 5, 26)) is False
    assert last_expected_trading_session_of_week(date(2026, 5, 26)) == date(2026, 5, 26)


def test_last_expected_session_of_week_returns_none_for_unsupported_year():
    assert last_expected_trading_session_of_week(date(2027, 1, 5)) is None


def test_last_expected_session_of_week_returns_none_when_zero_sessions_expected(monkeypatch):
    # Gerçek BIST takviminde sıfır-seanslı bir hafta yok -- bu, mimariyi
    # (fabrikasyon YOK) doğrulamak için yalnızca `expected_trading_sessions`'ı
    # izole eden bir birim testidir.
    import app.services.market_data.trading_calendar as calendar_module

    monkeypatch.setattr(calendar_module, "expected_trading_sessions", lambda start, end: [])
    assert calendar_module.last_expected_trading_session_of_week(date(2026, 8, 18)) is None


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


# ---------------------------------------------------------------------------
# H2. HATA 3D (26.08.2026): shared authoritative non-session normalization.
# ---------------------------------------------------------------------------


def test_classify_non_session_day_returns_none_for_expected_sessions():
    # Sıradan hafta içi gün VE yarım gün — ikisi de "expected", None döner.
    assert classify_non_session_day(date(2026, 8, 18)) is None  # sıradan Salı
    assert classify_non_session_day(date(2024, 4, 9)) is None  # HALF_DAY (Ramazan Arefesi)


def test_classify_non_session_day_weekend():
    assert classify_non_session_day(date(2026, 8, 22)) == NonSessionClassification.WEEKEND  # Cumartesi
    assert classify_non_session_day(date(2026, 8, 23)) == NonSessionClassification.WEEKEND  # Pazar


def test_classify_non_session_day_planned_full_day_closure():
    assert classify_non_session_day(date(2026, 5, 1)) == NonSessionClassification.PLANNED_FULL_DAY_CLOSURE


def test_classify_non_session_day_extraordinary_closure():
    assert classify_non_session_day(date(2023, 2, 9)) == NonSessionClassification.EXTRAORDINARY_CLOSURE


def test_classify_non_session_day_cancelled_session_not_confused_with_planned():
    # KRİTİK: 08.02.2023 CANCELLED_SESSION olarak sınıflandırılmalı, genel
    # bir "tatil" (PLANNED_FULL_DAY_CLOSURE) ile KARIŞTIRILMAMALI —
    # provenance kaybolmamalı.
    assert classify_non_session_day(date(2023, 2, 8)) == NonSessionClassification.CANCELLED_SESSION


def test_normalize_bist_daily_sessions_drops_08_02_2023_with_correct_classification():
    # 08.02.2023: seans fiilen açıldı ama TÜM işlemler resmi olarak iptal
    # edildi (bkz. modül docstring'i, Anadolu Ajansı/KAP kaynağı) — Yahoo
    # hâlâ bir bar döndürüyor.
    dates = pd.to_datetime(["2023-02-07", "2023-02-08", "2023-02-15"])
    df = pd.DataFrame({"Close": [124.26, 112.34, 136.67]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df, symbol="THYAO", provider="yahoo_finance")

    assert list(result_df.index.date) == [date(2023, 2, 7), date(2023, 2, 15)]
    assert len(result.dropped_sessions) == 1
    assert result.dropped_sessions[0].date == date(2023, 2, 8)
    assert result.dropped_sessions[0].classification == "CANCELLED_SESSION"
    assert result.policy == "AUTHORITATIVE_NON_SESSION_DROP"


def test_normalize_bist_daily_sessions_drops_planned_holiday_phantom_regardless_of_content():
    # HATA 3D madde 8: 27-29 Mayıs 2026 (Kurban Bayramı) gerçek Yahoo
    # deseni — Open=High=Low=Close=önceki kapanış, Volume=0. Karar SADECE
    # takvime dayanmalı; bu OHLC/Volume değerleri BİLE OLMASA (aşağıdaki
    # ikinci testte) AYNI şekilde düşürülmeli.
    dates = pd.to_datetime(["2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01"])
    df = pd.DataFrame(
        {
            "Open": [297.5, 296.75, 296.75, 296.75, 298.5],
            "High": [298.0, 296.75, 296.75, 296.75, 300.5],
            "Low": [295.25, 296.75, 296.75, 296.75, 291.0],
            "Close": [296.75, 296.75, 296.75, 296.75, 291.5],
            "Volume": [11744557, 0, 0, 0, 43996715],
        },
        index=dates,
    )

    result_df, result = normalize_bist_daily_sessions(df)

    assert list(result_df.index.date) == [date(2026, 5, 26), date(2026, 6, 1)]
    assert [d.classification for d in result.dropped_sessions] == [
        "PLANNED_FULL_DAY_CLOSURE",
        "PLANNED_FULL_DAY_CLOSURE",
        "PLANNED_FULL_DAY_CLOSURE",
    ]


def test_normalize_bist_daily_sessions_drops_planned_holiday_even_with_non_phantom_values():
    # HATA 3D madde 8 (ikinci kısım): karar Volume=0/OHLC-eşitliği
    # HEURİSTİĞİNE dayanmıyor — aynı 3 tarihte tamamen FARKLI, "phantom
    # olmayan" sentetik değerler (Volume>0, OHLC birbirinden farklı)
    # kullanılsa BİLE takvim authoritative olduğundan yine DÜŞÜRÜLMELİ.
    dates = pd.to_datetime(["2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01"])
    df = pd.DataFrame(
        {
            "Open": [297.5, 310.0, 305.0, 320.0, 298.5],
            "High": [298.0, 315.0, 308.0, 325.0, 300.5],
            "Low": [295.25, 305.0, 300.0, 315.0, 291.0],
            "Close": [296.75, 312.0, 306.0, 318.0, 291.5],
            "Volume": [11744557, 5_000_000, 3_200_000, 7_100_000, 43996715],
        },
        index=dates,
    )

    result_df, result = normalize_bist_daily_sessions(df)

    assert list(result_df.index.date) == [date(2026, 5, 26), date(2026, 6, 1)]
    assert len(result.dropped_sessions) == 3


def test_normalize_bist_daily_sessions_drops_weekend_bar():
    # Cuma geçerli, Cumartesi bogus provider bar, Pazartesi geçerli.
    dates = pd.to_datetime(["2026-08-21", "2026-08-22", "2026-08-24"])
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df)

    assert list(result_df.index.date) == [date(2026, 8, 21), date(2026, 8, 24)]
    assert result.dropped_sessions == [DroppedSession(date=date(2026, 8, 22), classification="WEEKEND")]


def test_normalize_bist_daily_sessions_never_drops_a_half_day():
    # 2024-04-09 authoritative HALF-DAY — bar varsa KEEP edilmeli.
    dates = pd.to_datetime(["2024-04-08", "2024-04-09", "2024-04-15"])
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df)

    assert list(result_df.index.date) == [date(2024, 4, 8), date(2024, 4, 9), date(2024, 4, 15)]
    assert result.dropped_sessions == []


def test_normalize_bist_daily_sessions_extraordinary_closure_regression():
    # HATA 3D madde 9: 09-14.02.2023 EXTRAORDINARY_CLOSURE -- provider
    # yanlışlıkla bar döndürürse DROP + doğru classification.
    dates = pd.to_datetime(["2023-02-08", "2023-02-09", "2023-02-10", "2023-02-15"])
    df = pd.DataFrame({"Close": [112.34, 999.0, 998.0, 136.67]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df)

    dropped_by_date = {d.date: d.classification for d in result.dropped_sessions}
    assert dropped_by_date[date(2023, 2, 8)] == "CANCELLED_SESSION"
    assert dropped_by_date[date(2023, 2, 9)] == "EXTRAORDINARY_CLOSURE"
    assert dropped_by_date[date(2023, 2, 10)] == "EXTRAORDINARY_CLOSURE"
    assert list(result_df.index.date) == [date(2023, 2, 15)]


def test_normalize_bist_daily_sessions_does_not_mask_a_real_missing_session():
    # HATA 3D madde 7: Cuma provider'da YOK (gerçek boşluk, tatil DEĞİL),
    # Cumartesi bogus bar VAR, Pazartesi var. Normalizasyon Cumartesi'yi
    # düşürür ama Cuma'nın GERÇEKTEN eksik olduğu gerçeğini MASKELEMEMELİ —
    # continuity ayrı bir katman, bu test yalnızca normalize'ın DataFrame'i
    # doğru ürettiğini kanıtlıyor (continuity ayrı testte, aşağıda).
    dates = pd.to_datetime(["2026-08-20", "2026-08-22", "2026-08-24"])  # 21.08 (Cuma) provider'da YOK
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df)

    assert list(result_df.index.date) == [date(2026, 8, 20), date(2026, 8, 24)]  # 22.08 (Cmt) düşürüldü
    assert result.dropped_sessions == [DroppedSession(date=date(2026, 8, 22), classification="WEEKEND")]


def test_normalize_bist_daily_sessions_is_noop_when_all_days_expected():
    dates = pd.to_datetime(["2026-08-24", "2026-08-25"])
    df = pd.DataFrame({"Close": [100.0, 101.0]}, index=dates)

    result_df, result = normalize_bist_daily_sessions(df)

    pd.testing.assert_frame_equal(result_df, df)
    assert result.dropped_sessions == []


def test_normalize_bist_daily_sessions_empty_dataframe_is_noop():
    df = pd.DataFrame(columns=["Close"])
    result_df, result = normalize_bist_daily_sessions(df)
    assert result_df.empty
    assert result.dropped_sessions == []


def test_session_normalization_to_dict_is_backward_compatible_shape():
    empty_dict = session_normalization_to_dict(SessionNormalizationResult())
    assert empty_dict == {
        "session_normalization_policy": "AUTHORITATIVE_NON_SESSION_DROP",
        "normalized_dropped_sessions": [],
    }

    dates = pd.to_datetime(["2023-02-07", "2023-02-08", "2023-02-15"])
    df = pd.DataFrame({"Close": [124.26, 112.34, 136.67]}, index=dates)
    _, result = normalize_bist_daily_sessions(df)
    non_empty_dict = session_normalization_to_dict(result)
    assert non_empty_dict == {
        "session_normalization_policy": "AUTHORITATIVE_NON_SESSION_DROP",
        "normalized_dropped_sessions": [{"date": "2023-02-08", "classification": "CANCELLED_SESSION"}],
    }


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


# ---------------------------------------------------------------------------
# HATA 10E, madde 16/25: takvim haftanın SON beklenen günü olarak Perşembe'yi
# (2026-03-19, Cuma=Ramazan Bayramı tam kapanış) bildirirken, provider verisi
# Çarşamba'da (2026-03-18) biterse -- haftalık MTF tamamlanma mantığı bunu
# SESSİZCE "Çarşamba haftanın sonuymuş gibi" KABUL ETMEMELİDİR; bu senaryo
# zaten yukarı akıştaki continuity hard-veto'sunda YAKALANMALIDIR (weekly
# fallback'e HİÇ ULAŞILMAZ).
# ---------------------------------------------------------------------------


def test_continuity_catches_missing_final_session_before_weekly_fallback_could_apply():
    dates = ["2026-03-16", "2026-03-17", "2026-03-18"]  # Perşembe (19) EKSİK
    rng = np.random.default_rng(17)
    closes = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {"Open": closes, "High": closes + 1, "Low": closes - 1, "Close": closes, "Volume": [1000, 1100, 1200]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates]),
    )
    # Cuma (20) resmi tatil olduğundan 'now' Cuma veya sonrası olsa bile
    # beklenen son tamamlanmış seans hâlâ Perşembe (19) -- eksikliği gizlemez.
    now = datetime(2026, 3, 20, 19, 0, tzinfo=TZ)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        check_trading_day_continuity(df, "TEST", now=now)

    err = exc_info.value
    assert err.missing_dates == [date(2026, 3, 19)]
    assert err.reason_code == "MISSING_TRADING_SESSION"


# ---------------------------------------------------------------------------
# HATA 3D, madde 20: indikatör regresyonu -- amaç, phantom barların (27-29
# Mayıs 2026 imzası: Open=High=Low=Close=önceki kapanış, Volume=0) normalize
# edilmiş göstergelerin GİRDİSİNDE hiç bulunmadığını KANITLAMAK. Gerçek
# internetten çekilmiş kesin sayısal değerler KİLİTLENMİYOR — yalnızca
# RAW (phantom dahil) ile NORMALIZED (phantom hariç) arasında yapısal fark
# olduğu doğrulanıyor.
# ---------------------------------------------------------------------------


def _raw_and_normalized_close_series_with_may_2026_phantom() -> tuple[pd.Series, pd.Series]:
    real_sessions = expected_trading_sessions(date(2026, 4, 1), date(2026, 5, 26))
    rng = np.random.default_rng(21)
    real_closes = 100 + np.cumsum(rng.normal(0, 1, len(real_sessions)))
    real_df = pd.DataFrame(
        {
            "Open": real_closes - 0.2,
            "High": real_closes + 0.5,
            "Low": real_closes - 0.5,
            "Close": real_closes,
            "Volume": rng.integers(1000, 5000, len(real_sessions)),
        },
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in real_sessions]),
    )
    last_close = real_df["Close"].iloc[-1]
    phantom_df = pd.DataFrame(
        {"Open": [last_close] * 3, "High": [last_close] * 3, "Low": [last_close] * 3,
         "Close": [last_close] * 3, "Volume": [0, 0, 0]},
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in ("2026-05-27", "2026-05-28", "2026-05-29")]),
    )
    raw_df = pd.concat([real_df, phantom_df]).sort_index()
    normalized_df, _ = normalize_bist_daily_sessions(raw_df, symbol="TEST", provider="yahoo_finance")
    return raw_df["Close"], normalized_df["Close"]


def test_normalization_removes_phantom_rows_from_indicator_input():
    from app.engines.technical.indicators import ema, macd, momentum, rsi, roc

    raw_close, normalized_close = _raw_and_normalized_close_series_with_may_2026_phantom()

    # 1) Yapısal kanıt: normalized seri, RAW'dan tam olarak 3 (phantom) satır
    #    EKSİK -- göstergelerin GİRDİSİ (uzunluk) fiilen değişti.
    assert len(normalized_close) == len(raw_close) - 3
    for phantom_date in ("2026-05-27", "2026-05-28", "2026-05-29"):
        assert pd.Timestamp(phantom_date, tz=TZ) not in normalized_close.index
        assert pd.Timestamp(phantom_date, tz=TZ) in raw_close.index

    # 2) Phantom barlar sıfır volatilite/sıfır hacim eklediğinden -- ve son
    #    bar olarak "GÜNCEL" analiz tarihine denk geldiklerinden -- RAW'ın SON
    #    değeri (29.05, phantom) ile NORMALIZED'ın SON değeri (26.05, gerçek)
    #    EMA/MACD/Momentum/ROC için FARKLI olmalıdır (bu sayısal değer
    #    internetten DOĞRULANMIYOR, yalnızca RAW != NORMALIZED kanıtlanıyor).
    #    NOT — RSI kasıtlı olarak bu karşılaştırmaya DAHİL edilmiyor: Wilder
    #    RSI'da delta=0 olan barlar avg_gain/avg_loss'u AYNI ORANDA küçültür,
    #    bu yüzden ardışık "flat" (phantom) barlar matematiksel olarak RSI
    #    oranını DEĞİŞTİRMEZ -- bu bir hata değil, ispatlanmış bir invaryanttır.
    raw_macd_line, _, _ = macd(raw_close)
    norm_macd_line, _, _ = macd(normalized_close)
    raw_ema, norm_ema = ema(raw_close, 20).iloc[-1], ema(normalized_close, 20).iloc[-1]
    raw_momentum, norm_momentum = momentum(raw_close).iloc[-1], momentum(normalized_close).iloc[-1]
    raw_roc, norm_roc = roc(raw_close).iloc[-1], roc(normalized_close).iloc[-1]

    assert raw_macd_line.iloc[-1] != pytest.approx(norm_macd_line.iloc[-1])
    assert raw_ema != pytest.approx(norm_ema)
    assert raw_momentum != pytest.approx(norm_momentum)
    assert raw_roc != pytest.approx(norm_roc)

    # RSI invaryantının kendisi de doğrulanır (belgelenmiş, beklenen davranış):
    # raw'ın phantom sonrası son değeri, normalized'ın son (gerçek) değeriyle
    # aynı orana (bu nedenle aynı RSI'a) sahiptir.
    assert rsi(raw_close).iloc[-1] == pytest.approx(rsi(normalized_close).iloc[-1])

    # 3) Normalized son değer, phantom'un kendisi DEĞİL, son GERÇEK barın
    #    (26.05) Close'undan türer -- momentum/roc bunu doğrudan kanıtlar.
    last_real_close = normalized_close.iloc[-1]
    assert last_real_close == raw_close.loc[pd.Timestamp("2026-05-26", tz=TZ)]


# ---------------------------------------------------------------------------
# HATA 3E (26.08.2026, commit-öncesi düzeltme) — `SUPPORTED_BIST_CALENDAR_
# YEARS` artık AÇIK bir liste, veri tablolarından TÜRETİLMİYOR. Bu testler,
# veri tablolarının bu açık listeden SAPMADIĞINI (eksik/fazla yıl)
# deterministik olarak, min/max KISAYOLU KULLANMADAN (her yıl/tarih tek tek)
# kilitler.
# ---------------------------------------------------------------------------


def test_every_supported_year_has_a_planned_calendar_entry():
    # Desteklenen HER yıl için BIST_FULL_DAY_CLOSURES'ta bir entry (key)
    # bulunmalı -- yani planlı takvim konfigürasyonu o yıl için GİRİLMİŞ
    # olmalı. Ancak "yıl destekleniyor" iddiası, "o yıl en az bir tam-gün
    # kapanışı VARDIR" anlamına gelmez -- SUPPORTED_BIST_CALENDAR_YEARS
    # tek otoritedir, dolu/boş olma durumu bu otoriteyi etkilemez.
    for year in sorted(SUPPORTED_BIST_CALENDAR_YEARS):
        assert year in BIST_FULL_DAY_CLOSURES, f"{year} desteklenen bir yıl ama BIST_FULL_DAY_CLOSURES'ta YOK"


def test_full_day_closures_do_not_contain_years_outside_supported_set():
    for year in BIST_FULL_DAY_CLOSURES:
        assert year in SUPPORTED_BIST_CALENDAR_YEARS, f"{year}, BIST_FULL_DAY_CLOSURES'ta ama desteklenen listede YOK"


def test_half_day_extraordinary_cancelled_years_are_all_within_supported_set():
    # Her yarım gün/olağanüstü kapanış/iptal edilmiş seans tarihinin YILI
    # desteklenen küme İÇİNDE olmalı -- tek tek, min/max karşılaştırması
    # YAPMADAN (ör. {2021,2022,2024} gibi non-contiguous bir küme olsaydı
    # min/max kontrolü 2023'ü yanlışlıkla "aralıkta" sayardı).
    for table in (BIST_HALF_DAY_SESSIONS, BIST_EXTRAORDINARY_CLOSURES, BIST_CANCELLED_SESSIONS):
        for year, dates in table.items():
            assert year in SUPPORTED_BIST_CALENDAR_YEARS, f"{year} desteklenmiyor ama {table} içinde tarih var"
            for d in dates:
                assert d.year == year, f"{d} tarihi {table}'nin {year} anahtarı altında ama d.year uyuşmuyor"
                assert d.year in SUPPORTED_BIST_CALENDAR_YEARS


def test_is_year_supported_matches_explicit_set_not_data_tables():
    # 2027 -- desteklenmeyen, veri tablolarında da hiç yer almayan bir yıl.
    assert not is_year_supported(2027)
    assert 2027 not in BIST_FULL_DAY_CLOSURES
    for year in SUPPORTED_BIST_CALENDAR_YEARS:
        assert is_year_supported(year)


# ---------------------------------------------------------------------------
# `first_expected_session_on_or_after` — HATA 5A FINAL PRE-COMMIT CLEANUP
# (27.08.2026): arbitrary/magic 14-günlük arama ufku KALDIRILDI, `search_end`
# artık çağırandan gelir. Weekend/holiday davranışı ve deterministic `None`
# (arama aralığında hiç expected session yoksa) burada ayrıca kilitlenir.
# ---------------------------------------------------------------------------


def test_first_expected_session_on_or_after_returns_day_itself_when_already_a_session():
    ordinary_day = date(2026, 8, 18)  # Salı -- expected session
    assert first_expected_session_on_or_after(ordinary_day, date(2026, 8, 31)) == ordinary_day


def test_first_expected_session_on_or_after_rolls_forward_past_weekend():
    saturday = date(2026, 8, 22)
    expected_next_session = date(2026, 8, 24)  # Pazartesi
    assert first_expected_session_on_or_after(saturday, date(2026, 8, 31)) == expected_next_session


def test_first_expected_session_on_or_after_rolls_forward_past_planned_holiday():
    # 2026-05-01 (1 Mayıs) -- tam gün resmi tatil, ondan SONRAKİ ilk expected
    # session'a taşınmalı.
    holiday = date(2026, 5, 1)
    assert is_full_day_closure(holiday) is True
    result = first_expected_session_on_or_after(holiday, date(2026, 5, 10))
    assert result is not None
    assert result > holiday
    assert is_full_day_closure(result) is False


def test_first_expected_session_on_or_after_returns_none_when_range_has_no_session():
    # `day > search_end` -- arama aralığı BOŞ, hiçbir expected session
    # OLAMAZ. Bu, arama ufkunun artık ARBITRARY bir sabitle değil, çağıranın
    # kendi (authoritative-doğrulanmış) üst sınırıyla sınırlı olduğunun
    # deterministic kanıtı -- tahmin YÜRÜTÜLMEZ, sessizce `None` döner.
    assert first_expected_session_on_or_after(date(2026, 8, 20), date(2026, 8, 19)) is None
