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
    completed = _bday_df("2025-01-05", "2026-08-25")  # ...24,25 Agustos completed
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    prepared = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-25").date()
    assert prepared.indicator_history.index[-1].date() == pd.Timestamp("2026-08-25").date()
    assert pd.Timestamp("2026-08-26", tz=TZ) not in prepared.indicator_history.index  # partial satir hic girmedi


def test_post_cutoff_includes_todays_now_completed_row():
    # now: kapanis (18:00) + finalization payi (30dk) GECTI -- bugunku satir artik tamamlanmis kabul edilir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    completed = _bday_df("2025-01-05", "2026-08-25")
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    prepared = prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-26").date()
    assert prepared.indicator_history.index[-1].date() == pd.Timestamp("2026-08-26").date()
    # artik hicbir satir cikarilmadi (partial satirin index'i _append_partial_row'da
    # tz-naive kaldigindan, karsilastirmayi .date() uzerinden yapariz)
    assert pd.Timestamp("2026-08-26").date() in [ts.date() for ts in prepared.indicator_history.index]


def test_partial_row_cannot_satisfy_minimum_history():
    # HATA 3B madde 3/12, HATA 5A ile GÜÇLENDİ: raw=60 (59 completed + 1
    # partial) -> completed=59. Eskiden bu, uzunluk-bazlı INSUFFICIENT_HISTORY
    # kontrolüne (min_history_days=60) takılıyordu. HATA 5A sonrası mandatory
    # 60-session warm-up continuity kontrolü (warmup_history_start..target_end,
    # ~312 session gerektirir) BUNDAN DAHA ERKEN VE DAHA GÜÇLÜ bir kapı haline
    # geldi -- 59 satırlık bu fixture artık MISSING_TRADING_SESSION (continuity)
    # ile HARD VETO ediliyor, INSUFFICIENT_HISTORY'ye hiç ulaşmadan. Partial
    # satırın "sayıyı yapay olarak tamamlaması" ihtimali her iki durumda da
    # ENGELLENMİŞ oluyor -- yalnızca hangi kapıdan (continuity vs length)
    # engellendiği değişti.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df(end="2026-08-25", periods=59)
    assert len(completed) == 59
    raw = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)
    assert len(raw) == 60  # raw eski MIN_HISTORY_DAYS(60) sartini "karsiliyormus gibi" gorunuyor

    with pytest.raises(DataQualityError) as exc_info:
        prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"


def test_partial_contamination_isolation_two_wildly_different_partial_rows_produce_identical_output():
    # HATA 3B'nin ana regresyon kilidi: iki AYRI partial "bugun" satiri
    # (biri sakin, biri asiri oynak) -- backtest'e HICBIR SEKILDE girmemeli.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    completed = _bday_df("2025-01-05", "2026-08-25")

    raw_a = _append_partial_row(completed, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)
    raw_b = _append_partial_row(completed, "2026-08-26", open_=500.0, close=900.0, volume=999_000_000)

    prepared_a = prepare_backtest_history(_FakeProvider(raw_a), "TEST", "1y", now=now)
    prepared_b = prepare_backtest_history(_FakeProvider(raw_b), "TEST", "1y", now=now)

    assert prepared_a.backtest_data_as_of == prepared_b.backtest_data_as_of
    pd.testing.assert_frame_equal(prepared_a.indicator_history, prepared_b.indicator_history)


def test_weekend_now_does_not_alter_friday_completed_history():
    # Cumartesi (2026-08-29) frozen now -- Cuma (2026-08-28) zaten tamamlanmis,
    # hafta sonu icin hicbir satir yok -- hicbir sey degismemeli.
    now = datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
    completed = _bday_df("2025-01-05", "2026-08-28")

    prepared = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2026-08-28").date()
    assert prepared.indicator_history.index[-1].date() == pd.Timestamp("2026-08-28").date()


