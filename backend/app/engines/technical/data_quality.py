"""Skorlama öncesi zorunlu veri kalite kontrolleri (hard-veto).

TECHNICAL_ANALYSIS_RESEARCH1.md'nin en çok vurguladığı noktalardan biri:
eksik/bayat/tutarsız veri üzerinden üretilen bir TechnicalScore, YANLIŞ ama
kendinden emin görünen bir sinyaldir — bu, hiç sinyal üretmemekten daha
kötüdür. Bu yüzden bu kontroller skorlama mantığı (engine.py) BAŞLAMADAN
önce, ayrı ve merkezi bir yerde çalışır; hem TechnicalAnalysisEngine hem de
BacktestEngine aynı fonksiyonu kullanır (canlı sistemle aynı davranış
sözleşmesi — bkz. backtest/engine.py modül docstring'i).

Kapsam (ilk sürüm): eksik sütun, yetersiz geçmiş, son bar'da eksik OHLCV
değeri, bayat veri (son bar günümüzden çok uzaksa). Spread/likidite/post-news
gap gibi ek veto koşulları ileride ayrı aşamalarda eklenecek (bkz. rapor
madde 7 — geliştirme sırası).
"""

from datetime import date, datetime, timezone

import pandas as pd

from app.services.market_data.completed_bars import latest_expected_completed_date
from app.services.market_data.trading_calendar import expected_trading_sessions, is_year_supported

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# BIST hafta sonu (Cts-Paz) kapalı; +1-2 gün resmi tatil toleransı için 5 gün.
DEFAULT_MAX_STALENESS_DAYS = 5

DEFAULT_PROVIDER_NAME = "yahoo_finance"


class DataQualityError(ValueError):
    """ValueError'dan türer: mevcut API katmanlarındaki `except ValueError`
    yakalama noktaları hiçbir değişiklik gerektirmeden bunu da yakalar.
    `reason_code`, ileride istemci tarafında veya loglarda hangi veto
    koşulunun tetiklendiğini ayırt edebilmek için eklendi.
    """

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(message)


class TradingCalendarUnsupportedError(DataQualityError):
    """HATA 2B (25.08.2026): süreklilik kontrolü, `trading_calendar.py`'de
    tanımlı olmayan bir yıl için ÇALIŞTIRILAMAZ — sessizce "tatil olmalı"
    varsayımı YAPILMAZ, açık bir hata fırlatılır (bkz. trading_calendar.py
    docstring'i, "bakım" notu).
    """

    def __init__(self, year: int):
        self.year = year
        super().__init__(
            "TRADING_CALENDAR_UNSUPPORTED_YEAR",
            f"BIST işlem takvimi {year} yılı için tanımlı değil — işlem günü süreklilik kontrolü yapılamıyor.",
        )


class TradingDayContinuityError(DataQualityError):
    """HATA 2B (25.08.2026): BIST'in resmi takvimine göre beklenen bir işlem
    gününde OHLCV barı yok VE bu, sembolün kendi gözlem penceresinin (ilk
    gerçek barından sonrası) İÇİNDE — yani tatil veya "henüz halka açık
    değildi" ile açıklanamıyor. Alanlar serbest metne gömülmek yerine
    doğrudan öz nitelik (attribute) olarak taşınır — çağıran taraf (API,
    log, gelecekteki bir monitoring katmanı) bunları serbest metni
    ayrıştırmadan doğrudan okuyabilir.
    """

    def __init__(
        self,
        symbol: str,
        missing_dates: list[date],
        checked_period: tuple[date, date],
        provider: str = DEFAULT_PROVIDER_NAME,
        severity: str = "HARD_VETO",
    ):
        self.symbol = symbol
        self.missing_dates = missing_dates
        self.first_missing_date = missing_dates[0]
        self.latest_missing_date = missing_dates[-1]
        self.missing_count = len(missing_dates)
        self.checked_period = checked_period
        self.severity = severity
        self.provider = provider
        message = (
            f"'{symbol}' için {self.missing_count} beklenen BIST işlem günü eksik "
            f"({self.first_missing_date.isoformat()}–{self.latest_missing_date.isoformat()}, "
            f"kaynak: {provider})"
        )
        super().__init__("MISSING_TRADING_SESSION", message)


def check_data_quality(
    df: pd.DataFrame,
    symbol: str,
    min_history_days: int,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    now: datetime | None = None,
) -> None:
    """Herhangi bir kontrol başarısız olursa DataQualityError fırlatır, aksi halde sessizce döner."""
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise DataQualityError(
            "MISSING_COLUMNS", f"'{symbol}' için eksik sütun(lar): {missing_columns}"
        )

    if len(df) < min_history_days:
        raise DataQualityError(
            "INSUFFICIENT_HISTORY",
            f"'{symbol}' için yeterli geçmiş veri yok ({len(df)} gün, en az {min_history_days} gerekli)",
        )

    last_row = df.iloc[-1]
    if last_row[REQUIRED_COLUMNS].isna().any():
        raise DataQualityError(
            "MISSING_OHLCV", f"'{symbol}' için son bar eksik OHLCV değeri içeriyor"
        )

    reference_now = pd.Timestamp(now or datetime.now(timezone.utc))
    if reference_now.tzinfo is None:
        reference_now = reference_now.tz_localize("UTC")

    last_bar_date = df.index[-1]
    if last_bar_date.tzinfo is None:
        last_bar_date = last_bar_date.tz_localize("UTC")

    staleness_days = (reference_now - last_bar_date).days
    if staleness_days > max_staleness_days:
        raise DataQualityError(
            "STALE_DATA",
            f"'{symbol}' için veri bayat (son bar {staleness_days} gün önce, "
            f"en fazla {max_staleness_days} gün izin veriliyor)",
        )


