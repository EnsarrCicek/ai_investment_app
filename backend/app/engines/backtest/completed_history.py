"""Backtest'e özel completed-session-only + continuity veri hazırlama
katmanı — HATA 3B (26.08.2026), genişletildi HATA 3C/3C-EX (26.08.2026).

HATA 3B denetiminde kanıtlandı: `BacktestEngine`/`WalkForwardOptimizer`,
`self._provider.get_history(symbol, period=period)`'i HİÇBİR filtre
uygulamadan doğrudan `technical_score_series()`/`simulate()`'e veriyordu.
Piyasa açıkken bu, Yahoo'nun hâlâ oluşmakta olan ("partial"/developing)
bugünkü günlük barının hem skor hesaplamasına HEM DE (HATA 3A'nın
execution modeli sayesinde) potansiyel olarak execution/terminal
mark-to-market'e sızmasına yol açıyordu — canlı ölçümle kanıtlandı
(GARAN/ASELS'te açık pozisyonun `unrealized_return_pct`'i dakikalar
içinde işaret bile değiştirebiliyordu).

KESİN SÖZLEŞME (kullanıcı kararı, 26.08.2026): Backtest, canlı/paper-trading
DEĞİLDİR — yalnızca TAMAMLANMIŞ günlük seanslar üzerinde çalışır
("COMPLETED_DAILY_ONLY"). Piyasa açıkken bugünün satırı (Open/High/Low/
Close/Volume — HİÇBİR alanı, "Open zaten sabit" gibi bir istisna dahi
YAPILMADAN) backtest'e hiç girmez. Bilinçli olarak REDDEDİLEN alternatif:
"partial günün Close'unu skordan çıkar ama Open'ını execution için kullan"
hibrit modeli — bu, historical backtest ile live/paper execution'ı
karıştırır; live/paper portföy ayrı, gelecekteki bir özelliktir.

HATA 3C (26.08.2026) — TRADING_SESSION_CONTINUITY: "Bugünü kullanma"
(HATA 3B) yeterli değil — GEÇMİŞTE olması gereken bir completed session
gerçekten mevcut mu sorusu AYRI bir denetim gerektiriyor. BIST'in resmi
takvimine göre beklenen ama provider'da bulunmayan bir işlem günü
(`MISSING_TRADING_SESSION`) VEYA takvime göre "expected" OLMAYAN bir günde
provider'ın açıklanamayan bir bar döndürmesi (`UNEXPECTED_TRADING_SESSION`)
varsa backtest HİÇ ÜRETİLMEZ (HARD VETO) — interpolasyon, önceki kapanışla
doldurma, "bir sonraki gözlemlenen satırı T+1 say" gibi hiçbir sessiz
düzeltme YAPILMAZ (bkz. `data_quality.check_trading_day_continuity`).

HATA 3C-EX (26.08.2026) — CANCELLED/EXTRAORDINARY SESSION: Planlı resmi
tatiller (`BIST_FULL_DAY_CLOSURES`) ve olağanüstü Borsa kararıyla tam gün
kapatılan günler (`BIST_EXTRAORDINARY_CLOSURES`) zaten "expected" sayılmaz.
Ayrı bir üçüncü durum: seans FİİLEN AÇILDI ama o güne ait TÜM işlemler
Borsa'nın kendi kararıyla RESMİ OLARAK İPTAL edildi (`BIST_CANCELLED_
SESSIONS`) — örnek: **08.02.2023**, 6 Şubat 2023 depremi sonrası devre
kesiciler tetiklenip piyasa saat 11:00'de durduruldu VE o gün gerçekleşen
TÜM işlemler Borsa İstanbul A.Ş. Yönetmeliği'nin "Emir ve İşlemlerin
İptali" başlıklı 33. maddesi uyarınca iptal edildi (kaynak: Anadolu
Ajansı, KAP duyurusunu doğrudan aktarıyor — 26.08.2026'da bağımsız
araştırmayla doğrulandı).

HATA 3D (26.08.2026) — AUTHORITATIVE NON-SESSION NORMALIZATION: HATA 3C-EX'in
`drop_cancelled_sessions()`'ı yalnızca CANCELLED_SESSION'ı kapsıyordu VE
yalnızca bu modülden (backtest) çağrılıyordu — canlı `TechnicalAnalysisEngine`
KAPSAM DIŞIYDI. Kanıtlandı ki Yahoo, PLANLI tam-gün kapanışlarda (yıllık
tatil tablosunda olan günler) da ARA SIRA phantom bar döndürebiliyor —
en şiddetli örnek: 27-28-29 Mayıs 2026 (Kurban Bayramı), BIST100'ün
TAMAMINDA (`Open=High=Low=Close=`önceki kapanış, `Volume=0`). Bu YÜZDEN
`drop_cancelled_sessions()` YERİNE, dört kategoriyi de (WEEKEND/PLANNED_
FULL_DAY_CLOSURE/EXTRAORDINARY_CLOSURE/CANCELLED_SESSION) kapsayan TEK,
PAYLAŞILAN `trading_calendar.normalize_bist_daily_sessions()` kullanılıyor
— hem bu modül (backtest) HEM `TechnicalAnalysisEngine` (canlı) AYNI
fonksiyonu çağırır. Karar YALNIZCA authoritative takvime dayanır — OHLC/
Volume değerlerine bakılarak "phantom'a benziyor" çıkarımı YAPILMAZ.
Düşürülen her tarihin provenance'ı (`SessionNormalizationResult.
dropped_sessions`) sonuca şeffaf şekilde eklenir — bkz. `backtest_data_as_of`
yanındaki `session_normalization_policy`/`normalized_dropped_sessions`.

Normalizasyon sırası (her biri kendi HATA numarasıyla etiketli):
    raw provider history
    ↓
    completed-session filter              [HATA 3B — filter_completed_daily_bars]
    ↓
    authoritative non-session drop        [HATA 3D — normalize_bist_daily_sessions, WEEKEND/PLANNED/EXTRAORDINARY/CANCELLED hepsi]
    ↓
    session continuity validation         [HATA 3C — check_trading_day_continuity, defense-in-depth]
    ↓
    check_data_quality                    [MIN_HISTORY_DAYS dahil, NORMALIZE EDİLMİŞ seri üzerinde]
    ↓
    technical_score_series / simulate NEXT_SESSION_OPEN   [HATA 3A]

Bu modül, yukarıdaki TÜM adımları TEK bir yerde birleştirir — üç ayrı
canlı giriş noktasının (`BacktestEngine.run()`, `BacktestEngine.
compare_strategies()`, `WalkForwardOptimizer.run()`) aynı mantığı
kopyala-yapıştır ile birbirinden bağımsız (ve zamanla birbirinden
sapabilecek) şekilde tekrarlamasını önler. `MIN_HISTORY_DAYS` kontrolü
RAW history üzerinde DEĞİL, TAM NORMALİZE EDİLMİŞ seri üzerinde çalışır.
`check_trading_day_continuity`'nin `missing`/`unexpected` kontrolleri
normalizasyondan SONRA da HÂLÂ çalışır (defense-in-depth — normalizasyonu
atlayan varsayımsal bir gelecekteki caller'a karşı, bkz. HATA 3C).

Period sözleşmesi (HATA 3C, madde 1): `SUPPORTED_BACKTEST_PERIODS` tek,
paylaşılan bir sabittir — API katmanına AYRI bir whitelist eklenmedi;
`prepare_backtest_history()` bu tek sabite karşı doğrular ve desteklenmeyen
bir `period` için düz bir `ValueError` fırlatır — mevcut proje-geneli
`except ValueError as exc: raise HTTPException(422, str(exc))` deseni
(bkz. `api/backtest.py`) bunu otomatik olarak 422'ye çevirir, API
route'larında hiçbir değişiklik GEREKMEDİ. Üç motor da (`BacktestEngine.
run/compare_strategies`, `WalkForwardOptimizer.run`) bu tek fonksiyonu
çağırdığından, doğrudan bir script'ten API'yi atlayarak çağrılsalar bile
aynı korumaya (defense-in-depth) tabidirler.
"""

