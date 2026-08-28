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

from datetime import date, datetime, timedelta, timezone

import numpy as np
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


def validate_calendar_coverage(start: date, end: date) -> None:
    """HATA 3E (26.08.2026) — `[start, end]` (dahil) aralığındaki HER yılın
    authoritative takvimde tanımlı olup olmadığını, tek tek, side-effect'siz
    kontrol eder. Herhangi bir DataFrame/provider görmez; yalnızca iki
    tarihten hesaplanır.

    Min/max-yıl KISAYOLU KASITLI OLARAK KULLANILMAZ — desteklenen yıllar
    ileride contiguous OLMAYABİLİR (ör. `{2021,2022,2024}`, 2023 eksik);
    `range(start.year, end.year+1)` İÇİNDEKİ HER yıl tek tek doğrulanır,
    aradaki bir yılın eksik olması yalnızca uç yıllara bakan bir kontrolden
    KAÇAMAZ.

    HATA 3E denetiminde kanıtlanan kör noktanın DÜZELTMESİDİR: `resolve_
    expected_start()`'ın `LEADING_EDGE_UNVERIFIED` dalı `expected_start`'ı
    `max(target_start, first_observed)`'a taşıdığından, yalnızca `expected_
    start.year`'dan başlayan bir kontrol (`check_trading_day_continuity()`nin
    KENDİ, defense-in-depth amaçlı taraması) `target_start`'ın desteklenmeyen
    bir yılda kalmasını GÖRMEZ — bu fonksiyon `target_start`/`target_end`
    üzerinde, provider'a hiç gidilmeden, evidence çözümlenmeden ÖNCE
    çağrılmalıdır (bkz. `backtest/completed_history.py`).
    """
    for year in range(start.year, end.year + 1):
        if not is_year_supported(year):
            raise TradingCalendarUnsupportedError(year)


def previous_expected_sessions(before: date, n: int) -> list[date]:
    """HATA 5A (27.08.2026) — backtest'in mandatory indicator warm-up alt
    sınırı: `before` (HARİÇ) öncesindeki tam `n` expected BIST session'ını,
    calendar-day YAKLAŞIK DEĞİL, authoritative takvim üzerinden EN GEÇ
    tarihten geriye doğru döner (`result[-1]` = `before`'dan hemen önceki
    session, `result[0]` = warm-up'ın başladığı session).

    Geriye doğru, YIL YIL genişleyerek arar — her adımda yalnızca o an
    ihtiyaç duyulan yılın desteklenip desteklenmediğini kontrol eder
    (`is_year_supported`), gereğinden fazla geriye taşıp OLMASI GEREKENDEN
    daha erken bir desteklenmeyen yıla çarpma riskini önler. Aranan `n`
    session'a ulaşmadan desteklenmeyen bir yıla ulaşılırsa
    `TradingCalendarUnsupportedError` fırlatılır — CLIP YAPILMAZ (mandatory
    warm-up, HATA 2C'nin pre-roll'u gibi advisory DEĞİLDİR).
    """
    year_cursor = before.year
    while True:
        if not is_year_supported(year_cursor):
            raise TradingCalendarUnsupportedError(year_cursor)
        candidate_start = date(year_cursor, 1, 1)
        sessions = expected_trading_sessions(candidate_start, before - timedelta(days=1))
        if sessions is not None and len(sessions) >= n:
            return sessions[-n:]
        year_cursor -= 1