def test_provider_gap_at_boundary_is_hard_vetoed_not_silently_accepted():
    # HATA 3C (26.08.2026): onceki (HATA 3B) davranis "25.08 eksikse
    # backtest_data_as_of sessizce 24.08'e gerilesin, PASS etsin" idi --
    # bu, tam olarak HATA 2B/3'un canli olarak defalarca gozlemledigi gercek
    # senaryo (24.08 var, 25.08 provider'da YOK, 26.08 partial). Artik bu
    # ARTIK sessizce kabul edilmiyor -- latest_expected_completed_date(now)
    # (=2026-08-25) beklenen ust sinira gore 25.08 hala "expected" ve
    # gozlemlenmedigi icin HARD_VETO (MISSING_TRADING_SESSION) olmali.
    now = datetime(2026, 8, 26, 10, 44, tzinfo=TZ)
    # HATA 5A: "1y" mandatory 60-session warm-up + ~252 simulation gerektirir.
    completed_through_24 = _bday_df(end="2026-08-24", periods=340)  # 25.08 hic YOK (holiday DEGIL, gercek bosluk)
    raw = _append_partial_row(completed_through_24, "2026-08-26", open_=100.0, close=110.0, volume=1_000_000)

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(raw), "TEST", "1y", now=now)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-08-25").date()]