from datetime import date, datetime

import pandas as pd

from app.engines.technical.data_quality import check_data_quality, check_trading_day_continuity
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.services.market_data.trading_calendar import SessionNormalizationResult, normalize_bist_daily_sessions

# HATA 3C (26.08.2026): koddaki TEK gerçek period sözleşmesi. Gerçek
# caller'ların (Flutter Strategy Lab: 6mo/1y/2y/3y/5y; ana Backtest sekmesi:
# her zaman 2y; WalkForwardOptimizer varsayılanı: 3y — dormant, Flutter
# çağıranı yok) hiçbiri bu setin dışına çıkmıyor (denetimde doğrulandı).
# `max`/`10y`/`ytd`/arbitrary bir değer artık API'den yfinance'e sessizce
# iletilmez.
SUPPORTED_BACKTEST_PERIODS = frozenset({"6mo", "1y", "2y", "3y", "5y"})


def prepare_backtest_history(
    provider: MarketDataProvider,
    symbol: str,
    period: str,
    min_history_days: int,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, date, SessionNormalizationResult]:
    """Ham geçmişi çeker; TAMAMLANMAMIŞ ("bugünkü") barı çıkarır; authoritative
    takvime göre expected OLMAYAN (hafta sonu/planlı tatil/olağanüstü kapanış/
    iptal edilmiş seans) hiçbir tarihteki bar'ı — içeriğine bakmadan — düşürür;
    BIST işlem-günü sürekliliğini doğrular; kalite kontrolünü NORMALİZE
    EDİLMİŞ seri üzerinde yapar.

    Döner: `(normalized_history, backtest_data_as_of, normalization_result)`
    — `backtest_data_as_of`, backtest'in fiilen hesaba kattığı EN SON
    tamamlanmış günün tarihidir; `normalization_result.dropped_sessions`
    düşürülen her tarihin provenance'ını (`classification`) taşır — boşsa
    `[]` (hiçbir şey düşürülmediyse).

    Raises:
        ValueError: `period`, `SUPPORTED_BACKTEST_PERIODS` içinde değilse.
        DataQualityError (`TradingDayContinuityError` dahil): eksik/
            beklenmeyen işlem günü veya diğer kalite kontrolleri başarısız
            olursa.
        TradingCalendarUnsupportedError: kontrol aralığındaki bir yıl
            için resmi takvim tanımlı değilse (ör. 2027 ve sonrası, henüz
            eklenmedi).
    """
    if period not in SUPPORTED_BACKTEST_PERIODS:
        raise ValueError(
            f"Desteklenmeyen backtest period'u: '{period}' — desteklenenler: "
            f"{sorted(SUPPORTED_BACKTEST_PERIODS)}"
        )

    raw_history = provider.get_history(symbol, period=period)
    completed_history = filter_completed_daily_bars(raw_history, now=now)
    normalized_history, normalization_result = normalize_bist_daily_sessions(
        completed_history, symbol=symbol, provider="yahoo_finance"
    )
    check_trading_day_continuity(normalized_history, symbol, now=now)
    check_data_quality(normalized_history, symbol, min_history_days=min_history_days, now=now)
    backtest_data_as_of = normalized_history.index[-1].date()
    return normalized_history, backtest_data_as_of, normalization_result
