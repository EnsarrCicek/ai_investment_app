from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.engines.technical.multi_timeframe import (
    WEEKLY_DIRECTION_MIN_OBSERVATIONS,
    check_alignment,
    resample_to_weekly_close,
    timeframe_direction,
)

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


# ---------------------------------------------------------------------------
# HATA 10D (03.09.2026): `min_observations` -- haftalık MTF için açık, formül-
# türevli bir uygunluk sözleşmesi (bkz. modülün `WEEKLY_DIRECTION_MIN_
# OBSERVATIONS` yorumu). `None` (varsayılan) iken davranış HİÇ DEĞİŞMEDEN
# kalır -- yalnızca haftalık çağrı (`engine.py`) bu parametreyi verir.
# ---------------------------------------------------------------------------


def test_timeframe_direction_default_min_observations_none_preserves_existing_behavior():
    # 6 gözlem (slope_lookback+1) -- eskiden de, şimdi de (min_observations
    # verilmediğinde) MATEMATİKSEL olarak hesaplanabilir olmalı, UNKNOWN DEĞİL.
    close = pd.Series([100.0 + i for i in range(6)])
    assert timeframe_direction(close, window=10, slope_lookback=5) == "UP"


def test_timeframe_direction_min_observations_unknown_below_threshold():
    close = pd.Series([100.0 + i for i in range(24)])  # 24 < 25
    assert timeframe_direction(close, min_observations=25) == "UNKNOWN"


def test_timeframe_direction_min_observations_up_at_threshold():
    close = pd.Series([100.0 + i for i in range(25)])  # tam 25
    assert timeframe_direction(close, min_observations=25) == "UP"


def test_timeframe_direction_min_observations_down_at_threshold():
    close = pd.Series([200.0 - i for i in range(25)])
    assert timeframe_direction(close, min_observations=25) == "DOWN"


def test_timeframe_direction_min_observations_flat_at_threshold():
    # ±0.5 deadband HİÇ DEĞİŞMEDİ -- sabit seri hâlâ FLAT döner.
    close = pd.Series([100.0] * 25)
    assert timeframe_direction(close, min_observations=25) == "FLAT"


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


def _weekly_close_series(n_weeks: int) -> tuple[pd.Series, datetime]:
    # 2024-01-01 bir Pazartesi -- `n_weeks*5` iş günü, `now` son (Cuma) günün
    # kendisi olacak şekilde, TAM `n_weeks` tamamlanmış hafta üretir (devam
    # eden hafta belirsizliği YOK, bkz. yukarıdaki Cuma-sonrası testleri).
    idx = pd.bdate_range("2024-01-01", periods=n_weeks * 5, tz=TZ)
    close = pd.Series([100.0 + 0.5 * i for i in range(len(idx))], index=idx)
    return close, idx[-1].to_pydatetime()


def test_weekly_direction_unknown_with_24_completed_weeks_via_min_observations_gate():
    # HATA 10D: 24 TAMAMLANMIŞ hafta (partial/devam eden hafta HİÇ karışmıyor,
    # `resample_to_weekly_close` zaten yalnızca tamamlanmışları döner) --
    # WEEKLY_DIRECTION_MIN_OBSERVATIONS(25)'in ALTINDA, UNKNOWN dönmeli.
    close, now = _weekly_close_series(24)
    weekly = resample_to_weekly_close(close, now=now)
    assert len(weekly) == 24
    assert timeframe_direction(weekly, min_observations=WEEKLY_DIRECTION_MIN_OBSERVATIONS) == "UNKNOWN"
    # Eski (gate'siz) çağrı hâlâ MATEMATİKSEL olarak hesaplanabilir olduğunu
    # kanıtlıyor -- bu, "hesaplanabilir" ile "olgun" farkının ta kendisi.
    assert timeframe_direction(weekly) == "UP"


def test_weekly_direction_computed_normally_with_25_completed_weeks_via_min_observations_gate():
    # Tam eşikte (25) -- normal EMA-eğimi formülüne göre hesaplanmalı, UNKNOWN DEĞİL.
    close, now = _weekly_close_series(25)
    weekly = resample_to_weekly_close(close, now=now)
    assert len(weekly) == 25
    assert timeframe_direction(weekly, min_observations=WEEKLY_DIRECTION_MIN_OBSERVATIONS) == "UP"


def test_partial_25th_week_does_not_count_toward_min_observations_gate():
    # HATA 10D FINAL PRE-COMMIT HARDENING: 24 TAMAMLANMIŞ hafta + 25. haftanın
    # DEVAM EDEN (Pazartesi-Çarşamba) kısmı -- `_is_last_week_complete()`
    # HİÇ DEĞİŞMEDİ, devam eden hafta zaten düşürülür; bu test yalnızca bunun
    # min_observations(25) sözleşmesiyle DOĞRU birleştiğini kilitler: partial
    # hafta sayılmamalı (24 tamamlanmış hafta, UNKNOWN). Aynı seri, 25. hafta
    # TAMAMLANDIĞINDA (Cuma) normal şekilde hesaplanmalı.
    idx_partial = pd.bdate_range("2024-01-01", periods=123, tz=TZ)  # 24 tam hafta + Pzt-Çrş (25. hafta, devam ediyor)
    close_partial = pd.Series([100.0 + 0.5 * i for i in range(len(idx_partial))], index=idx_partial)
    now_partial = idx_partial[-1].to_pydatetime()  # aynı (devam eden) haftanın Çarşamba'sı

    weekly_partial = resample_to_weekly_close(close_partial, now=now_partial)
    assert len(weekly_partial) == 24
    assert timeframe_direction(weekly_partial, min_observations=WEEKLY_DIRECTION_MIN_OBSERVATIONS) == "UNKNOWN"

    idx_full = pd.bdate_range("2024-01-01", periods=125, tz=TZ)  # AYNI seri, 25. hafta TAMAMLANDI (Cuma)
    close_full = pd.Series([100.0 + 0.5 * i for i in range(len(idx_full))], index=idx_full)
    now_full = idx_full[-1].to_pydatetime()

    weekly_full = resample_to_weekly_close(close_full, now=now_full)
    assert len(weekly_full) == 25
    assert timeframe_direction(weekly_full, min_observations=WEEKLY_DIRECTION_MIN_OBSERVATIONS) != "UNKNOWN"


def test_different_iso_week_than_now_is_always_complete():
    # Son bar gecen haftadan (tatil nedeniyle Persembe'de bitmis olsa bile)
    # ve 'now' zaten sonraki haftadaysa, o hafta kesin tamamlanmis sayilir.
    dates = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"]  # son gun Persembe (20)
    close = _daily_close(dates)
    now = datetime(2026, 8, 24, 10, 0, tzinfo=TZ)  # sonraki hafta Pazartesi

    weekly = resample_to_weekly_close(close, now=now)

    assert weekly.iloc[-1] == pytest.approx(close.iloc[-1])
