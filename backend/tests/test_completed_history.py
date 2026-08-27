from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.engines.backtest.completed_history import SUPPORTED_BACKTEST_PERIODS, prepare_backtest_history
from app.engines.technical.data_quality import (
    DataQualityError,
    TradingCalendarUnsupportedError,
    TradingDayContinuityError,
)
from app.services.market_data.trading_calendar import NonSessionClassification, expected_trading_sessions

TZ = ZoneInfo("Europe/Istanbul")


class _FakeProvider:
    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df

    def get_history(self, symbol: str, period: str = "6mo", **_kwargs):
        return self._history_df


class _CapturingProvider:
    """HATA 3E: `prepare_backtest_history()`'nin provider'a GERÇEKTEN neyi
    (`period=` DEĞİL, explicit `start`/`end`) istediğini doğrudan gözlemler."""

    def __init__(self, history_df: pd.DataFrame):
        self._history_df = history_df
        self.calls: list[dict] = []

    def get_history(self, symbol: str, **kwargs):
        self.calls.append(kwargs)
        return self._history_df


class _AssertNotCalledProvider:
    def get_history(self, symbol: str, **_kwargs):
        raise AssertionError("get_history çağrılmamalıydı — bu adımdan ÖNCE fail-fast/validasyon durmalıydı")


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
#
# NOT (HATA 3E, 26.08.2026): Bu fixture'ların TAMAMI, `period`'un çağırdığı
# `target_start`'tan ÇOK DAHA KISA bir aralık kapsıyor (ör. 2026-01-05'ten
# başlıyor, "1y" target_start'ı 2025-08-2x'tir) — bu yüzden HEPSİ
# `LEADING_EDGE_UNVERIFIED` yoluna düşer (`expected_start = ilk gözlemlenen
# bar`), tıpkı HATA 3E ÖNCESİ `expected_start=None` varsayılan davranışı
# gibi — bu testlerin sayısal/continuity sonuçları HİÇ DEĞİŞMEDİ, yalnızca
# dönüş tipi (3-tuple → `PreparedBacktestHistory`) değişti.
# ---------------------------------------------------------------------------


def test_pre_cutoff_excludes_partial_today_row():
    # now: piyasa acik, saat 10:44 -- bugunku (26.08) satir HENUZ tamamlanmamis.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-25")  # ...24,25 Agustos completed
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    prepared = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-25").date()
    assert prepared.history.index[-1].date() == pd.Timestamp("2026-08-25").date()
    assert len(prepared.history) == len(completed)  # partial satir hic girmedi


def test_post_cutoff_includes_todays_now_completed_row():
    # now: kapanis (18:00) + finalization payi (30dk) GECTI -- bugunku satir artik tamamlanmis kabul edilir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    prepared = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", min_history_days=60, now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-26").date()
    assert prepared.history.index[-1].date() == pd.Timestamp("2026-08-26").date()
    assert len(prepared.history) == len(raw)  # artik hicbir satir cikarilmadi


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

    prepared_a = prepare_backtest_history(_FakeProvider(raw_a), "TEST", "1y", min_history_days=60, now=now)
    prepared_b = prepare_backtest_history(_FakeProvider(raw_b), "TEST", "1y", min_history_days=60, now=now)

    assert prepared_a.backtest_data_as_of == prepared_b.backtest_data_as_of
    pd.testing.assert_frame_equal(prepared_a.history, prepared_b.history)


