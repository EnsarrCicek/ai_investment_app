"""BIST resmi işlem takvimi — HATA 2B (25.08.2026).

Kaynak: Borsa İstanbul A.Ş.'nin her yıl resmi web sitesinde yayınladığı
"Pay Piyasası Tatil Tablosu" (ör. 2026 için
https://www.borsaistanbul.com/files/pay-piyasasi-2026-yili-tatil-tablosu.pdf,
2025 için eşdeğer EK-3 belgesi) — bağımsız bir araştırmayla doğrulanıp elle
transkribe edildi (25.08.2026). Yeni bir kütüphane bağımlılığı EKLENMEDİ;
bu proje kapsamında "resmi, gerçek bir kaynaktan gelen veri" ilkesiyle
tutarlı (sektör riski/haber arşivi gibi güvenilir kaynağı OLMAYAN durumlardan
farklı — burada güvenilir, resmi bir kaynak var).

Yalnızca TAM GÜN kapalı seanslar burada listelenir. Yarım gün (arife)
seansları BİLİNÇLİ OLARAK dışarıda bırakılır — BIST o günler kısa da olsa
gerçek bir seans açıyor, bu yüzden "beklenen işlem günü" sayılmaya devam
etmeliler (`BIST_HALF_DAY_SESSIONS` yalnızca belgeleme/denetim amaçlıdır,
hiçbir filtrelemede kullanılmaz).

Bakım: Bu liste YILLIK olarak güncellenmelidir. Desteklenmeyen bir yıl için
SESSİZCE tahmin YÜRÜTÜLMEZ — `expected_trading_sessions()` böyle bir durumda
`None` döner, çağıran taraf (`data_quality.py`) bunu açık bir
`TradingCalendarUnsupportedError`'a çevirir.
"""

from datetime import date, timedelta

BIST_FULL_DAY_CLOSURES: dict[int, frozenset[date]] = {
    2025: frozenset(
        {
            date(2025, 1, 1),  # Yılbaşı
            date(2025, 3, 31),  # Ramazan Bayramı
            date(2025, 4, 1),  # Ramazan Bayramı
            date(2025, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
            date(2025, 5, 1),  # Emek ve Dayanışma Günü
            date(2025, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
            date(2025, 6, 6),  # Kurban Bayramı
            date(2025, 6, 9),  # Kurban Bayramı
            date(2025, 7, 15),  # Demokrasi ve Milli Birlik Günü
            date(2025, 10, 29),  # Cumhuriyet Bayramı
        }
    ),
    2026: frozenset(
        {
            date(2026, 1, 1),  # Yılbaşı
            date(2026, 3, 20),  # Ramazan Bayramı
            date(2026, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
            date(2026, 5, 1),  # Emek ve Dayanışma Günü
            date(2026, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
            date(2026, 5, 27),  # Kurban Bayramı
            date(2026, 5, 28),  # Kurban Bayramı
            date(2026, 5, 29),  # Kurban Bayramı
            date(2026, 7, 15),  # Demokrasi ve Milli Birlik Günü
            date(2026, 10, 29),  # Cumhuriyet Bayramı
        }
    ),
}

# Yalnızca belgeleme/denetim amaçlı — filtrelemede KULLANILMAZ (yarım günler
# beklenen işlem günü sayılmaya devam eder).
BIST_HALF_DAY_SESSIONS: dict[int, frozenset[date]] = {
    2025: frozenset({date(2025, 6, 5)}),  # Kurban Bayramı Arifesi
    2026: frozenset(
        {
            date(2026, 3, 19),  # Ramazan Bayramı Arifesi
            date(2026, 5, 26),  # Kurban Bayramı Arifesi
            date(2026, 10, 28),  # Cumhuriyet Bayramı Arifesi
        }
    ),
}


def is_year_supported(year: int) -> bool:
    return year in BIST_FULL_DAY_CLOSURES


def is_full_day_closure(day: date) -> bool:
    """Hafta sonu VEYA bilinen tam-gün resmi tatil ise True."""
    if day.weekday() >= 5:
        return True
    return day in BIST_FULL_DAY_CLOSURES.get(day.year, frozenset())


def expected_trading_sessions(start: date, end: date) -> list[date] | None:
    """[start, end] aralığındaki (dahil) BEKLENEN işlem günlerini döner.

    Aralıktaki herhangi bir yıl `BIST_FULL_DAY_CLOSURES`'ta tanımlı değilse
    `None` döner — o durumda sessizce tahmin yürütülmez, çağıran taraf
    bunu açık bir hataya çevirmelidir.
    """
    for year in range(start.year, end.year + 1):
        if not is_year_supported(year):
            return None

    sessions: list[date] = []
    current = start
    one_day = timedelta(days=1)
    while current <= end:
        if not is_full_day_closure(current):
            sessions.append(current)
        current += one_day
    return sessions
