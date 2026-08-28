from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.data_quality import (
    DataQualityError,
    InvalidOHLCVError,
    TradingCalendarUnsupportedError,
    TradingDayContinuityError,
    check_data_quality,
    check_raw_ohlcv_integrity,
    check_trading_day_continuity,
    previous_expected_sessions,
)
from app.services.market_data.trading_calendar import expected_trading_sessions

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


# ---------------------------------------------------------------------------
# HATA 5A REQUIRED TEST TRACE MATRIX, madde A/B: `previous_expected_sessions()`
# -- mandatory indicator warm-up'ın alt sınırının EXACT 60 expected session
# olduğu ve off-by-one'ın (simulation_start'ın KENDİSİ 60'a DAHİL DEĞİL)
# doğrudan, izole bir birim testle kilitlenmesi.
# ---------------------------------------------------------------------------


def test_previous_expected_sessions_returns_exactly_n_sessions_in_order():
    before = date(2026, 8, 26)
    result = previous_expected_sessions(before, 60)
    assert len(result) == 60
    assert result == sorted(result)  # kronolojik sıra
    # doğrudan authoritative takvimle çapraz doğrulama: `before`'dan önceki
    # tam 60 expected session'ın KENDİSİ.
    all_sessions = expected_trading_sessions(date(2026, 1, 1), before - timedelta(days=1))
    assert result == all_sessions[-60:]


def test_previous_expected_sessions_excludes_the_before_date_itself_off_by_one():
    # `before` (simulation_start) authoritative takvimde expected bir session
    # OLSA BİLE (2026-08-26 bir Çarşamba, expected), dönen 60'ın İÇİNE ASLA
    # girmemeli -- yalnızca ONDAN ÖNCEki seanslar sayılır.
    before = date(2026, 8, 26)
    assert before in expected_trading_sessions(date(2026, 8, 24), before)  # önkoşul: before expected bir session
    result = previous_expected_sessions(before, 60)
    assert before not in result
    assert result[-1] < before


def test_previous_expected_sessions_raises_for_unsupported_year_without_clipping():
    # Mandatory warm-up, evidence pre-roll'un aksine CLIP YAPILMAZ -- 60
    # session'a ulaşmadan desteklenmeyen bir yıla (2020) çarpılırsa
    # deterministic TradingCalendarUnsupportedError.
    before = date(2021, 1, 15)  # 2021'in başı -- geriye 60 session gitmek 2020'ye taşar
    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        previous_expected_sessions(before, 60)
    assert exc_info.value.year == 2020


# ---------------------------------------------------------------------------
# HATA 5B1 (27.08.2026) — LAYER 1: `check_raw_ohlcv_integrity()`. Mandatory
# skorlanan pencere içindeki (yalnızca son bar DEĞİL) NaN/±inf/geçersiz
# fiyat/negatif hacim/imkânsız OHLC ilişkisi HARD VETO edilmeli.
# ---------------------------------------------------------------------------


def test_check_raw_ohlcv_integrity_passes_for_clean_history():
    check_raw_ohlcv_integrity(_fresh_df(rows=30), "TEST")  # exception atmamalı


def test_check_raw_ohlcv_integrity_empty_dataframe_is_noop():
    df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    check_raw_ohlcv_integrity(df, "TEST")  # exception atmamalı


def test_internal_nan_close_is_hard_vetoed_not_just_last_row():
    # HATA 5B1 madde 16: yalnızca SON bar DEĞİL, pencerenin ORTASINDAKİ bir
    # NaN da yakalanmalı -- `check_data_quality()`'nin dar (yalnızca son bar)
    # kapsamından FARKLI, daha geniş bir garanti.
    df = _fresh_df(rows=30)
    df.iloc[15, df.columns.get_loc("Close")] = np.nan
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.reason_code == "INVALID_OHLCV"
    assert exc_info.value.violations[0][0] == df.index[15].date()
    assert exc_info.value.violations[0][1] == "NaN"


def test_internal_nan_open_high_low_volume_each_hard_vetoed():
    for col in ("Open", "High", "Low", "Volume"):
        df = _fresh_df(rows=30)
        df.iloc[10, df.columns.get_loc(col)] = np.nan
        with pytest.raises(InvalidOHLCVError):
            check_raw_ohlcv_integrity(df, "TEST")