class TradingDayContinuityError(DataQualityError):
    """HATA 2B (25.08.2026) + HATA 3C (26.08.2026): BIST'in resmi takvimine
    göre beklenen bir işlem gününde OHLCV barı YOK (`missing_dates`) VE/VEYA
    takvime göre "expected" OLMAYAN bir günde (hafta sonu/planlı tatil/
    olağanüstü kapanış) bir bar VAR (`unexpected_dates`) — ikisi de sembolün
    kendi gözlem penceresinin (ilk gerçek barından sonrası) İÇİNDE.

    HATA 3C denetiminde kanıtlandı: önceki sürüm yalnızca `expected -
    observed` (missing) kontrolü yapıyordu, `observed - expected`
    (unexpected) hiç kontrol edilmiyordu — bu, takvimde "non-session"
    olarak işaretli bir güne ait bir bar sessizce kabul edilip göstergelere/
    execution'a sızabiliyordu (bkz. 08.02.2023 sentetik testi). Bilinen,
    kaynak gösterilmiş bir istisna (`BIST_CANCELLED_SESSIONS`) DIŞINDA,
    böyle bir bar asla sessizce düşürülmez veya başka bir güne taşınmaz —
    açıkça HARD VETO edilir.

    Alanlar serbest metne gömülmek yerine doğrudan öz nitelik (attribute)
    olarak taşınır — çağıran taraf (API, log, gelecekteki bir monitoring
    katmanı) bunları serbest metni ayrıştırmadan doğrudan okuyabilir.
    """

    def __init__(
        self,
        symbol: str,
        missing_dates: list[date],
        checked_period: tuple[date, date],
        provider: str = DEFAULT_PROVIDER_NAME,
        severity: str = "HARD_VETO",
        unexpected_dates: list[date] | None = None,
    ):
        self.symbol = symbol
        self.missing_dates = missing_dates
        self.unexpected_dates = unexpected_dates or []
        self.first_missing_date = missing_dates[0] if missing_dates else None
        self.latest_missing_date = missing_dates[-1] if missing_dates else None
        self.missing_count = len(missing_dates)
        self.unexpected_count = len(self.unexpected_dates)
        self.checked_period = checked_period
        self.severity = severity
        self.provider = provider

        message_parts = []
        if missing_dates:
            message_parts.append(
                f"{self.missing_count} beklenen BIST işlem günü eksik "
                f"({self.first_missing_date.isoformat()}–{self.latest_missing_date.isoformat()})"
            )
        if self.unexpected_dates:
            message_parts.append(
                f"{self.unexpected_count} beklenmeyen (non-session) günde veri var "
                f"({self.unexpected_dates[0].isoformat()}–{self.unexpected_dates[-1].isoformat()})"
            )
        message = f"'{symbol}' için " + " ve ".join(message_parts) + f" (kaynak: {provider})"

        # Geriye dönük uyumluluk: yalnızca missing varsa (mevcut, en yaygın
        # durum) reason_code eskisiyle BİREBİR aynı kalır. Yalnızca
        # unexpected varsa yeni, ayrı bir reason_code kullanılır.
        reason_code = "MISSING_TRADING_SESSION" if missing_dates else "UNEXPECTED_TRADING_SESSION"
        super().__init__(reason_code, message)


class InvalidOHLCVError(DataQualityError):
    """HATA 5B1 (27.08.2026) — LAYER 1 (market data quality): mandatory
    skorlanan pencere (`indicator_history` / live'ın `expected_start`'tan
    itibaren kırpılmış analiz penceresi) İÇİNDE, HERHANGİ bir satırda
    (yalnızca son bar DEĞİL — bkz. `check_data_quality`'nin daha dar,
    yalnızca-son-bar kapsamı) NaN/±inf OHLCV, sıfır/negatif fiyat, negatif
    hacim veya imkânsız bir OHLC ilişkisi (`High < Low` vb.) varsa HARD VETO
    eder.

    Bu, HATA 5B1'in component-seviyesi "available/unavailable" renormalizasyon
    contract'ından (bkz. `scoring.py`) KASITLI OLARAK AYRIDIR: bir component'in
    KENDİ matematiğinin (warm-up NaN, 0/0 oranı) tanımsız olması NORMAL ve
    beklenen bir durumdur (Layer 2/3, per-component, graceful renormalizasyon).
    Ama market datanın KENDİSİNİN (Open/High/Low/Close/Volume) bozuk olması
    FARKLI bir kategoridir — component renormalizasyonu bunu ASLA sessizce
    "eksik component" gibi ele alıp gizlememelidir; bu fonksiyon, indikatör
    hesabı hiç BAŞLAMADAN önce (mevcut HATA 2B/3C/3D fail-fast mimarisiyle
    AYNI felsefeyle) tüm satırı reddeder.

    **Kapsam sınırı (HATA 2C/5A evidence semantics KORUNUR):** yalnızca
    ÇAĞIRAN tarafın verdiği mandatory pencere kontrol edilir — evidence-only
    pre-roll (`warmup_history_start`'tan ÖNCESİ) bu fonksiyona HİÇ verilmez
    (bkz. `completed_history.prepare_backtest_history()`/`technical/engine.py`
    çağrı noktaları, her ikisi de yalnızca kendi mandatory kırpılmış
    penceresini geçirir).

    **Bilinçli olarak KAPSAM DIŞI (HATA 5B1 final contract audit'i, madde 7):**
    yinelenen (duplicate) timestamp, timestamp sıralama sorunları — ayrı,
    gelecekteki bir data-quality denetiminin konusu. `Volume == 0` OTOMATİK
    invalid SAYILMAZ (yalnızca `Volume < 0` hard veto'dur) — sıfır hacim ayrı
    bir semantik/data-quality konusudur, bu HATA'nın kapsamında değildir.
    """

    def __init__(self, symbol: str, violations: list[tuple[date, str]]):
        self.symbol = symbol
        self.violations = violations
        preview = ", ".join(f"{d.isoformat()} ({reason})" for d, reason in violations[:5])
        more = f" (+{len(violations) - 5} tane daha)" if len(violations) > 5 else ""
        super().__init__(
            "INVALID_OHLCV",
            f"'{symbol}' için zorunlu skorlanan pencerede geçersiz/tutarsız OHLCV: {preview}{more}",
        )