def test_weekend_now_does_not_alter_friday_completed_history():
    # Cumartesi (2026-08-29) frozen now -- Cuma (2026-08-28) zaten tamamlanmis,
    # hafta sonu icin hicbir satir yok -- hicbir sey degismemeli.
    now = datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
    completed = _bday_df("2026-01-05", "2026-08-28")

    prepared = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", min_history_days=60, now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-28").date()
    assert len(prepared.history) == len(completed)


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

    prepared = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", min_history_days=60, now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2025-12-31").date()
    assert len(prepared.history) == len(completed)


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
# HATA 3C, madde 1 / HATA 3E, madde 1: authoritative backtest period sözleşmesi.
# `SUPPORTED_BACKTEST_PERIODS` artık `BACKTEST_PERIOD_DELTAS`'tan türer (tek
# source-of-truth) — iki koleksiyonun birbirinden sapması yapısal olarak
# imkansız, bu yüzden ayrı bir "set eşitliği" testi GEREKMEZ.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", sorted(SUPPORTED_BACKTEST_PERIODS))
def test_supported_period_passes_validation_and_uses_explicit_window(period):
    # HATA 3E: kısa (120 günlük) bir fixture, HER period için LEADING_EDGE_
    # UNVERIFIED yoluna düşer (target_start çok daha eskiye gidiyor) — bu,
    # tam da yeni-listing-güvenli davranışın kanıtı: 5y istenip yalnızca
    # ~6 aylık gerçek veri olsa bile otomatik HARD_VETO ÜRETİLMEZ.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df(end="2026-08-26", periods=120)
    provider = _CapturingProvider(df)

    prepared = prepare_backtest_history(provider, "TEST", period, min_history_days=60, now=now)

    assert prepared.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert len(provider.calls) == 1
    assert "period" not in provider.calls[0]  # Yahoo'ya artık period= GÖNDERİLMİYOR
    assert "start" in provider.calls[0] and "end" in provider.calls[0]


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random", ""])
def test_unsupported_period_is_rejected_before_fetching_provider_history(period):
    # Period validasyonu provider.get_history()'DEN ÖNCE çalışır -- ağa hiç
    # gidilmez (bkz. _AssertNotCalledProvider).
    with pytest.raises(ValueError):
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", period, min_history_days=60)


# ---------------------------------------------------------------------------
# HATA 3C-EX (26.08.2026): 08.02.2023 cancelled-session normalizasyonu.
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

    prepared = prepare_backtest_history(_FakeProvider(df), "THYAO", "1y", min_history_days=2, now=now)

    # 08.02 normalizasyon sonrası TAMAMEN gitti -- 07.02 -> 15.02 ardışık.
    assert list(prepared.history.index.date) == [date(2023, 2, 7), date(2023, 2, 15)]
    assert date(2023, 2, 8) not in prepared.history.index.date
    assert prepared.backtest_data_as_of == date(2023, 2, 15)
    dropped_dates = {d.date: d.classification for d in prepared.normalization.dropped_sessions}
    assert dropped_dates.get(date(2023, 2, 8)) == NonSessionClassification.CANCELLED_SESSION.value
    # 09-14.02 (olağanüstü kapanış) veya 08.02'nin kendisi "missing"/"unexpected"
    # olarak HARD_VETO tetiklemiyor -- ikisi de authoritative takvimde
    # "expected" DEĞİL (bkz. BIST_EXTRAORDINARY_CLOSURES/BIST_CANCELLED_SESSIONS).


def test_unexpected_bar_on_planned_holiday_is_authoritatively_dropped_not_vetoed():
    # HATA 3D (26.08.2026): 1 Mayıs resmi tam gün tatildir -- provider (Yahoo)
    # bu tarihte "phantom" bir bar döndürürse (bkz. HATA 3D denetimi, 27-29
    # Mayıs 2026 gerçek örneği), bu artık HARD VETO edilmez; authoritative
    # takvime göre PLANNED_FULL_DAY_CLOSURE olarak şeffaf biçimde düşürülür ve
    # backtest normal şekilde devam eder (bkz. normalize_bist_daily_sessions).
    # Bu davranış, kararın OHLC/Volume desenine DEĞİL yalnızca takvime dayandığını
    # kilitler -- bogus_holiday_row'un OHLC/Volume değerleri bilinçli olarak
    # "phantom imzasından" (Open=High=Low=Close=önceki kapanış, Volume=0) FARKLI.
    now = datetime(2026, 5, 8, 19, 0, tzinfo=TZ)
    valid_before = _bday_df("2026-04-01", "2026-04-30")
    bogus_holiday_row = pd.DataFrame(
        {"Open": [50.0], "High": [51.0], "Low": [49.0], "Close": [50.0], "Volume": [100]},
        index=[pd.Timestamp("2026-05-01", tz=TZ)],  # 1 Mayıs -- resmi tatil, gerçekte hiç bar olmamalı
    )
    valid_after = _bday_df("2026-05-04", "2026-05-08")
    df = pd.concat([valid_before, bogus_holiday_row, valid_after]).sort_index()

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=10, now=now)

    assert date(2026, 5, 1) not in [ts.date() for ts in prepared.history.index]
    assert len(prepared.normalization.dropped_sessions) == 1
    dropped = prepared.normalization.dropped_sessions[0]
    assert dropped.date == date(2026, 5, 1)
    assert dropped.classification == NonSessionClassification.PLANNED_FULL_DAY_CLOSURE.value


