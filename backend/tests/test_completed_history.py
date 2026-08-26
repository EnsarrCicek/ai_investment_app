from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.completed_history import prepare_backtest_history
from app.engines.technical.data_quality import DataQualityError

TZ = ZoneInfo("Europe/Istanbul")


class _FakeProvider:
    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df

    def get_history(self, symbol: str, period: str = "6mo", **_kwargs):
        return self._history_df


def _bday_df(start: str | None = None, end: str | None = None, periods: int | None = None, seed: int = 1) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, end=end, periods=periods, freq="B")
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


def test_backtest_data_as_of_reflects_actual_provider_gap_not_the_upper_bound():
    # HATA 3B/3C sinir cizgisi: latest_expected_completed_date(now) yalnizca
    # UST SINIRDIR ("bu tarihe kadar veri kabul ederiz"), provider'da o
    # tarihe kadar HER GUNUN GERCEKTEN var oldugu GARANTISI DEGILDIR.
    # Burada 25.08.2026 provider'da HIC YOK (bkz. HATA 3B raporu, gercek
    # canli gozlem) -- backtest_data_as_of bu durumda ust sinirdan (25.08)
    # DAHA ESKI (24.08) olmali. Bu, 25.08 eksikligini HARD_VETO YAPMAMALI --
    # trading-day continuity kontrolu HATA 3C kapsamindadir, burada
    # dogrulanan yalnizca metadata'nin GERCEK kullanilan tarihi tasidigidir.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)  # ust sinir: latest_expected_completed_date == 2026-08-25
    completed_through_24 = _bday_df(end="2026-08-24", periods=120)  # 25.08 hic YOK
    raw = _append_partial_row(completed_through_24, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    df, backtest_data_as_of = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert backtest_data_as_of == pd.Timestamp("2026-08-24").date()  # ust sinirdan (25.08) DAHA ESKI
    assert df.index[-1].date() == pd.Timestamp("2026-08-24").date()  # 26.08 partial cikarildi, 25.08 zaten yoktu


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