def check_trading_day_continuity(
    df: pd.DataFrame,
    symbol: str,
    provider: str = DEFAULT_PROVIDER_NAME,
    now: datetime | None = None,
    expected_start: date | None = None,
) -> None:
    """BIST'in resmi işlem takvimine göre, `expected_start`'tan (dahil),
    `now`'a göre BEKLENEN son tamamlanmış BIST seansına kadar olan aralıkta
    beklenen ama seride bulunmayan bir işlem günü varsa
    `TradingDayContinuityError` fırlatır.

    Bu fonksiyonun GARANTİ ETTİĞİ ŞEY TAM OLARAK BUDUR — ne daha fazlası, ne
    daha azı: "`expected_start`'tan, now'a göre beklenen son tamamlanmış
    BIST seansına kadar olan continuity." "6 aylık geçmişin TAMAMEN
    eksiksiz olduğu" gibi daha geniş bir iddia YAPILMAZ.

    ÖNEMLİ: Kontrol aralığının üst sınırı `df.index[-1]` DEĞİL,
    `latest_expected_completed_date(now)`'dur (bkz. completed_bars.py).
    Neden: `filter_completed_daily_bars()` "bugünü" çıkardığında, df'in son
    satırı geriye (ör. Cuma'ya) çekilebilir — eğer bu fonksiyon yalnızca
    `df.index[-1]`'e bakıyor olsaydı, tam da "çıkarılan bugün"den hemen
    ÖNCEki gerçek bir boşluk (ör. 24.08.2026, Pazartesi) kontrol aralığının
    DIŞINDA kalıp görünmez hale gelirdi (bu, geliştirme sırasında canlı
    veriyle yakalanan gerçek bir hataydı). `now` paylaşılarak bu iki
    fonksiyon her zaman AYNI "ne kadar ileriye kadar veri bekliyoruz"
    sınırında hemfikir olur.

    **`expected_start` parametresi (HATA 2C, 25.08.2026 — "leading-gap" kör
    noktasının düzeltmesi):** Verilmezse (None) eski davranış korunur:
    alt sınır `df.index[0]`'dır. VERİLİRSE, alt sınır olarak DOĞRUDAN bu
    kullanılır — `df.index[0]`'dan BAĞIMSIZ. Bunun nedeni: HATA 2B'de
    kanıtlanan kör nokta — sağlayıcı, analiz penceresinin TAM BAŞINDAKİ
    günleri düşürürse, `df.index[0]` yanlışlıkla "muhtemelen pre-listing"
    sanılıp gerçek bir boşluk maskelenebiliyordu. Çözüm (bkz.
    `history_window.py`, `resolve_expected_start()`): `df`'e, analiz
    penceresinden BİRAZ daha ÖNCESİNİ kapsayan bir "pre-roll" bölgesi de
    dahil edilir; pre-roll'da EN AZ bir bar bulunması sembolün
    `analysis_start`'tan ÖNCE ZATEN işlem gördüğünü KANITLAR ve o durumda
    `expected_start=analysis_start` geçirilir — pre-roll'un KENDİ içindeki
    boşluklar bu fonksiyona hiç görünmez (`observed_dates`'te var ama
    `expected` listesi `expected_start`'tan başladığından hiç eşleşmezler,
    dolayısıyla asla "eksik" sayılmazlar). Pre-roll'da HİÇ bar yoksa
    (`LEADING_EDGE_UNVERIFIED`), `expected_start` sembolün GÖZLEMLENEN İLK
    barı olur — bu durumda da o tarihten SONRAKİ gerçek boşluklar (bkz.
    "new listing + middle gap" test senaryosu) hâlâ HARD VETO'ya yol açar,
    yalnızca o tarihten ÖNCESİ hiç sorgulanmaz.

    **HÂLÂ ÇÖZÜLMEMİŞ, KABUL EDİLMİŞ SINIRLAMA:** Pre-roll bölgesinin
    TAMAMI boş dönerse (`LEADING_EDGE_UNVERIFIED`), bu GERÇEK bir yeni
    halka arz ile sağlayıcının pre-roll'un TAMAMINI kaybetmesi arasında
    HÂLÂ kesin bir ayrım YAPAMAZ — bilinçli olarak `PRE_LISTING`
    varsayılmaz, ne de otomatik `HARD_VETO` uygulanır (bkz. `engine.py`,
    `HistoryValidationStatus.LEADING_EDGE_UNVERIFIED`).

    Takvim, aralıktaki herhangi bir yıl için tanımlı değilse
    `TradingCalendarUnsupportedError` fırlatılır — sessizce tahmin YÜRÜTÜLMEZ.

    Bu fonksiyon TechnicalAnalysisEngine'e özel bir bağımlılık taşımaz (yalnızca
    bir DataFrame + sembol adı + zaman referansı alır) — aynı imzayla
    BacktestEngine veya ileride eklenecek bir ikincil sağlayıcı katmanı
    tarafından da doğrudan çağrılabilir (bkz. modül docstring'i,
    provider-agnostic tasarım).
    """
    if df.empty:
        return

    first_bar_date = expected_start if expected_start is not None else df.index[0].date()
    boundary_date = latest_expected_completed_date(now)
    end_date = max(df.index[-1].date(), boundary_date)

    for year in range(first_bar_date.year, end_date.year + 1):
        if not is_year_supported(year):
            raise TradingCalendarUnsupportedError(year)

    expected = expected_trading_sessions(first_bar_date, end_date)
    observed_dates = {ts.date() for ts in df.index}
    missing = sorted(d for d in expected if d not in observed_dates)

    if missing:
        raise TradingDayContinuityError(
            symbol=symbol,
            missing_dates=missing,
            checked_period=(first_bar_date, end_date),
            provider=provider,
        )