def test_internal_positive_infinity_is_hard_vetoed():
    df = _fresh_df(rows=30)
    df.iloc[12, df.columns.get_loc("High")] = float("inf")
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "INF"


def test_internal_negative_infinity_is_hard_vetoed():
    df = _fresh_df(rows=30)
    df.iloc[12, df.columns.get_loc("Low")] = float("-inf")
    with pytest.raises(InvalidOHLCVError):
        check_raw_ohlcv_integrity(df, "TEST")


def test_zero_close_is_hard_vetoed():
    df = _fresh_df(rows=30)
    df.iloc[5, df.columns.get_loc("Close")] = 0.0
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "NON_POSITIVE_PRICE"


def test_negative_open_is_hard_vetoed():
    df = _fresh_df(rows=30)
    df.iloc[5, df.columns.get_loc("Open")] = -1.0
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "NON_POSITIVE_PRICE"


def test_negative_volume_is_hard_vetoed():
    df = _fresh_df(rows=30)
    df.iloc[5, df.columns.get_loc("Volume")] = -100
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "NEGATIVE_VOLUME"


def test_zero_volume_is_not_invalid():
    # HATA 5B1 madde 7 — kesin scope sınırı: sıfır hacim OTOMATİK invalid
    # SAYILMAZ (yalnızca negatif hacim hard-veto'dur). Ayrı bir semantik konu.
    df = _fresh_df(rows=30)
    df.iloc[5, df.columns.get_loc("Volume")] = 0
    check_raw_ohlcv_integrity(df, "TEST")  # exception atmamalı


@pytest.mark.parametrize("bad_column, delta", [("High", -1), ("Low", 100)])
def test_high_below_low_and_low_above_high_are_hard_vetoed(bad_column, delta):
    # High < Low (delta=-1 satırın Low'unun ALTINA) ve Low > High (delta=+100
    # satırın High'ının ÜSTÜNE) — ikisi de aynı temel imkansızlığın (High/Low
    # sırasının bozulması) iki yönü.
    df = _fresh_df(rows=30)
    row_loc = df.index[7]
    if bad_column == "High":
        df.loc[row_loc, "High"] = df.loc[row_loc, "Low"] + delta
    else:
        df.loc[row_loc, "Low"] = df.loc[row_loc, "High"] + delta
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "IMPOSSIBLE_OHLC_RELATIONSHIP"


def test_high_below_open_is_hard_vetoed():
    df = _fresh_df(rows=30)
    row_loc = df.index[7]
    df.loc[row_loc, "High"] = df.loc[row_loc, "Open"] - 5
    df.loc[row_loc, "Low"] = df.loc[row_loc, "Open"] - 10  # Low<High korunsun, yalnız High<Open ihlali test edilsin
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "IMPOSSIBLE_OHLC_RELATIONSHIP"


def test_low_above_close_is_hard_vetoed():
    df = _fresh_df(rows=30)
    row_loc = df.index[7]
    df.loc[row_loc, "Low"] = df.loc[row_loc, "Close"] + 5
    df.loc[row_loc, "High"] = df.loc[row_loc, "Close"] + 10  # High>Low korunsun, yalnız Low>Close ihlali test edilsin
    with pytest.raises(InvalidOHLCVError) as exc_info:
        check_raw_ohlcv_integrity(df, "TEST")
    assert exc_info.value.violations[0][1] == "IMPOSSIBLE_OHLC_RELATIONSHIP"


def test_evidence_only_malformed_row_outside_mandatory_window_does_not_veto():
    # HATA 5A evidence-contract regresyon kilidi: bu fonksiyona yalnızca
    # ÇAĞIRAN tarafın verdiği mandatory pencere gider -- bozuk bir satır
    # mandatory pencerenin DIŞINDA (ör. evidence-only pre-roll'da) kalırsa
    # bu fonksiyon onu HİÇ GÖRMEZ. Bu test, entegrasyon noktalarının (bkz.
    # completed_history.py/technical/engine.py) yalnızca kırpılmış mandatory
    # pencereyi geçirdiğini simüle eder: bozuk satırı İÇERMEYEN bir df
    # sorunsuz geçer.
    mandatory_window = _fresh_df(rows=30)  # evidence pre-roll HİÇ dahil değil
    check_raw_ohlcv_integrity(mandatory_window, "TEST")  # exception atmamalı