def test_middle_gap_not_at_boundary_is_hard_vetoed():
    # HATA 3C madde 9: gap tam ortada (ne son bar ne bugunun sinirinda).
    now = datetime(2026, 8, 27, 19, 0, tzinfo=TZ)  # boundary = 27.08 (son gercek bar ile ayni)
    df = _bday_df("2025-01-05", "2026-08-27", exclude=["2026-08-25"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

    assert exc_info.value.missing_dates == [pd.Timestamp("2026-08-25").date()]
    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"


def test_holiday_now_does_not_alter_prior_session_history():
    # Resmi BIST tam gun kapanisi (2026-01-01) frozen now -- son gercek
    # islem gunu (2025-12-31) zaten tamamlanmis, o gun icin Yahoo hic satir
    # dondurmez -- filtre hicbir seyi degistirmemeli (bkz. completed_bars.py
    # docstring: resmi tatilde bu modulun hicbir etkisi yok).
    now = datetime(2026, 1, 1, 12, 0, tzinfo=TZ)
    # HATA 5A: "1y" için mandatory 60-session warm-up + ~252 simulation
    # session'ı karşılayacak kadar geniş (fixture eskiden yalnızca 2025-09-01
    # başlıyordu, artık warmup_history_start'a ulaşamazdı).
    completed = _bday_df("2024-01-02", "2025-12-31")

    prepared = prepare_backtest_history(_FakeProvider(completed), "TEST", "1y", now=now)

    assert prepared.backtest_data_as_of == pd.Timestamp("2025-12-31").date()
    assert prepared.indicator_history.index[-1].date() == pd.Timestamp("2025-12-31").date()


def test_half_day_2024_04_09_missing_is_hard_vetoed():
    # HATA 3C madde 10: 2024-04-09 (Ramazan Bayramı Arefesi) authoritative
    # HALF-DAY expected session'dır -- eksikse ignore/interpolation YAPILMAZ,
    # tıpkı tam gün bir eksiklik gibi HARD_VETO edilir.
    now = datetime(2024, 4, 30, 19, 0, tzinfo=TZ)
    # HATA 5A: "1y" mandatory 60-session warm-up + ~252 simulation session
    # gerektirdiğinden fixture 2022 başına kadar genişletildi.
    df = _bday_df("2022-01-03", "2024-04-30", exclude=["2024-04-09"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

    assert date(2024, 4, 9) in exc_info.value.missing_dates


# ---------------------------------------------------------------------------
# HATA 3C, madde 1 / HATA 3E, madde 1: authoritative backtest period sözleşmesi.
# `SUPPORTED_BACKTEST_PERIODS` artık `BACKTEST_PERIOD_DELTAS`'tan türer (tek
# source-of-truth) — iki koleksiyonun birbirinden sapması yapısal olarak
# imkansız, bu yüzden ayrı bir "set eşitliği" testi GEREKMEZ.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", sorted(SUPPORTED_BACKTEST_PERIODS))
def test_supported_period_passes_validation_and_uses_explicit_window(period):
    # HATA 5A NOTU: HATA 3E'deki orijinal versiyon kısa (120 günlük) bir
    # fixture'ın HER period için (5y dahil) LEADING_EDGE_UNVERIFIED ile
    # sorunsuz geçtiğini doğruluyordu -- bu, HATA 5A'nın BİLİNÇLİ OLARAK
    # SIKILAŞTIRDIĞI bir davranıştı: artık mandatory 60-session warm-up
    # aralığının (`warmup_history_start..target_end`) TAMAMEN dolu olması
    # ZORUNLU (evidence durumundan bağımsız, bkz. completed_history.py modül
    # docstring'i) -- "belki yeni listing'dir" diye otomatik tolere
    # EDİLMİYOR. Bu yüzden fixture artık authoritative takvimin başına
    # yakın kadar geniş (TÜM period'ların, 5y dahil, mandatory warm-up'ını
    # karşılayacak şekilde) tutuldu; testin amacı artık "kısa geçmiş her
    # zaman güvenle geçer" DEĞİL, "explicit start/end fetch contract'ı
    # (period= hiç gönderilmemesi) HER desteklenen period için doğru
    # çalışıyor" olarak netleştirildi.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df("2021-01-04", "2026-08-26")
    provider = _CapturingProvider(df)

    prepared = prepare_backtest_history(provider, "TEST", period, now=now)

    assert prepared.history_validation_status in ("VERIFIED_PRE_WINDOW", "LEADING_EDGE_UNVERIFIED")
    assert len(provider.calls) == 1
    assert "period" not in provider.calls[0]  # Yahoo'ya artık period= GÖNDERİLMİYOR
    assert "start" in provider.calls[0] and "end" in provider.calls[0]


@pytest.mark.parametrize("period", ["max", "10y", "ytd", "random", ""])
def test_unsupported_period_is_rejected_before_fetching_provider_history(period):
    # Period validasyonu provider.get_history()'DEN ÖNCE çalışır -- ağa hiç
    # gidilmez (bkz. _AssertNotCalledProvider).
    with pytest.raises(ValueError):
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", period)


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
    # HATA 5A NOTU: bu, `prepare_backtest_history()`'nin normalizasyonu
    # DOĞRU ENTEGRE ettiğini (izole normalizasyon mekaniğini değil) test
    # eder -- bu yüzden `_feb_2023_earthquake_df()` (yalnızca 3 satır) artık
    # mandatory 60-session warm-up'ı tek başına sağlayamadığından, warm-up'ı
    # kapsayan sürekli bir taban geçmişin ARDINA eklenir (warmup_history_start
    # = 2021-11-23, bkz. sanity script).
    now = datetime(2023, 2, 15, 19, 0, tzinfo=TZ)  # boundary = 15.02 (son gercek bar ile ayni)
    base = _bday_df("2021-09-01", "2023-02-06")
    df = pd.concat([base, _feb_2023_earthquake_df()]).sort_index()

    prepared = prepare_backtest_history(_FakeProvider(df), "THYAO", "1y", now=now)

    # 08.02 normalizasyon sonrası TAMAMEN gitti -- 07.02 -> 15.02 ardışık.
    assert list(prepared.indicator_history.index.date)[-2:] == [date(2023, 2, 7), date(2023, 2, 15)]
    assert date(2023, 2, 8) not in prepared.indicator_history.index.date
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
    # HATA 5A NOTU: mandatory 60-session warm-up (warmup_history_start =
    # 2025-02-07, bkz. sanity script) `valid_before`'un tek başına
    # sağlayamayacağı kadar geriye gider -- bu yüzden sürekli bir taban
    # geçmiş öne eklenir; testin amacı (1 Mayıs phantom bar'ının OHLC/Volume
    # desenine değil yalnızca takvime göre düşürülmesi) değişmez.
    now = datetime(2026, 5, 8, 19, 0, tzinfo=TZ)
    valid_before = _bday_df("2024-11-01", "2026-04-30")
    bogus_holiday_row = pd.DataFrame(
        {"Open": [50.0], "High": [51.0], "Low": [49.0], "Close": [50.0], "Volume": [100]},
        index=[pd.Timestamp("2026-05-01", tz=TZ)],  # 1 Mayıs -- resmi tatil, gerçekte hiç bar olmamalı
    )
    valid_after = _bday_df("2026-05-04", "2026-05-08")
    df = pd.concat([valid_before, bogus_holiday_row, valid_after]).sort_index()

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

    assert date(2026, 5, 1) not in [ts.date() for ts in prepared.indicator_history.index]
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
        prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

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
    # HATA 5A: "1y" mandatory 60-session warm-up + ~252 simulation gerektirir.
    df = _bday_df(end=expected_target_end.isoformat(), periods=340)

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

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
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert exc_info.value.missing_dates == [date(2026, 2, 26), date(2026, 2, 27)]


def test_leading_edge_unverified_tolerates_start_gap_but_still_vetoes_middle_gap():
    # HATA 5A NOTU: "start gap tolerance" artık `target_start`'a DEĞİL,
    # yalnızca `warmup_history_start`'IN ÖNCESİNDEKİ (advisory pre-roll)
    # kanıta uygulanır -- mandatory warm-up'ın KENDİSİ (warmup_history_start
    # onward) HİÇBİR ZAMAN gevşetilmez (final blocker fix). Bu yüzden
    # fixture, pre-roll kanıtı OLMADAN doğrudan `warmup_history_start`'tan
    # (2025-12-03, bkz. sanity script) başlar; test artık yalnızca
    # warm-up/simülasyon ARASINDAKİ gerçek bir middle-gap'in hâlâ HARD_VETO
    # tetiklediğini doğruluyor.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26, warmup_history_start(6mo)=2025-12-03
    df = _bday_df("2025-12-03", "2026-08-26", exclude=["2026-05-05"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert exc_info.value.missing_dates == [date(2026, 5, 5)]
    assert date(2025, 12, 3) not in exc_info.value.missing_dates


def test_leading_edge_unverified_passes_and_reports_metadata_when_no_middle_gap():
    # HATA 5A NOTU: pre-roll kanıtı OLMADAN doğrudan `warmup_history_start`'tan
    # (2025-12-03) başlayan, aralıksız bir fixture -- LEADING_EDGE_UNVERIFIED
    # artık yalnızca "warmup_history_start'ın ÖNCESİNDE kanıt yok" anlamına
    # gelir, mandatory bölgenin kendisi eksiksiz kalmalıdır.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df("2025-12-03", "2026-08-26")

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert prepared.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert prepared.requested_window_start == date(2026, 2, 26)  # target_start -- kullanıcının İSTEDİĞİ, değişmez
    assert prepared.warmup_history_start == date(2025, 12, 3)
    assert prepared.actual_indicator_history_start == date(2025, 12, 3)  # gerçekte GÖZLEMLENEN ilk warm-up barı
    assert prepared.actual_history_start == date(2026, 2, 26)  # simulation_history'nin ilk barı == simulation_start
    assert prepared.backtest_data_as_of == date(2026, 8, 26)


def test_missing_first_warmup_session_is_hard_vetoed_regardless_of_evidence_status():
    # HATA 5A "FINAL BLOCKER" REGRESYON KİLİDİ: `resolve_expected_start()`'ın
    # döndürdüğü evidence durumu (VERIFIED_PRE_WINDOW/LEADING_EDGE_UNVERIFIED)
    # `check_trading_day_continuity()`'e geçirilen alt sınırı ASLA belirlemez
    # -- o alt sınır HER ZAMAN `warmup_history_start`'ın KENDİSİdir (bkz.
    # completed_history.py modül docstring'i). Bu test, mandatory warm-up'ın
    # İLK seansının (W1 = warmup_history_start = 2025-12-03) provider'da HİÇ
    # olmadığı, ama sonrasının tamamen sürekli olduğu senaryoyu kurar --
    # düzeltmeden ÖNCE bu, "pre-roll'da kanıt yok, ilk gözlemlenen barı al"
    # (LEADING_EDGE_UNVERIFIED) yoluna sessizce düşüp W1'in eksikliğini
    # MASKELERDİ. Düzeltmeden SONRA bu HER ZAMAN HARD VETO olmalıdır.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # warmup_history_start(6mo)=2025-12-03
    df = _bday_df("2025-12-03", "2026-08-26", exclude=["2025-12-03"])  # W1'in KENDİSİ eksik

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert date(2025, 12, 3) in exc_info.value.missing_dates


def test_middle_warmup_session_missing_is_hard_vetoed_not_just_boundary():
    # HATA 5A REQUIRED TEST TRACE MATRIX, madde I: W1 (madde J, warm-up'ın
    # İLK seansı) DIŞINDA, warm-up aralığının TAM ORTASINDAKİ (2026-01-15,
    # warmup_history_start=2025-12-03..simulation_start-1=2026-02-25
    # aralığının tam ortası, bkz. sanity script) tek bir eksik seans bile
    # HARD VETO'ya yol açmalı -- mandatory continuity yalnızca sınırları
    # (W1/son gün) değil, aralığın TAMAMINI kapsar.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # warmup_history_start(6mo)=2025-12-03
    df = _bday_df("2025-12-03", "2026-08-26", exclude=["2026-01-15"])

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"
    assert exc_info.value.missing_dates == [date(2026, 1, 15)]


def test_verified_pre_window_metadata_when_fully_continuous():
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)
    df = _bday_df("2025-09-01", "2026-08-26")  # pre-roll evidence + fully continuous target window

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert prepared.history_validation_status == "VERIFIED_PRE_WINDOW"
    assert prepared.requested_window_start == date(2026, 2, 26)
    assert prepared.actual_history_start == date(2026, 2, 26)  # expected_start == target_start
    assert prepared.backtest_data_as_of == date(2026, 8, 26)


def test_evidence_rows_are_categorically_excluded_from_indicator_history():
    # HATA 5A FINAL COMMIT GATE, madde 1: madde M'in (evidence-only rows
    # indicator_history'ye girmiyor) önceki kanıtı (`test_backtest_engine_
    # run_warm_up_boundary_is_identical_with_and_without_pre_roll_evidence`,
    # test_backtest_completed_session.py) yalnızca DOLAYLI bir output-parity
    # testiydi ("evidence var/yok sonuç aynı") -- bu test ise CONTRACT'ı
    # DOĞRUDAN kilitler: fixture GERÇEKTEN üç ayrı bölge içerir (evidence /
    # tam 60 warm-up / simulation), ve `indicator_history`'nin sınırları,
    # ayrıca evidence tarihleriyle KESİŞİMİ doğrudan assert edilir. Bu yeni
    # test MEVCUT parity testinin YERİNE değil, YANINA eklenmiştir.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> simulation_start(1y)=2025-08-26
    evidence = _bday_df("2025-03-01", "2025-05-28", seed=9)  # warmup_history_start'IN ÖNCESİNDE -- yalnız evidence
    warmup_and_simulation = _bday_df("2025-05-29", "2026-08-26")  # warmup_history_start(=2025-05-29)..target_end
    df = pd.concat([evidence, warmup_and_simulation]).sort_index()

    # Önkoşul: fixture GERÇEKTEN üç bölge içeriyor -- evidence satırları
    # warmup_history_start'tan (2025-05-29) KESİNLİKLE ÖNCE.
    assert len(evidence) > 0
    assert all(ts.date() < date(2025, 5, 29) for ts in evidence.index)

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

    assert prepared.history_validation_status == "VERIFIED_PRE_WINDOW"  # evidence GERÇEKTEN bulundu
    assert prepared.warmup_history_start == date(2025, 5, 29)
    assert prepared.simulation_start == date(2025, 8, 26)

    # DOĞRUDAN kontrat kilidi: indicator_history TAM OLARAK warmup_history_
    # start'ta başlar, simulation_history TAM OLARAK simulation_start'ta.
    assert prepared.indicator_history.index[0].date() == prepared.warmup_history_start
    assert prepared.simulation_history.index[0].date() == prepared.simulation_start
    assert all(ts.date() >= prepared.warmup_history_start for ts in prepared.indicator_history.index)
    assert all(ts.date() >= prepared.simulation_start for ts in prepared.simulation_history.index)

    # ASIL kilit: evidence tarihleri ile indicator_history tarihleri KESİŞMEZ
    # -- evidence yalnızca history_validation_status'u belirlemek için
    # KULLANILIR (yukarıdaki VERIFIED_PRE_WINDOW assert'i bunu kanıtlar),
    # ama indicator_history'ye (dolayısıyla skor/warm-up hesabına) ASLA girmez.
    evidence_dates = {ts.date() for ts in evidence.index}
    indicator_history_dates = {ts.date() for ts in prepared.indicator_history.index}
    assert evidence_dates & indicator_history_dates == set()


def test_evidence_only_malformed_row_does_not_veto_real_prepare_backtest_history():
    # HATA 5B1 FINAL PRE-COMMIT GATE, madde 4: `check_raw_ohlcv_integrity()`'in
    # (Layer 1) evidence-only pre-roll'a YANLIŞLIKLA genişlemediğini yalnızca
    # fonksiyonu izole çağırarak (bkz. test_data_quality.py, `test_evidence_
    # only_malformed_row_outside_mandatory_window_does_not_veto`) DEĞİL, GERÇEK
    # `prepare_backtest_history()` uçtan uca akışıyla kanıtlar -- HATA 5A +
    # HATA 5B1 parity kilidi.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26 -> simulation_start(1y)=2025-08-26
    evidence = _bday_df("2025-03-01", "2025-05-28", seed=9)  # warmup_history_start'IN ÖNCESİNDE -- yalnız evidence
    malformed_date = evidence.index[3]
    evidence.loc[malformed_date, "Close"] = float("nan")  # BİLEREK bozuk -- evidence-only bölgede
    warmup_and_simulation = _bday_df("2025-05-29", "2026-08-26")  # warmup_history_start(=2025-05-29)..target_end
    df = pd.concat([evidence, warmup_and_simulation]).sort_index()

    assert malformed_date.date() < date(2025, 5, 29)  # önkoşul: gerçekten evidence-only bölgede

    # PASS beklenir -- Layer 1 HARD VETO tetiklenMEMELİ (bozuk satır mandatory
    # pencerenin dışında).
    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "1y", now=now)

    assert prepared.history_validation_status == "VERIFIED_PRE_WINDOW"  # evidence GERÇEKTEN bulundu (NaN'a RAĞMEN)
    assert prepared.warmup_history_start == date(2025, 5, 29)
    assert prepared.indicator_history.index[0].date() == date(2025, 5, 29)
    # Bozuk evidence tarihi indicator_history'ye HİÇ GİRMEDİ.
    assert malformed_date.date() not in [ts.date() for ts in prepared.indicator_history.index]
    # indicator_history'nin KENDİSİ tamamen temiz (NaN İÇERMİYOR).
    assert not prepared.indicator_history.isna().any().any()
    assert prepared.simulation_history.index[0].date() == prepared.simulation_start


def test_min_history_counts_only_analysis_history_not_pre_roll():
    # HATA 3E madde 14: analiz penceresi (target_start onward) TEK BAŞINA
    # min_history_days'i karşılamıyorsa, pre-roll'un (evidence-only) EK
    # bar sayısı bunu YAPAY olarak artırmamalı.
    # HATA 5A NOTU: bu fixture, mandatory warm-up'ın (warmup_history_start=
    # 2025-12-03) ÇOK gerisinde kalıyor -- artık DataQualityError'a hiç
    # ulaşılmadan, ÇOK DAHA ERKEN VE GÜÇLÜ mandatory continuity kapısı
    # (TradingDayContinuityError/MISSING_TRADING_SESSION) devreye giriyor.
    # Bu, testin ORİJİNAL amacını (pre-roll'un analiz yeterliliğini yapay
    # artırmaması) hâlâ dolaylı olarak kanıtlıyor -- pre-roll'un 11 seansı
    # burada da hiçbir şeyi "kurtarmıyor".
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26, target_start(6mo)=2026-02-26
    pre_roll = _bday_df("2026-02-11", "2026-02-25")  # 11 valid pre-roll seansı (evidence)
    analysis_window = _bday_df("2026-02-26", "2026-08-26")  # 122 valid seans -- TAM, kesintisiz analiz penceresi
    df = pd.concat([pre_roll, analysis_window]).sort_index()
    assert len(pre_roll) == 11 and len(analysis_window) == 122
    assert len(df) == 133  # pre-roll YANLIŞLIKLA sayılsaydı 133 >= 125 ile PASS ederdi

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(df), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"


def test_empty_analysis_history_after_crop_raises_insufficient_history_not_crash():
    # HATA 3E madde 11: provider yalnızca pre-roll bölgesinde bar döndürüp
    # target_start'tan itibaren HİÇ bar döndürmezse crop sonrası analysis_
    # history TAMAMEN BOŞ kalır -- IndexError/teknik crash YERİNE
    # deterministik bir hata beklenir.
    # HATA 5A NOTU: aynı fixture artık DataQualityError'dan ÖNCE mandatory
    # warm-up continuity kapısına (TradingDayContinuityError/
    # MISSING_TRADING_SESSION) takılıyor -- "boş analiz penceresi" durumu
    # bu daha erken kapı tarafından zaten deterministik biçimde engelleniyor,
    # teknik bir crash YOK.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_start(6mo)=2026-02-26
    only_pre_roll = _bday_df("2026-02-11", "2026-02-25")  # tamamı target_start'tan ÖNCE

    with pytest.raises(TradingDayContinuityError) as exc_info:
        prepare_backtest_history(_FakeProvider(only_pre_roll), "TEST", "6mo", now=now)

    assert exc_info.value.reason_code == "MISSING_TRADING_SESSION"


def test_target_start_on_weekend_resolves_to_next_valid_session():
    # HATA 3E madde 23: target_start bir hafta sonuna/tatile denk gelebilir --
    # bu bir HARD_VETO gerekçesi DEĞİLDİR. `expected_trading_sessions()`
    # zaten bir sonraki gerçek geçerli seanstan başlar.
    now = datetime(2026, 8, 26, 18, 45, tzinfo=TZ)  # target_end=2026-08-26
    # period=3y -> target_start = 2023-08-26 (CUMARTESİ)
    df = _bday_df("2022-01-03", "2026-08-26")  # pre-roll evidence BOL -- VERIFIED_PRE_WINDOW

    prepared = prepare_backtest_history(_FakeProvider(df), "TEST", "3y", now=now)

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
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", "5y", now=now)

    assert exc_info.value.year == 2020


def test_mandatory_warmup_touching_unsupported_year_fails_before_provider_fetch_even_when_requested_window_is_supported():
    # HATA 5A REQUIRED TEST TRACE MATRIX, madde N: yukarıdaki testten (`test_
    # requested_window_touching_unsupported_year_fails_before_provider_fetch`)
    # KASITLI OLARAK FARKLI bir senaryo -- burada İSTENEN pencerenin KENDİSİ
    # (`[target_start, target_end]` = `[2021-02-01, 2021-08-01]`) TAMAMEN
    # desteklenen bir yılda (2021), yalnızca MANDATORY 60-session warm-up'ın
    # hesabı (`previous_expected_sessions(simulation_start, 60)`) geriye
    # doğru 2020'ye (desteklenmiyor) taşıyor. Mandatory warm-up, evidence
    # pre-roll'un aksine CLIP YAPILMAZ -- deterministic fail-fast, provider'a
    # HİÇ gidilmeden (bkz. sanity script: now=2021-08-01, period=6mo ->
    # target_start=simulation_start=2021-02-01 -> previous_expected_sessions
    # 2020'ye taşıp TradingCalendarUnsupportedError fırlatır).
    now = datetime(2021, 8, 1, 19, 0, tzinfo=TZ)  # target_end=2021-08-01 -> target_start(6mo)=2021-02-01

    with pytest.raises(TradingCalendarUnsupportedError) as exc_info:
        prepare_backtest_history(_AssertNotCalledProvider(), "TEST", "6mo", now=now)

    assert exc_info.value.year == 2020


def test_pre_roll_request_clips_to_earliest_supported_calendar_date_without_failing():
    # HATA 5A NOTU: bu senaryo artık İKİ AYRI sınır arasında bilinçli olarak
    # ayrıştırılıyor:
    #   (a) MANDATORY warm-up'ın kendisi (`warmup_history_start`) desteklenen
    #       bir yılda (2021) KALMALI -- aksi halde previous_expected_sessions()
    #       zaten deterministik olarak TradingCalendarUnsupportedError fırlatır
    #       (bkz. test_requested_window_touching_unsupported_year_fails_before_
    #       provider_fetch ve ayrı bir üst-mandatory-warmup-unsupported-year testi).
    #   (b) yalnızca ADVISORY evidence pre-roll'un (`warmup_history_start` - 15
    #       takvim günü) ham hesabı desteklenmeyen bir yıla taşarsa, bu FAIL-CLOSED
    #       OLMAMALI -- provider'a giden `start`, authoritative takvimin ilk
    #       desteklenen gününe (2021-01-01) KIRPILMALI.
    # Bu ikisini AYNI anda sağlamak için warmup_history_start bilinçli olarak
    # 2021 yılının ilk haftalarına (2021-01-04) denk gelecek şekilde seçildi
    # (bkz. sanity script: now=2021-09-29, period=6mo -> target_start=sim_start=
    # 2021-03-29 -> warmup_history_start=2021-01-04 -> advisory preroll=2020-12-20).
    now = datetime(2021, 9, 29, 19, 0, tzinfo=TZ)  # target_end=2021-09-29 -> target_start(6mo)=2021-03-29
    df = _bday_df("2021-01-04", "2021-09-29")  # warmup_history_start'tan ÖNCE hiç bar yok (evidence YOK)
    provider = _CapturingProvider(df)

    prepared = prepare_backtest_history(provider, "TEST", "6mo", now=now)

    assert provider.calls[0]["start"] == "2021-01-01"  # 2020-12-20 DEĞİL -- authoritative sınıra kırpıldı
    assert prepared.history_validation_status == "LEADING_EDGE_UNVERIFIED"
    assert prepared.requested_window_start == date(2021, 3, 29)
    assert prepared.warmup_history_start == date(2021, 1, 4)