def test_unexpected_bar_on_genuinely_unknown_weekday_is_still_hard_vetoed():
    # HATA 3D defense-in-depth (spec bölüm 12): normalization yalnızca
    # AUTHORITATIVE olarak bilinen 4 sınıfı (weekend/planlı/olağanüstü/iptal)
    # düşürür. Hafta içi, hiçbir sınıfa girmeyen (yani gerçekte var olmaması
    # gereken ama takvimde hiçbir gerekçesi bulunmayan) bir bar hâlâ
    # check_trading_day_continuity() tarafından HARD VETO edilmelidir --
    # normalization bu koruma katmanını ASLA zayıflatmaz.
    now = datetime(2026, 5, 8, 19, 0, tzinfo=TZ)
    valid_before = _bday_df("2026-04-01", "2026-04-24")
    # 2026-04-27 (Pazartesi) expected bir seans -- provider'da hiç YOK, bu
    # nedenle normalization sonrası bile "missing" olarak kalmalı.
    valid_after = _bday_df("2026-04-28", "2026-05-08")
    df = pd.concat([valid_before, valid_after]).sort_index()

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=10, now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert date(2026, 4, 27) in exc_info.value.missing_dates


# ---------------------------------------------------------------------------
# HATA 3E (26.08.2026) — BACKTEST LEADING-EDGE / EXPLICIT WINDOW.
#
# Window anchor: `target_end = latest_expected_completed_date(now)` (yeni
# tamamlanmış bir seans olduğunda pencerenin ilerlemesi BEKLENEN davranıştır,
# bir hata DEĞİLDİR); `target_start = target_end - BACKTEST_PERIOD_DELTAS
# [period]`. Provider'a artık `period=` DEĞİL, explicit `start`/`end`
# gönderilir. Pre-roll (`PRE_ROLL_DAYS`, live ile PAYLAŞILAN sabit) yalnızca
# `resolve_expected_start()`'a (HATA 2C ile AYNI fonksiyon) evidence
# sağlamak için kullanılır — hiçbir hesaplamaya (continuity/kalite/skor/
# warm-up) pre-roll barı SIZMAZ.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "now_str, expected_target_end, expected_1y_target_start",
    [
        ("2026-08-26 10:00", date(2026, 8, 25), date(2025, 8, 25)),  # cutoff (18:30) ÖNCESİ
        ("2026-08-26 18:45", date(2026, 8, 26), date(2025, 8, 26)),  # cutoff SONRASI
    ],
)
def test_window_anchor_uses_latest_completed_session_not_wall_clock_date(
    now_str, expected_target_end, expected_1y_target_start
):
    # Cutoff öncesinde window wall-clock "bugün"e bağlanmaz (target_end dünkü
    # son GERÇEKTEN tamamlanmış seanstır); cutoff sonrasında yeni bir completed
    # session mevcut olduğu için target_end'in bir gün ilerlemesi BEKLENEN,
    # istenen rolling-window davranışıdır -- bir non-determinism/bug DEĞİLDİR.
    now = datetime.strptime(now_str, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    df = _bday_df(end=expected_target_end.isoformat(), periods=120)

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", min_history_days=60, now=now)

    assert prepared.backtest_data_as_of == expected_target_end
    assert prepared.requested_window_start == expected_1y_target_start


def test_leading_gap_verified_pre_window_is_hard_vetoed():
    # HATA 3E ANA REGRESYONU: pre-roll'da GERÇEK kanıt var (VERIFIED_PRE_
    # WINDOW) -> expected_start=target_start -> pencerenin EN BAŞINDAKİ
    # (T0/T1) eksik seanslar artık MISSING_TRADING_SESSION ile HARD VETO
    # edilir. HATA 3E ÖNCESİ kod `expected_start` hiç geçirmediğinden
    # `df.index[0]`'ı (T2) alt sınır sayıp bunu PASS ederdi (final audit'te
    # sentetik kanıtlanan kör nokta) -- bu, o kör noktanın regresyon kilididir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26, target_start(6mo)=2026-02-26
    pre_roll_evidence = _bday_df("2025-09-01", "2026-02-25")  # target_start'tan ÖNCE gerçek kanıt
    # T0=2026-02-26, T1=2026-02-27 (pencerenin ilk iki beklenen seansı) provider'da YOK.
    after_gap = _bday_df("2026-03-02", "2026-08-26")
    df = pd.concat([pre_roll_evidence, after_gap]).sort_index()

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", min_history_days=60, now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert exc_info.value.missing_dates == [date(2026, 2, 26), date(2026, 2, 27)]


def test_leading_edge_unverified_tolerates_start_gap_but_still_vetoes_middle_gap():
    # Pre-roll'da HİÇ kanıt yok -- ilk gözlemlenen bar T2 (2026-03-02),
    # T0/T1 (2026-02-26/27) provider'da YOK ama bu artık HARD_VETO DEĞİL
    # (LEADING_EDGE_UNVERIFIED). Ama T2'den SONRAKİ gerçek bir middle-gap
    # hâlâ HARD_VETO'ya yol açmalı -- advisory leading-edge ile HATA 3C'nin
    # middle-gap korumasının AYRI kaldığının kanıtı.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26, target_start(6mo)=2026-02-26
    df = _bday_df("2026-03-02", "2026-08-26", exclude=["2026-05-05"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", min_history_days=60, now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert exc_info.value.missing_dates == [date(2026, 5, 5)]
    assert date(2026, 2, 26) not in exc_info.value.missing_dates
    assert date(2026, 2, 27) not in exc_info.value.missing_dates


def test_leading_edge_unverified_passes_and_reports_metadata_when_no_middle_gap():
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df("2026-03-02", "2026-08-26")

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", min_history_days=60, now=now)

    assert prepared.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert prepared.requested_window_start == date(2026, 2, 26)  # target_start -- kullanıcının İSTEDİĞİ, değişmez
    assert prepared.actual_history_start == date(2026, 3, 2)  # gerçekte GÖZLEMLENEN ilk bar
    assert prepared.backtest_data_as_of == date(2026, 8, 26)


def test_verified_pre_window_metadata_when_fully_continuous():
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df("2025-09-01", "2026-08-26")  # pre-roll evidence + fully continuous target window

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", min_history_days=60, now=now)

    assert prepared.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert prepared.requested_window_start == date(2026, 2, 26)
    assert prepared.actual_history_start == date(2026, 2, 26)  # expected_start == target_start
    assert prepared.backtest_data_as_of == date(2026, 8, 26)


def test_min_history_counts_only_analysis_history_not_pre_roll():
    # HATA 3E madde 14: analiz penceresi (target_start onward) TEK BAŞINA
    # min_history_days'i karşılamıyorsa, pre-roll'un (evidence-only) EK
    # bar sayısı bunu YAPAY olarak artırmamalı.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26, target_start(6mo)=2026-02-26
    pre_roll = _bday_df("2026-02-11", "2026-02-25")  # 11 valid pre-roll seansı (evidence)
    analysis_window = _bday_df("2026-02-26", "2026-08-26")  # 122 valid seans -- TAM, kesintisiz analiz penceresi
    df = pd.concat([pre_roll, analysis_window]).sort_index()
    assert len(pre_roll) == 11 and len(analysis_window) == 122
    assert len(df) == 133  # pre-roll YANLIŞLIKLA sayılsaydı 133 >= 125 ile PASS ederdi

    with pytest.raises(DataQualityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", min_history_days=125, now=now)

    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_empty_analysis_history_after_crop_raises_insufficient_history_not_crash():
    # HATA 3E madde 11: provider yalnızca pre-roll bölgesinde bar döndürüp
    # target_start'tan itibaren HİÇ bar döndürmezse crop sonrası analysis_
    # history TAMAMEN BOŞ kalır -- IndexError/teknik crash YERİNE
    # deterministik DataQualityError(INSUFFICIENT_HISTORY) beklenir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_start(6mo)=2026-02-26
    only_pre_roll = _bday_df("2026-02-11", "2026-02-25")  # tamamı target_start'tan ÖNCE

    with pytest.raises(DataQualityError) as exc_info:
        prepare_backtest_history(_FakeProvider(only_pre_roll), "TEST", "6mo", min_history_days=60, now=now)

    assert exc_info.value.reason_code == "INSUFFICIENT_HISTORY"


def test_target_start_on_weekend_resolves_to_next_valid_session():
    # HATA 3E madde 23: target_start bir hafta sonuna/tatile denk gelebilir --
    # bu bir HARD_VETO gerekçesi DEĞİLDİR. `expected_trading_sessions()`
    # zaten bir sonraki gerçek geçerli seanstan başlar.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26
    # period=3y -> target_start = 2023-08-26 (CUMARTESİ)
    df = _bday_df("2022-01-03", "2026-08-26")  # pre-roll evidence BOL -- VERIFIED_PRE_WINDOW

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "3y", min_history_days=60, now=now)

    assert prepared.requested_window_start == date(2023, 8, 26)  # Cumartesi -- olduğu gibi taşınır
    assert prepared.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert prepared.actual_history_start == date(2023, 8, 28)  # ilk GERÇEK geçerli seans (Pazartesi)


def test_requested_window_touching_unsupported_year_fails_before_provider_fetch():
    # HATA 3E FINAL AUDIT'te sentetik kanıtlanan kör nokta: `resolve_expected_
    # start()`'ın LEADING_EDGE_UNVERIFIED dalı `expected_start`'ı ileri
    # taşıyabildiğinden, yalnızca `expected_start.year`'dan başlayan bir
    # kontrol `target_start`'ın desteklenmeyen bir yılda kalmasını
    # GÖRMEYEBİLİRDİ. `validate_calendar_coverage(target_start, target_end)`
    # artık provider'a GİTMEDEN, evidence çözümlenmeden ÖNCE bunu yakalar.
    now = datetime(2025, 8, 25, 19, 0, tzinfo=TZ)  # target_end=2025-08-25
    # period=5y -> target_start = 2020-08-25 (2020 DESTEKLENMİYOR)

    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", "5y", min_history_days=60, now=now)

    assert exc_info.value.year == 2020


def test_pre_roll_request_clips_to_earliest_supported_calendar_date_without_failing():
    # Requested window'un KENDİSİ (target_start=2021-01-10..target_end=
    # 2021-07-10) TAMAMEN desteklenen bir yılda (2021) -- yalnızca ADVISORY
    # pre-roll'un ham hesabı (target_start - 15 gün = 2020-12-26) desteklenmeyen
    # 2020'ye taşıyor. Bu durum FAIL-CLOSED OLMAMALI -- provider'a giden
    # `start`, authoritative takvimin ilk desteklenen gününe (2021-01-01)
    # KIRPILMALI, kırpılmış bölgede kanıt yoksa LEADING_EDGE_UNVERIFIED'a düşmeli.
    now = datetime(2021, 7, 10, 19, 0, tzinfo=TZ)  # target_end=2021-07-10 -> target_start(6mo)=2021-01-10
    df = _bday_df("2021-01-11", "2021-07-10")  # target_start'tan ÖNCE hiç bar yok (evidence YOK)
    provider = _CapturingProvider(df)

    prepared = prepare_backtest_history(provider, "TEST", "6mo", min_history_days=60, now=now)

    assert provider.calls[0]["start"] == "2021-01-01"  # 2020-12-26 DEĞİL -- authoritative sınıra kırpıldı
    assert prepared.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert prepared.requested_window_start == date(2021, 1, 10)
