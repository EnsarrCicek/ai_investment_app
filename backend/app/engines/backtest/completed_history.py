"""Backtest'e özel explicit-window veri hazırlama katmanı — HATA 3B/3C/3C-EX/
3D (26.08.2026), HATA 3E ile (26.08.2026) baştan tasarlandı.

HATA 3B denetiminde kanıtlandı: `BacktestEngine`/`WalkForwardOptimizer`,
`self._provider.get_history(symbol, period=period)`'i HİÇBİR filtre
uygulamadan doğrudan `technical_score_series()`/`simulate()`'e veriyordu.
KESİN SÖZLEŞME: Backtest, canlı/paper-trading DEĞİLDİR — yalnızca
TAMAMLANMIŞ günlük seanslar üzerinde çalışır ("COMPLETED_DAILY_ONLY").

HATA 3C/3C-EX/3D: BIST'in resmi takvimine göre beklenen ama provider'da
bulunmayan bir işlem günü VEYA takvime göre "expected" OLMAYAN bir günde
(hafta sonu/planlı tatil/olağanüstü kapanış/iptal edilmiş seans) provider'ın
açıklanamayan bir bar döndürmesi durumları — bkz. `data_quality.py`,
`trading_calendar.py`.

HATA 3E (26.08.2026) — BACKTEST LEADING-EDGE / EXPLICIT WINDOW: Önceki
sürüm `provider.get_history(symbol, period=period)` çağırıyordu — Yahoo'nun
`period=` string'i SUNUCU TARAFINDA opak şekilde yorumlanıyor (yfinance
kaynağı: `params={"range": period}`, istemci tarafında `relativedelta`/sabit
gün sayısıyla YENİDEN HESAPLANMIYOR) VE `check_trading_day_continuity()`
`expected_start` PARAMETRESİ HİÇ VERİLMEDEN çağrılıyordu — bu ikisinin
BİRLEŞİMİ, sentetik kanıtla doğrulandı: provider'ın istenen pencerenin TAM
BAŞINDAKİ günleri (T0, T1) sessizce düşürmesi durumunda `prepare_backtest_
history()` PASS veriyordu (canlı motorun HATA 2B/2C ile çözdüğü kör noktanın
BİREBİR AYNISI, backtest'e hiç taşınmamıştı).

Çözüm — canlı `history_window.py`/`resolve_expected_start()` (HATA 2C) ile
AYNI evidence semantiği, backtest'in KENDİ period sözleşmesine (`period` →
`target_start`/`target_end`) uyarlanarak:

    period validation (SUPPORTED_BACKTEST_PERIODS = frozenset(BACKTEST_PERIOD_DELTAS))
    ↓
    target_end = latest_expected_completed_date(now)          [COMPLETED_DAILY_ONLY'nin KENDİ as-of'u]
    ↓
    target_start = target_end - BACKTEST_PERIOD_DELTAS[period]
    ↓
    validate_calendar_coverage(target_start, target_end)       [HATA 3E — FAIL-FAST, provider'a gitmeden ÖNCE]
    ↓
    provider_start = max(target_start - PRE_ROLL_DAYS, EARLIEST_SUPPORTED_CALENDAR_DATE)   [advisory clip]
    ↓
    provider_end = target_end + 1 gün                          [Yahoo end EXCLUSIVE]
    ↓
    provider.get_history(symbol, start=provider_start, end=provider_end)   [explicit — period= YOK]
    ↓
    filter_completed_daily_bars                                [3B, defense-in-depth]
    ↓
    normalize_bist_daily_sessions                               [3D — pre-roll DAHİL tüm seri üzerinde]
    ↓
    resolve_expected_start(normalized, target_start)            [2C parity — AYNI, kopyalanmamış fonksiyon]
    ↓
    crop: analysis_history = normalized[index.date >= expected_start]   [pre-roll BURADAN SONRA HİÇBİR
                                                                          şeye — indikatöre, warm-up'a,
                                                                          walk-forward split'e — GİRMEZ]
    ↓
    check_trading_day_continuity(analysis_history, expected_start=expected_start)   [3C, defense-in-depth]
    ↓
    check_data_quality(analysis_history, min_history_days=...)
    ↓
    technical_score_series / simulate NEXT_SESSION_OPEN         [3A]

**"target_end = now.date()" DEĞİL, "target_end = latest_expected_completed_
date(now)" olması KASITLI (HATA 3E, "window anchor" denetimi):** `COMPLETED_
DAILY_ONLY` sözleşmesi zaten veri as-of'unu bu fonksiyonla tanımlıyor —
window'un END'i başka bir referans (wall-clock "bugün") kullanırsa, cutoff
(18:30 TSİ) öncesi/sonrası aynı istek 1 gün kayan bir pencere üretirdi. Cutoff
SONRASINDA `target_end`'in bir gün ilerlemesi (yeni bir completed session
mevcut olduğunda) bir hata DEĞİLDİR — BEKLENEN, istenen rolling-window
davranışıdır.

**Requested window calendar coverage (`validate_calendar_coverage`) İLE
pre-roll calendar coverage AYRI, KASITLI OLARAK FARKLI davranır:**
`[target_start, target_end]` (fiilen istenen, skorlanacak analiz penceresi)
desteklenmeyen bir yıla değerse **FAIL-CLOSED** (`TradingCalendarUnsupportedError`,
provider'a HİÇ gidilmez) — bu, kullanıcının/sistemin AÇIKÇA istediği bir
şeyin doğrulanamamasıdır. Pre-roll ise yalnızca ADVISORY bir evidence
bölgesidir (`resolve_expected_start`, "bu sembol target_start'tan önce zaten
işlem görüyor muydu?") — desteklenmeyen bir yıla taşarsa authoritative
takvimin sınırına KIRPILIR (`EARLIEST_SUPPORTED_CALENDAR_DATE`), kırpılmış
bölgede kanıt bulunamazsa mevcut `LEADING_EDGE_UNVERIFIED` yoluna (YENİ bir
hata tipi İCAT EDİLMEDEN) doğal olarak düşer — advisory bir "kanıt arayamadık"
durumu, authoritative bir "bilmediğimiz bir aralığı doğru kabul ettik"
durumundan EPİSTEMİK OLARAK FARKLIDIR.

**Yeni-listing tahmini YAPILMAZ:** `resolve_expected_start()`'ın `LEADING_
EDGE_UNVERIFIED` dalı hiçbir gün-farkı eşiği (60 gün vb.) KULLANMAZ — yalnızca
pre-roll'da GERÇEK bir bar bulunup bulunmadığına bakar. `Yahoo firstTradeDate`
kullanılmaz, `Asset.listing_date` migration'ı yapılmaz (önceki denetimlerde
zaten kesinleşmişti).

Provenance/şeffaflık: `PreparedBacktestHistory.requested_window_start`
(`target_start`), `.actual_history_start` (fiili analiz penceresine giren
İLK barın tarihi) ve `.history_validation_status` (`VERIFIED_PRE_WINDOW` |
`LEADING_EDGE_UNVERIFIED`, live'la AYNI string'ler) — "5y istendi ama elimizde
gerçekte yalnızca 17 aylık gözlemlenen history var" gibi bir durum sessizce
KAYBOLMAZ; `period` alanı (kullanıcının GERÇEKTEN istediği) asla geriye
yazılmaz.

`PreparedBacktestHistory` (tuple değil, typed dataclass): önceki 3-tuple
(`df, backtest_data_as_of, normalization_result`) HATA 3E ile 6 alana çıktığı
için pozisyonel tuple okunaksız/hataya açık hale gelirdi — küçük, frozen bir
dataclass her caller'da isimle erişim sağlar.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta

from app.engines.technical.data_quality import (
    check_data_quality,
    check_trading_day_continuity,
    validate_calendar_coverage,
)
from app.engines.technical.history_window import PRE_ROLL_DAYS, resolve_expected_start
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.completed_bars import filter_completed_daily_bars, latest_expected_completed_date
from app.services.market_data.trading_calendar import (
    EARLIEST_SUPPORTED_CALENDAR_DATE,
    SessionNormalizationResult,
    normalize_bist_daily_sessions,
)

# HATA 3E (26.08.2026): TEK source-of-truth — `SUPPORTED_BACKTEST_PERIODS`
# bu mapping'in key'lerinden TÜRETİLİR, ayrı elle-bakımlı bir set OLARAK
# TUTULMAZ. Bir period'un delta'ya eklenip whitelist'e eklenmemesi (veya
# tersi) artık yapısal olarak İMKANSIZDIR. Gerçek caller'ların (Flutter
# Strategy Lab: 6mo/1y/2y/3y/5y; ana Backtest sekmesi: her zaman 2y;
# WalkForwardOptimizer varsayılanı: 3y — dormant, Flutter çağıranı yok)
# hiçbiri bu setin dışına çıkmıyor (denetimde doğrulandı).
BACKTEST_PERIOD_DELTAS: dict[str, relativedelta] = {
    "6mo": relativedelta(months=6),
    "1y": relativedelta(years=1),
    "2y": relativedelta(years=2),
    "3y": relativedelta(years=3),
    "5y": relativedelta(years=5),
}
SUPPORTED_BACKTEST_PERIODS = frozenset(BACKTEST_PERIOD_DELTAS)


@dataclass(frozen=True)
class PreparedBacktestHistory:
    """`prepare_backtest_history()`'nin dönüş sözleşmesi (HATA 3E).

    `history`: pre-roll KESİNLİKLE İÇERMEZ — `expected_start`'tan itibaren
    crop edilmiş, normalize edilmiş, continuity/kalite kontrolünden geçmiş
    "analysis history"nin KENDİSİ. `BacktestEngine`/`WalkForwardOptimizer`
    yalnızca bunu görür.
    """

    history: pd.DataFrame
    backtest_data_as_of: date
    normalization: SessionNormalizationResult
    requested_window_start: date
    actual_history_start: date
    history_validation_status: str


def prepare_backtest_history(
    provider: MarketDataProvider,
    symbol: str,
    period: str,
    min_history_days: int,
    now: datetime | None = None,
) -> PreparedBacktestHistory:
    """Explicit `start`/`end` ile ham geçmişi çeker (Yahoo `period=` ARTIK
    KULLANILMAZ); TAMAMLANMAMIŞ ("bugünkü") barı çıkarır; authoritative
    takvime göre expected OLMAYAN hiçbir tarihteki bar'ı düşürür; canlı HATA
    2C ile AYNI `resolve_expected_start()` ile pre-roll evidence'ını
    çözümler; BIST işlem-günü sürekliliğini VE kalite kontrolünü yalnızca
    fiili analiz penceresi (`expected_start` sonrası) üzerinde yapar.

    Raises:
        ValueError: `period`, `SUPPORTED_BACKTEST_PERIODS` içinde değilse.
        TradingCalendarUnsupportedError: İSTENEN pencere (`[target_start,
            target_end]`) desteklenmeyen bir yıla değerse (FAIL-FAST, provider
            çağrılmadan ÖNCE) VEYA fiili analiz penceresinde (defense-in-depth)
            bir yıl desteklenmiyorsa.
        DataQualityError (`TradingDayContinuityError` dahil): eksik/
            beklenmeyen işlem günü veya diğer kalite kontrolleri (ör.
            `INSUFFICIENT_HISTORY` — boş/çok kısa analiz penceresi dahil)
            başarısız olursa.
    """
    if period not in SUPPORTED_BACKTEST_PERIODS:
        raise ValueError(
            f"Desteklenmeyen backtest period'u: '{period}' — desteklenenler: "
            f"{sorted(SUPPORTED_BACKTEST_PERIODS)}"
        )

    target_end = latest_expected_completed_date(now)
    target_start = target_end - BACKTEST_PERIOD_DELTAS[period]

    # HATA 3E — REQUESTED WINDOW CALENDAR COVERAGE: provider'a hiç gidilmeden,
    # yalnızca [target_start, target_end] üzerinde fail-fast doğrulama.
    # Bilerek `resolve_expected_start`'tan/observed history'den BAĞIMSIZ —
    # aksi halde `LEADING_EDGE_UNVERIFIED` dalı `expected_start`'ı ileri
    # taşıyıp `target_start`'ın desteklenmeyen bir yılda kaldığını
    # GİZLEYEBİLİRDİ (HATA 3E final audit'inde sentetik olarak kanıtlandı).
    validate_calendar_coverage(target_start, target_end)

    # Pre-roll YALNIZCA advisory bir evidence bölgesidir — desteklenmeyen bir
    # yıla taşarsa authoritative takvimin ilk desteklenen gününe KIRPILIR
    # (yeni bir hata tipi İCAT EDİLMEZ; kırpılmış bölgede kanıt bulunamazsa
    # zaten mevcut LEADING_EDGE_UNVERIFIED yoluna düşer).
    provider_start = max(target_start - timedelta(days=PRE_ROLL_DAYS), EARLIEST_SUPPORTED_CALENDAR_DATE)
    provider_end = target_end + timedelta(days=1)  # Yahoo `end` EXCLUSIVE — target_end'i dahil etmek için +1

    raw_history = provider.get_history(
        symbol, start=provider_start.isoformat(), end=provider_end.isoformat(), interval="1d"
    )
    completed_history = filter_completed_daily_bars(raw_history, now=now)
    normalized_history, normalization_result = normalize_bist_daily_sessions(
        completed_history, symbol=symbol, provider="yahoo_finance"
    )

    # HATA 2C parity: backtest, live'ın KULLANDIĞI AYNI fonksiyonu çağırır —
    # backtest'e özel bir kopyası YAZILMADI. Phantom bir pre-roll barı (HATA
    # 3D) normalizasyondan SONRA geldiği için evidence olarak SAYILAMAZ.
    expected_start, validation_status = resolve_expected_start(normalized_history, target_start)

    # Pre-roll barları BURADAN SONRA hiçbir hesaplamaya (continuity, kalite,
    # skor, warm-up, walk-forward split) GİRMEZ.
    # NOT: `.index.date` (vektörize) YERİNE liste comprehension kullanılır —
    # `resolve_expected_start()` ile AYNI desen (`history_window.py`):
    # tz-karışık/`object` dtype bir index (ör. testlerde tz-naive bir partial
    # satırın tz-aware bir seriyle `pd.concat` edilmesi) `.index.date`'i
    # `AttributeError` ile KIRABİLİR, `ts.date()` her koşulda güvenlidir.
    keep_mask = [ts.date() >= expected_start for ts in normalized_history.index]
    analysis_history = normalized_history[keep_mask]

    check_trading_day_continuity(analysis_history, symbol, now=now, expected_start=expected_start)
    check_data_quality(analysis_history, symbol, min_history_days=min_history_days, now=now)

    return PreparedBacktestHistory(
        history=analysis_history,
        backtest_data_as_of=analysis_history.index[-1].date(),
        normalization=normalization_result,
        requested_window_start=target_start,
        actual_history_start=analysis_history.index[0].date(),
        history_validation_status=validation_status.value,
    )
