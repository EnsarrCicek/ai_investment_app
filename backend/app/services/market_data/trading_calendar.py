"""BIST resmi işlem takvimi — HATA 2B (25.08.2026), genişletildi HATA 3C/3C-EX/3D (26.08.2026).

Kaynak: Borsa İstanbul A.Ş.'nin her yıl resmi web sitesinde yayınladığı
"Pay Piyasası Tatil Tablosu" (EK-3) belgeleri — 2021-2026'nın TAMAMI bu
oturumda doğrudan indirilip okunarak bağımsız şekilde doğrulandı (26.08.2026):
    https://borsaistanbul.com/files/PayPiyasasi2021YiliTatilTablosu.pdf
    https://borsaistanbul.com/files/pay-piyasasi-2022-yili-tatil-tablosu.pdf
    https://www.borsaistanbul.com/files/pay-piyasasi-2023-yili-tatil-tablosu.pdf
    https://www.borsaistanbul.com/files/pay-piyasasi-2024-yili-tatil-tablosu.pdf
    https://www.borsaistanbul.com/files/pay-piyasasi-2025-yili-tatil-tablosu.pdf
    https://www.borsaistanbul.com/files/pay-piyasasi-2026-yili-tatil-tablosu.pdf
Yeni bir kütüphane bağımlılığı EKLENMEDİ (araştırıldı — `exchange_calendars`/
`pandas_market_calendars` XIST'i destekliyor, ama tatil verileri "user
contributed"dır, resmi kaynakla senkron olduğu garanti değildir; manuel,
resmi-kaynaklı yaklaşım bilinçli olarak sürdürüldü).

Yalnızca TAM GÜN kapalı seanslar `BIST_FULL_DAY_CLOSURES`'ta listelenir.
Yarım gün (arife) seansları BİLİNÇLİ OLARAK ayrı tutulur — BIST o günler
kısa da olsa gerçek, geçerli bir seans açıyor, bu yüzden "beklenen işlem
günü" sayılmaya devam ederler. `BIST_HALF_DAY_SESSIONS` artık yalnızca
belgeleme amaçlı DEĞİLDİR — testlerle (`test_trading_calendar.py`) her
yarım günün gerçekten `expected_trading_sessions()` çıktısında kaldığı
kilitlenmiştir (HATA 3C, madde 3).

HATA 3C-EX (26.08.2026) — ÜÇ AYRI "işlem günü DEĞİL" KATEGORİSİ, provenance
(hangi karardan/hangi kaynaktan geldiği) asla karıştırılmadan:

1. `BIST_FULL_DAY_CLOSURES` — ÖNCEDEN PLANLANMIŞ resmi/dini tatiller.
   Kaynak: yıllık EK-3 "Tatil Tablosu" (yukarıdaki URL'ler). Her yıl aynı,
   öngörülebilir yöntemle güncellenir.

2. `BIST_EXTRAORDINARY_CLOSURES` — Borsa'nın OLAĞANÜSTÜ bir kararla TAM GÜN
   kapattığı, yıllık tatil tablosunda YER ALMAYAN günler. Kaynak: ad-hoc
   KAP/BIST duyurusu (yıllık PDF'lerde bulunmaz, ayrıca araştırılmalıdır).
   Örnek — 6 Şubat 2023 Kahramanmaraş depremi sonrası: BIST 100 endeksi
   %5/%7 devre kesicilerini tetikleyince, Borsa İstanbul Pay Piyasası'nı ve
   VİOP'u 8 Şubat 2023 saat 11:00'den itibaren 5 iş günü süreyle (14 Şubat
   2023 akşamına kadar) TAMAMEN kapattı; işlemler 15 Şubat 2023'te yeniden
   başladı (kaynak: Anadolu Ajansı, KAP duyurusunu doğrudan aktarıyor —
   26.08.2026'da bağımsız araştırmayla doğrulandı). Bu 4 gün (9,10,13,14
   Şubat — hiç seans açılmadı) buraya girer.

3. `BIST_CANCELLED_SESSIONS` — bir seansın FİİLEN AÇILDIĞI ama o güne ait
   TÜM işlemlerin Borsa'nın kendi kararıyla RESMİ OLARAK İPTAL edildiği
   günler. Kaynak: spesifik iptal duyurusu + ilgili yönetmelik maddesi.
   Örnek — 8 Şubat 2023: piyasa 10:00'da açıldı, 10:12/10:42'de devre
   kesici tetiklendi, 11:00'de durduruldu VE o gün gerçekleşen TÜM işlemler
   Borsa İstanbul A.Ş. Yönetmeliği'nin "Emir ve İşlemlerin İptali" başlıklı
   33. maddesi uyarınca RESMİ OLARAK İPTAL EDİLDİ (kaynak: Anadolu Ajansı/
   KAP, aynı araştırmayla doğrulandı). Bu, ne "seans hiç açılmadı" (full-day
   closure) ne "seans normal/kısaltılmış şekilde geçerli kapandı" (half-day)
   kategorisine girer — üçüncü, ayrı bir sınıftır. Yahoo bu tarih için hâlâ
   bir bar döndürüyor (Open=High=Low=Close, ihmal edilebilir hacim — 08.02.
   2023'te THYAO/GARAN/ASELS/SISE/KCHOL'de doğrudan gözlemlendi) — bu bar,
   `normalize_bist_daily_sessions()` içinde authoritative olarak DÜŞÜRÜLÜR,
   skorlamaya/execution'a ASLA girmez.

Fonksiyonel olarak (1) ve (2) `is_full_day_closure()` açısından TAMAMEN
AYNI davranır (o tarih hiç "expected" sayılmaz) — ayrı tutulmalarının
TEK nedeni provenance/auditability'dir (biri her yıl yeniden doğrulanması
gereken rutin bir belge, diğeri tarihe gömülü, tek seferlik bir olay).
(3) ise FARKLI davranır: hem "expected" sayılmaz HEM DE üzerinde bulunan
gerçek bir bar varsa bu bar sessizce yok sayılmaz, açıkça DÜŞÜRÜLÜR (bkz.
`normalize_bist_daily_sessions()`) — genel bir "anomali gördüm, sil" mekanizması
DEĞİLDİR, yalnızca burada AÇIKÇA, kaynak gösterilerek tanımlanmış tarihler
için çalışır. Bilinmeyen/belgelenmemiş herhangi bir başka "beklenmeyen bar"
(ör. hafta sonuna veya bir tatile denk gelen açıklanamayan bir Yahoo barı)
BURADA ele alınmaz — `data_quality.check_trading_day_continuity()` bunu
`UNEXPECTED_TRADING_SESSION` ile HARD VETO eder (bkz. o modülün docstring'i).

2021-2026 araştırıldı; bu aralıkta 2023 Şubat dışında doğrulanabilir başka
bir olağanüstü tam-gün kapanış BULUNAMADI (normal, aynı gün içinde çözülen
intraday devre kesici olayları — ör. 2026 Mayıs/Haziran — kapsam dışıdır,
tam günlük bar oluşumunu engellemezler).

HATA 3D (26.08.2026) — AUTHORITATIVE NON-SESSION NORMALIZATION: Ayrıca
kanıtlandı ki Yahoo, bireysel BIST hisseleri için PLANLI (yıllık tatil
tablosunda olan) tam-gün kapanışlarda da ARA SIRA "phantom" bar
döndürebiliyor — 2021-2026 arası 59 hafta-içi resmi tatilin 7'sinde en az
bir sembolde gözlendi. En şiddetli örnek: **27-28-29 Mayıs 2026 (Kurban
Bayramı tam kapanışı)** — BIST100'ün TAMAMINDA (100/100), her üç günde de
`Open=High=Low=Close=26 Mayıs'ın kapanışı` (donmuş/forward-fill) VE
`Volume=0`. `^XU100` (endeksin kendisi) bu üç günde HİÇ satır döndürmüyor —
anomali yalnızca bireysel hisse sembollerinde. `normalize_bist_daily_
sessions()`, bu barları — OHLC/Volume DEĞERLERİNE BAKMADAN, yalnızca
tarihin authoritative takvimde "expected session" olmadığı bilgisine
dayanarak — düşürür. Bu KESİNLİKLE bir "Volume=0 ise/OHLC eşitse düşür"
heuristic'i DEĞİLDİR (bkz. denetim raporu, madde 9-10: 2021-2026 arası 13
sembol/~7000 gün taramasında, zaten bilinen iki kategori dışında hiçbir
"gerçek" işlem gününde Volume=0 bulunamadı — ama bu, teorik olarak
imkansız olduğu ANLAMINA GELMEZ, yalnızca ampirik gözlem; asıl otorite her
zaman takvimdir, verinin İÇERİĞİ değil).

Bakım: Bu listeler YILLIK olarak güncellenmelidir. Desteklenmeyen bir yıl
için SESSİZCE tahmin YÜRÜTÜLMEZ — `expected_trading_sessions()` böyle bir
durumda `None` döner, çağıran taraf (`data_quality.py`) bunu açık bir
`TradingCalendarUnsupportedError`'a çevirir. 2027 ve sonrası BİLİNÇLİ
OLARAK henüz eklenmedi (şu an hiçbir gerçek backtest period'u gerektirmiyor,
bkz. `completed_history.SUPPORTED_BACKTEST_PERIODS`).
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

import pandas as pd

logger = logging.getLogger(__name__)

BIST_FULL_DAY_CLOSURES: dict[int, frozenset[date]] = {
    2021: frozenset(
        {
            date(2021, 1, 1),  # Yılbaşı
            date(2021, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
            date(2021, 5, 13),  # Ramazan Bayramı
            date(2021, 5, 14),  # Ramazan Bayramı
            date(2021, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
            date(2021, 7, 15),  # Demokrasi ve Milli Birlik Günü
            date(2021, 7, 20),  # Kurban Bayramı
            date(2021, 7, 21),  # Kurban Bayramı
            date(2021, 7, 22),  # Kurban Bayramı
            date(2021, 7, 23),  # Kurban Bayramı
            date(2021, 8, 30),  # Zafer Bayramı
            date(2021, 10, 29),  # Cumhuriyet Bayramı
            # 1 Mayıs 2021 Cumartesi'ye denk geldi — hafta sonu kuralıyla zaten kapsanıyor.
        }
    ),
    2022: frozenset(
        {
            date(2022, 5, 2),  # Ramazan Bayramı
            date(2022, 5, 3),  # Ramazan Bayramı
            date(2022, 5, 4),  # Ramazan Bayramı
            date(2022, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
            date(2022, 7, 11),  # Kurban Bayramı
            date(2022, 7, 12),  # Kurban Bayramı
            date(2022, 7, 15),  # Demokrasi ve Milli Birlik Günü
            date(2022, 8, 30),  # Zafer Bayramı
            # Yılbaşı, Ulusal Egemenlik, Emek Günü/Ramazan Arefesi, Cumhuriyet'in
            # kendi günü (29 Ekim) — hepsi 2022'de hafta sonuna denk geldi.
        }
    ),
    2023: frozenset(
        {
            date(2023, 4, 21),  # Ramazan Bayramı
            date(2023, 5, 1),  # Emek ve Dayanışma Günü
            date(2023, 5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
            date(2023, 6, 28),  # Kurban Bayramı
            date(2023, 6, 29),  # Kurban Bayramı
            date(2023, 6, 30),  # Kurban Bayramı
            date(2023, 8, 30),  # Zafer Bayramı
            # NOT: 8-14 Şubat 2023 (deprem sonrası olağanüstü kapanış/iptal)
            # BİLEREK burada DEĞİL — bkz. BIST_EXTRAORDINARY_CLOSURES /
            # BIST_CANCELLED_SESSIONS (modül docstring'i).
        }
    ),
    2024: frozenset(
        {
            date(2024, 1, 1),  # Yılbaşı
            date(2024, 4, 10),  # Ramazan Bayramı
            date(2024, 4, 11),  # Ramazan Bayramı
            date(2024, 4, 12),  # Ramazan Bayramı
            date(2024, 4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
            date(2024, 5, 1),  # Emek ve Dayanışma Günü
            date(2024, 6, 17),  # Kurban Bayramı
            date(2024, 6, 18),  # Kurban Bayramı
            date(2024, 6, 19),  # Kurban Bayramı
            date(2024, 7, 15),  # Demokrasi ve Milli Birlik Günü
            date(2024, 8, 30),  # Zafer Bayramı
            date(2024, 10, 29),  # Cumhuriyet Bayramı
        }
    ),
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

# HATA 3C-EX (26.08.2026): olağanüstü Borsa kararıyla TAM GÜN kapalı kalan
# günler — yıllık EK-3 tatil tablolarında YER ALMAZ, ayrı ad-hoc kaynaktan
# doğrulanır (bkz. modül docstring'i).
BIST_EXTRAORDINARY_CLOSURES: dict[int, frozenset[date]] = {
    2023: frozenset(
        {
            date(2023, 2, 9),  # Deprem sonrası olağanüstü kapanış
            date(2023, 2, 10),  # Deprem sonrası olağanüstü kapanış
            date(2023, 2, 13),  # Deprem sonrası olağanüstü kapanış
            date(2023, 2, 14),  # Deprem sonrası olağanüstü kapanış
        }
    ),
}

# HATA 3C-EX (26.08.2026): seans FİİLEN AÇILDI ama o güne ait TÜM işlemler
# Borsa'nın kararıyla resmi olarak İPTAL edildi — bkz. modül docstring'i.
# `normalize_bist_daily_sessions()` tarafından kullanılır (provider barı varsa düşürülür).
BIST_CANCELLED_SESSIONS: dict[int, frozenset[date]] = {
    2023: frozenset(
        {
            date(2023, 2, 8),  # Tüm işlemler resmi olarak iptal edildi (BİAŞ Yönetmeliği m.33)
        }
    ),
}

# Yalnızca belgeleme amaçlı DEĞİLDİR — `test_trading_calendar.py` her yarım
# günün `expected_trading_sessions()` çıktısında KALDIĞINI (full-day closure
# gibi çıkarılmadığını) ayrıca test eder (HATA 3C, madde 3).
BIST_HALF_DAY_SESSIONS: dict[int, frozenset[date]] = {
    2021: frozenset(
        {
            date(2021, 5, 12),  # Ramazan Bayramı Arefesi
            date(2021, 7, 19),  # Kurban Bayramı Arefesi
            date(2021, 10, 28),  # Cumhuriyet Bayramı Arefesi
        }
    ),
    2022: frozenset(
        {
            date(2022, 7, 8),  # Kurban Bayramı Arefesi
            date(2022, 10, 28),  # Cumhuriyet Bayramı Arefesi
        }
    ),
    2023: frozenset(
        {
            date(2023, 4, 20),  # Ramazan Bayramı Arefesi
            date(2023, 6, 27),  # Kurban Bayramı Arefesi
        }
    ),
    2024: frozenset(
        {
            date(2024, 4, 9),  # Ramazan Bayramı Arefesi
            date(2024, 10, 28),  # Cumhuriyet Bayramı Arefesi
        }
    ),
    2025: frozenset(
        {
            date(2025, 6, 5),  # Kurban Bayramı Arefesi
            date(2025, 10, 28),  # Cumhuriyet Bayramı Arefesi — HATA 3C denetiminde eklendi
            # (önceki sürümde eksikti; expected_trading_sessions() davranışını
            # HİÇ ETKİLEMİYORDU — yarım gün listesi filtrelemede kullanılmaz —
            # yalnızca dokümantasyon eksikliğiydi, resmi PDF ile doğrulanıp düzeltildi).
        }
    ),
    2026: frozenset(
        {
            date(2026, 3, 19),  # Ramazan Bayramı Arefesi
            date(2026, 5, 26),  # Kurban Bayramı Arefesi
            date(2026, 10, 28),  # Cumhuriyet Bayramı Arefesi
        }
    ),
}


def is_year_supported(year: int) -> bool:
    return year in BIST_FULL_DAY_CLOSURES


def is_cancelled_session(day: date) -> bool:
    """Seansın fiilen açılıp TÜM işlemlerin resmi kararla iptal edildiği gün mü?"""
    return day in BIST_CANCELLED_SESSIONS.get(day.year, frozenset())


def is_full_day_closure(day: date) -> bool:
    """Hafta sonu VEYA planlı resmi tatil VEYA olağanüstü kapanış VEYA iptal
    edilmiş seans — hiçbiri "expected" bir işlem günü DEĞİLDİR."""
    if day.weekday() >= 5:
        return True
    year = day.year
    if day in BIST_FULL_DAY_CLOSURES.get(year, frozenset()):
        return True
    if day in BIST_EXTRAORDINARY_CLOSURES.get(year, frozenset()):
        return True
    return is_cancelled_session(day)


class NonSessionClassification(str, Enum):
    """HATA 3D (26.08.2026) — `normalize_bist_daily_sessions()`'ın düşürdüğü
    bir tarihin PROVENANCE'ı. Sıra ÖNEMLİ (bkz. `classify_non_session_day`):
    daha SPESİFİK/ad-hoc-kaynaklı kategoriler (CANCELLED_SESSION,
    EXTRAORDINARY_CLOSURE), genel WEEKEND kuralının veya yıllık
    PLANNED_FULL_DAY_CLOSURE tablosunun ALTINDA "kaybolmamalı"."""

    WEEKEND = "WEEKEND"
    PLANNED_FULL_DAY_CLOSURE = "PLANNED_FULL_DAY_CLOSURE"
    EXTRAORDINARY_CLOSURE = "EXTRAORDINARY_CLOSURE"
    CANCELLED_SESSION = "CANCELLED_SESSION"


SESSION_NORMALIZATION_POLICY = "AUTHORITATIVE_NON_SESSION_DROP"


@dataclass(frozen=True)
class DroppedSession:
    date: date
    classification: str  # NonSessionClassification değeri (string — Pydantic/JSON serileştirme kolaylığı için)


@dataclass(frozen=True)
class SessionNormalizationResult:
    """`normalize_bist_daily_sessions()`'ın provenance çıktısı — backward-
    compatible: boşsa `dropped_sessions == []` (asla `None` değil)."""

    dropped_sessions: list[DroppedSession] = field(default_factory=list)
    policy: str = SESSION_NORMALIZATION_POLICY


def classify_non_session_day(day: date) -> NonSessionClassification | None:
    """`day` authoritative takvime göre bir "expected session DEĞİL" günüyse
    PROVENANCE'ını döner; `day` gerçekten expected bir session ise (yarım
    günler DAHİL — `HALF_DAY` hiçbir zaman bu fonksiyonun döndürdüğü bir
    kategori DEĞİLDİR) `None` döner.

    Sıra KASITLI: CANCELLED_SESSION ve EXTRAORDINARY_CLOSURE (ad-hoc,
    kaynağı ayrı araştırılan kararlar) ÖNCE kontrol edilir — aksi halde
    (ör. `is_full_day_closure`'ın basit OR mantığıyla) bu tarihler genel bir
    "tatil" gibi yanlış sınıflandırılıp provenance'ları kaybolabilirdi.
    """
    if is_cancelled_session(day):
        return NonSessionClassification.CANCELLED_SESSION
    if day in BIST_EXTRAORDINARY_CLOSURES.get(day.year, frozenset()):
        return NonSessionClassification.EXTRAORDINARY_CLOSURE
    if day in BIST_FULL_DAY_CLOSURES.get(day.year, frozenset()):
        return NonSessionClassification.PLANNED_FULL_DAY_CLOSURE
    if day.weekday() >= 5:
        return NonSessionClassification.WEEKEND
    return None


def normalize_bist_daily_sessions(
    df: pd.DataFrame, symbol: str | None = None, provider: str | None = None
) -> tuple[pd.DataFrame, SessionNormalizationResult]:
    """HATA 3D (26.08.2026) — TEK, PAYLAŞILAN authoritative non-session
    normalizasyon katmanı. Hem canlı `TechnicalAnalysisEngine` hem
    `BacktestEngine`/`WalkForwardOptimizer` (`completed_history.py` üzerinden)
    AYNI bu fonksiyonu çağırır — HATA 3C-EX'in `normalize_bist_daily_sessions()`'ı
    (yalnızca backtest'te kullanılıyordu, canlı motoru KAPSAMIYORDU) YERİNE
    geçer ve dört kategoriyi de (WEEKEND/PLANNED_FULL_DAY_CLOSURE/
    EXTRAORDINARY_CLOSURE/CANCELLED_SESSION) kapsar.

    KESİN KURAL: Karar YALNIZCA authoritative takvime (`classify_non_session_
    day`) dayanır — OHLC değerlerine veya Volume'a BAKILMAZ, "bu satır
    phantom'a benziyor" gibi bir çıkarım YAPILMAZ (bkz. HATA 3D denetim
    raporu, madde 9-10: Volume=0/OHLC-eşitliği asla karar kriteri değildir).
    Bir tarih authoritative takvimde "expected session" ise (yarım günler
    DAHİL), o tarihteki bar — içeriği ne olursa olsun — ASLA düşürülmez.

    Döner: `(normalized_df, result)` — `result.dropped_sessions` boşsa `[]`
    (hiçbir şey düşürülmediyse). Düşürülen HER tarih için tek bir INFO log
    satırı üretilir (indikatör/skor hesaplaması başına DEĞİL — bkz. modül
    docstring'i, "normalization aşamasında bir kez").
    """
    if df.empty:
        return df, SessionNormalizationResult(dropped_sessions=[])

    dropped: list[DroppedSession] = []
    keep_mask: list[bool] = []
    for ts in df.index:
        day = ts.date()
        classification = classify_non_session_day(day)
        if classification is None:
            keep_mask.append(True)
            continue
        keep_mask.append(False)
        dropped.append(DroppedSession(date=day, classification=classification.value))

    if dropped:
        logger.info(
            "BIST non-session bar normalization: symbol=%s provider=%s dropped=%s",
            symbol or "?",
            provider or "?",
            [(d.date.isoformat(), d.classification) for d in dropped],
        )

    return df[keep_mask], SessionNormalizationResult(dropped_sessions=dropped)


def session_normalization_to_dict(result: SessionNormalizationResult) -> dict:
    """`SessionNormalizationResult`'ı JSON/Pydantic-uyumlu, backward-compatible
    bir sözlüğe çevirir — hem `TechnicalAnalysis` hem backtest sonuç
    sözlükleri AYNI şemayı kullanır, provenance iki tarafta da birbirinden
    sapmaz. Boşsa `normalized_dropped_sessions: []` (asla `None` değil)."""
    return {
        "session_normalization_policy": result.policy,
        "normalized_dropped_sessions": [
            {"date": d.date.isoformat(), "classification": d.classification} for d in result.dropped_sessions
        ],
    }


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