def check_raw_ohlcv_integrity(df: pd.DataFrame, symbol: str) -> None:
    """LAYER 1 — bkz. `InvalidOHLCVError` docstring'i. `df` boşsa sessizce
    döner (çağıran taraf zaten ayrı bir boş-history kontrolü yapar).
    """
    if df.empty:
        return

    numeric = df[REQUIRED_COLUMNS].astype(float)
    open_, high, low, close, volume = (numeric[c] for c in REQUIRED_COLUMNS)

    finite_mask = pd.DataFrame(
        np.isfinite(numeric.to_numpy()), index=numeric.index, columns=REQUIRED_COLUMNS
    ).all(axis=1)
    non_positive_price_mask = finite_mask & ((open_ <= 0) | (high <= 0) | (low <= 0) | (close <= 0))
    negative_volume_mask = finite_mask & (volume < 0)
    impossible_ohlc_mask = finite_mask & (
        (high < low) | (high < open_) | (high < close) | (low > open_) | (low > close)
    )

    bad_mask = ~finite_mask | non_positive_price_mask | negative_volume_mask | impossible_ohlc_mask
    if not bad_mask.any():
        return

    def _reason(ts) -> str:
        if not finite_mask.loc[ts]:
            return "NaN" if numeric.loc[ts].isna().any() else "INF"
        if non_positive_price_mask.loc[ts]:
            return "NON_POSITIVE_PRICE"
        if negative_volume_mask.loc[ts]:
            return "NEGATIVE_VOLUME"
        return "IMPOSSIBLE_OHLC_RELATIONSHIP"

    violations = [(ts.date(), _reason(ts)) for ts in df.index[bad_mask]]
    raise InvalidOHLCVError(symbol, violations)


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

    **HATA 3C (26.08.2026) — `unexpected_dates` (missing-only kör noktasının
    düzeltmesi):** Önceki sürüm yalnızca `expected - observed` (missing)
    kontrol ediyordu; `observed - expected` (takvime göre "non-session"
    olan ama provider'da bar bulunan tarihler) hiç sorgulanmıyordu — bu,
    ör. resmi olarak iptal edilmiş bir seansın (bkz. `trading_calendar.py`,
    `BIST_CANCELLED_SESSIONS`, 08.02.2023 örneği) sessizce kabul edilip
    göstergelere sızmasına izin veriyordu. Artık HER İKİSİ de kontrol
    edilir; ikisinden biri (veya ikisi birden) doluysa `TradingDayContinuityError`
    fırlatılır. Bilinen `BIST_CANCELLED_SESSIONS` tarihleri, bu fonksiyon
    çağrılmadan ÖNCE `trading_calendar.drop_cancelled_sessions()` ile
    `df`'ten zaten düşürülmüş olmalıdır (bkz. `completed_history.py`) —
    aksi halde o tarih burada `unexpected_dates` olarak HARD VETO'ya yol
    açar (bu fonksiyonun kendisi hiçbir authoritative-normalizasyon
    YAPMAZ, yalnızca kendisine verilen `df`'in takvimle tutarlılığını
    kontrol eder). `unexpected_dates` kontrolü, YALNIZCA `[first_bar_date,
    end_date]` aralığındaki gözlemlenen tarihlere bakar — pre-roll
    bölgesindeki (yukarıdaki `expected_start` açıklamasına bkz.) bar'lar
    bu aralığın DIŞINDA kaldığından hiçbir zaman "unexpected" sayılmaz,
    HATA 2C'nin pre-roll sözleşmesi bozulmaz.
    """
    if df.empty:
        return

    first_bar_date = expected_start if expected_start is not None else df.index[0].date()
    boundary_date = latest_expected_completed_date(now)
    end_date = max(df.index[-1].date(), boundary_date)

    validate_calendar_coverage(first_bar_date, end_date)

    expected = expected_trading_sessions(first_bar_date, end_date)
    expected_set = set(expected)
    observed_dates_in_range = {
        ts.date() for ts in df.index if first_bar_date <= ts.date() <= end_date
    }
    missing = sorted(d for d in expected_set if d not in observed_dates_in_range)
    # HATA 3C commit-öncesi düzeltme (26.08.2026): hafta sonu için özel bir
    # istisna YOK — authoritative kural kesindir: gözlemlenen bir tarih
    # `expected_trading_sessions` içinde değilse (Cumartesi/Pazar dahil)
    # `UNEXPECTED_TRADING_SESSION`'dır. Bilinen `BIST_CANCELLED_SESSIONS`
    # tarihleri bu fonksiyon çağrılmadan ÖNCE authoritative olarak
    # düşürüldüğü için (bkz. `drop_cancelled_sessions`) tek istisna BUDUR —
    # başka hiçbir "muhtemelen zararsızdır" gerekçesiyle yumuşatma YAPILMAZ.
    unexpected = sorted(d for d in observed_dates_in_range if d not in expected_set)

    if missing or unexpected:
        raise TradingDayContinuityError(
            symbol=symbol,
            missing_dates=missing,
            unexpected_dates=unexpected,
            checked_period=(first_bar_date, end_date),
            provider=provider,
        )
