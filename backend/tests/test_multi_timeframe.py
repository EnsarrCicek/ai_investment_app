from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.engines.technical.multi_timeframe import check_alignment, resample_to_weekly_close, timeframe_direction

TZ = ZoneInfo("Europe/Istanbul")


def test_timeframe_direction_up_for_rising_series():
    close = pd.Series([100.0 + i for i in range(40)])
    assert timeframe_direction(close, window=10, slope_lookback=5) == "UP"


def test_timeframe_direction_down_for_falling_series():
    close = pd.Series([200.0 - i for i in range(40)])
    assert timeframe_direction(close, window=10, slope_lookback=5) == "DOWN"


def test_timeframe_direction_flat_for_constant_series():
    close = pd.Series([100.0] * 40)
    assert timeframe_direction(close, window=10, slope_lookback=5) == "FLAT"


def test_timeframe_direction_unknown_for_insufficient_history():
    close = pd.Series([100.0, 101.0])
    assert timeframe_direction(close, window=20, slope_lookback=5) == "UNKNOWN"


def test_check_alignment_true_when_all_timeframes_agree():
    result = check_alignment({"1d": "UP", "1wk": "UP"})
    assert result["aligned"] is True
    assert result["consensus"] == "UP"


def test_check_alignment_true_when_all_timeframes_agree_down():
    result = check_alignment({"1d": "DOWN", "1wk": "DOWN"})
    assert result["aligned"] is True
    assert result["consensus"] == "DOWN"


def test_check_alignment_conflicting_when_directions_oppose():
    result = check_alignment({"1d": "UP", "1wk": "DOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "CONFLICTING"


def test_check_alignment_mixed_for_partial_agreement():
    result = check_alignment({"1d": "UP", "1wk": "FLAT"})
    assert result["aligned"] is False
    assert result["consensus"] == "MIXED"


def test_check_alignment_unknown_when_no_timeframe_resolved():
    result = check_alignment({"1d": "UNKNOWN", "1wk": "UNKNOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


# HATA 7C-FIX (01.09.2026): eski sürüm, UNKNOWN olan zaman dilimini SESSİZCE
# eleyip kalan TEK bilinen zaman dilimini "uyumlu" sayıyordu (ör. burada
# {"1d":"UP","1wk":"UNKNOWN"} -> aligned=True, consensus="UP" dönüyordu) --
# bu, dokümantasyonun ("günlük VE haftalık yönü karşılaştırılır") iddia
# ettiği İKİ-taraflı karşılaştırmayı ihlal ediyordu (bkz. HATA 7C denetimi).
# Artık configured zaman dilimlerinden HERHANGİ BİRİ UNKNOWN ise MTF kanıtı
# EKSİK sayılır -- aligned/consensus İDDİA EDİLMEZ (UNKNOWN'a forward-fill
# YOK, DOWN/FLAT'e çevrilmiyor).
def test_check_alignment_incomplete_when_one_known_one_unknown_up():
    result = check_alignment({"1d": "UP", "1wk": "UNKNOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


def test_check_alignment_incomplete_when_one_known_one_unknown_down():
    result = check_alignment({"1d": "DOWN", "1wk": "UNKNOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


def test_check_alignment_incomplete_when_unknown_then_known_up():
    result = check_alignment({"1d": "UNKNOWN", "1wk": "UP"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


def test_check_alignment_incomplete_when_unknown_then_known_down():
    result = check_alignment({"1d": "UNKNOWN", "1wk": "DOWN"})
    assert result["aligned"] is False
    assert result["consensus"] == "UNKNOWN"


def test_resample_to_weekly_close_reduces_to_weekly_last_values():
    idx = pd.date_range("2024-01-01", periods=14, freq="D")  # Pzt 2024-01-01 .. Paz 2024-01-14 (2 tam hafta)
    daily_close = pd.Series(range(1, 15), index=idx, dtype=float)  # 1..14

    # 'now' iki haftanın da kesin tamamlandığından emin olmak için üçüncü haftaya ayarlandı
    # (HATA 2A: son hafta, 'now' onun haftasıyla çakışıyorsa devam ediyor sayılıp düşürülürdü).
    now = datetime(2024, 1, 20, 12, 0)  # ertesi haftanın Cumartesi'si
    weekly = resample_to_weekly_close(daily_close, now=now)

    assert len(weekly) == 2
    assert weekly.iloc[0] == 7.0  # ilk haftanın son günü (2024-01-07, Pazar) -> 7
    assert weekly.iloc[-1] == 14.0  # ikinci haftanın son günü (2024-01-14, Pazar) -> 14


def test_weekly_resample_direction_matches_underlying_trend_without_extra_fetch():
    # AŞAMA 48/18: haftalık yön, ek bir yfinance isteği olmadan günlük
    # seriden türetilebiliyor mu — asıl doğrulanan budur.
    idx = pd.date_range("2023-01-02", periods=140, freq="D")
    daily_close = pd.Series([100.0 + 0.5 * i for i in range(140)], index=idx)

    now = datetime(2023, 6, 1, 12, 0)  # serinin bittiği tarihten haftalarca sonrası
    weekly = resample_to_weekly_close(daily_close, now=now)

    assert timeframe_direction(weekly, window=10, slope_lookback=4) == "UP"


# ---------------------------------------------------------------------------
# HATA 2A (25.08.2026): devam eden (henüz Cuma'sı gelmemiş) hafta, MTF
# confirmation'a girmemeli — bkz. TEKNIK_ANALIZ_METODOLOJISI.md ve
# services/market_data/completed_bars.py.
# ---------------------------------------------------------------------------


def _daily_close(dates: list[str]) -> pd.Series:
    index = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in dates])
    return pd.Series(range(100, 100 + len(dates)), index=index, dtype=float)


def test_wednesday_ongoing_week_is_excluded_from_weekly_confirmation():
    # Carsamba (26 Agustos 2026) itibariyla son tamamlanmis gunluk bar Sali
    # (25) -- bu haftanin Cuma'si henuz gelmedi, bu yuzden bu haftanin
    # "haftalik kapanisi" MTF confirmation'a girmemeli.
    dates = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25"]
    close = _daily_close(dates)  # son gun: 2026-08-25 (Sali), devam eden hafta
    now = datetime(2026, 8, 26, 13, 0, tzinfo=TZ)  # Carsamba

    weekly = resample_to_weekly_close(close, now=now)

    # Devam eden haftanin (17-21 Agustos haftasindan SONRAKI hafta) bucket'i dusurulmus olmali.
    last_completed_week_label = pd.Timestamp("2026-08-23", tz=TZ)  # 17-21 Agustos haftasinin W-SUN etiketi
    assert weekly.index[-1] == last_completed_week_label


def test_friday_after_close_includes_that_weeks_bar():
    # Son tamamlanmis gunluk bar Cuma (28 Agustos) ise, o haftanin kendisi
    # BIST icin zaten bitmistir -- devre disi birakilmamali.
    dates = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
    close = _daily_close(dates)  # son gun Cuma
    now = datetime(2026, 8, 28, 19, 0, tzinfo=TZ)  # ayni Cuma, kapanistan sonra

    weekly = resample_to_weekly_close(close, now=now)

    assert weekly.iloc[-1] == pytest.approx(close.iloc[-1])


def test_weekend_after_friday_close_still_includes_that_weeks_bar():
    dates = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
    close = _daily_close(dates)
    now = datetime(2026, 8, 30, 11, 0, tzinfo=TZ)  # Pazar

    weekly = resample_to_weekly_close(close, now=now)

    assert weekly.iloc[-1] == pytest.approx(close.iloc[-1])


def test_different_iso_week_than_now_is_always_complete():
    # Son bar gecen haftadan (tatil nedeniyle Persembe'de bitmis olsa bile)
    # ve 'now' zaten sonraki haftadaysa, o hafta kesin tamamlanmis sayilir.
    dates = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"]  # son gun Persembe (20)
    close = _daily_close(dates)
    now = datetime(2026, 8, 24, 10, 0, tzinfo=TZ)  # sonraki hafta Pazartesi

    weekly = resample_to_weekly_close(close, now=now)

    assert weekly.iloc[-1] == pytest.approx(close.iloc[-1])
