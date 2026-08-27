"""Backtest'e özel explicit-window veri hazırlama katmanı — HATA 3B/3C/3C-EX/
3D (26.08.2026), HATA 3E ile (26.08.2026) baştan tasarlandı, HATA 5A
(27.08.2026) ile üç-bölgeli (evidence/warm-up/simulation) modele geçirildi.

HATA 5A ÖZET — EXTERNAL 60-SESSION WARM-UP: Önceki sürüm, indicator warm-up'ı
(RSI/MACD/EMA/.../ROC göstergeleri için ayrılmış 60 geçmiş barlık proje
warm-up contract/buffer'ı, `INDICATOR_WARMUP_SESSIONS` — bu 60 değeri
"matematiksel minimum"/"bilimsel olarak gerekli" bir sayı DEĞİLDİR, bkz.
TEKNIK_ANALIZ_METODOLOJISI.md HATA 5A bölümü, "60'ın anlamı" notu) İSTENEN
BACKTEST PENCERESİNİN KENDİ İLK 60 SATIRINDAN
kesiyordu (`BacktestEngine`'de eski `df.iloc[MIN_HISTORY_DAYS:]`) — kullanıcı
"1y" istediğinde gerçek simülasyon, istenen pencerenin ilk ~3 ayını (60 işlem
günü) HİÇ görmeden başlıyordu. Gerçek 5-sembol/3-periyot ölçümle kanıtlandı:
bu, `total_return_pct`'in İŞARETİNİ BİLE değiştirebiliyordu. Çözüm: warm-up
artık `prepare_backtest_history()` içinde AYRICA, pencerenin DIŞINDAN fetch
edilir (`indicator_history` = warmup+simulation, `simulation_history` =
yalnız simulation) — bkz. `PreparedBacktestHistory`/`prepare_backtest_
history()` docstring'leri ve TEKNIK_ANALIZ_METODOLOJISI.md, HATA 5A bölümü.

**KRİTİK FINAL-BLOCKER DÜZELTMESİ** (pre-commit audit'te gerçek kodla
kanıtlandı): mandatory 60-session warm-up'ın continuity kontrolü, evidence
durumundan (`resolve_expected_start()`'ın döndürdüğü tarih) TAMAMEN
BAĞIMSIZ, HER ZAMAN `warmup_history_start`'a anchor edilir. Aksi halde
(`resolve_expected_start()`'ın döndürdüğü tarih hem crop hem continuity
anchor'ı için kullanılsaydı), warm-up'ın TAM BAŞINDAKİ bir gerçek boşluk,
evidence yoksa "muhtemelen kanıtsız" sanılıp SESSİZCE MASKELENİRDİ — gerçek
kodla (W1 eksik senaryosu) kanıtlandı.

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
    DataQualityError,
    check_data_quality,
    check_trading_day_continuity,
    previous_expected_sessions,
    validate_calendar_coverage,
)
from app.engines.technical.history_window import PRE_ROLL_DAYS, resolve_expected_start
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.completed_bars import filter_completed_daily_bars, latest_expected_completed_date
from app.services.market_data.trading_calendar import (
    EARLIEST_SUPPORTED_CALENDAR_DATE,
    SessionNormalizationResult,
    first_expected_session_on_or_after,
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

# HATA 5A (27.08.2026) — EXTERNAL 60-SESSION WARM-UP: önceki sürüm, indicator
# warm-up'ı (RSI/MACD/EMA/.../ROC göstergeleri için ayrılmış proje warm-up
# contract/buffer'ı — bilimsel/matematiksel bir minimum DEĞİL, bkz. aşağıdaki
# INDICATOR_WARMUP_SESSIONS tanımı) İSTENEN BACKTEST PENCERESİNİN KENDİ İLK
# 60 SATIRINI KESEREK elde ediyordu
# (`BacktestEngine`'de `df.iloc[MIN_HISTORY_DAYS:]`) — yani kullanıcı "1y"
# istediğinde gerçek simülasyon, istenen pencerenin İLK ~3 AYINI (60 işlem
# günü) hiç görmeden, o kadar geriden başlıyordu. Gerçek 5-sembol/3-periyot
# ölçümle kanıtlandı: bu, `total_return_pct`'in İŞARETİNİ BİLE
# DEĞİŞTİREBİLİYOR (bkz. TEKNIK_ANALIZ_METODOLOJISI.md, HATA 5A bölümü).
#
# Çözüm: warm-up, istenen pencerenin İÇİNDEN değil, DIŞINDAN (ayrıca fetch
# edilerek) sağlanır — üç AYRI bölge:
#   1. evidence   — yalnız leading-edge doğrulaması (advisory, PRE_ROLL_DAYS).
#   2. warm-up    — `warmup_history_start .. simulation_start-1`, YALNIZ
#                   `technical_score_series()`'e girer, P/L'e ASLA girmez.
#   3. simulation — `simulation_start .. target_end`, indicator+score+trade+
#                   P/L+equity+benchmark.
#
# `INDICATOR_WARMUP_SESSIONS` DEĞERİ (60) DEĞİŞMEDİ — yalnızca KONUMU
# (pencere içi → pencere dışı) düzeltildi.
INDICATOR_WARMUP_SESSIONS = 60


@dataclass(frozen=True)
class PreparedBacktestHistory:
    """`prepare_backtest_history()`'nin dönüş sözleşmesi (HATA 3E, HATA 5A ile genişletildi).

    `indicator_history`: `warmup_history_start .. target_end` — pre-roll
    KESİNLİKLE İÇERMEZ, ama mandatory 60-session warm-up'ı İÇERİR.
    `technical_score_series()`'in TEK girdisi budur.

    `simulation_history`: `simulation_start .. target_end` — `indicator_
    history`'nin bir ALT KÜMESİ (ayrı bir DataFrame, memory-view garantisi
    YOKTUR). `simulate()`'in TEK girdisi budur; warm-up satırları buraya
    HİÇBİR ZAMAN girmez.
    """

    indicator_history: pd.DataFrame
    simulation_history: pd.DataFrame

    requested_window_start: date
    simulation_start: date
    warmup_history_start: date
    indicator_warmup_sessions: int

    # Geriye dönük uyumluluk (HATA 3E'den): `actual_history_start` ANLAMI
    # DEĞİŞMEDİ — hâlâ "fiili analiz penceresinin ilk barı" demektir; o
    # pencere artık `simulation_history`'dir (HATA 5A'dan önce `history`
    # olan alandı). Mevcut API tüketicileri (Flutter) kırılmaz.
    actual_history_start: date
    actual_indicator_history_start: date

    history_validation_status: str
    backtest_data_as_of: date
    normalization: SessionNormalizationResult


def prepare_backtest_history(
    provider: MarketDataProvider,
    symbol: str,
    period: str,
    now: datetime | None = None,
) -> PreparedBacktestHistory:
    """Explicit `start`/`end` ile ham geçmişi çeker (Yahoo `period=` ARTIK
    KULLANILMAZ); TAMAMLANMAMIŞ ("bugünkü") barı çıkarır; authoritative
    takvime göre expected OLMAYAN hiçbir tarihteki bar'ı düşürür; mandatory
    60-session indicator warm-up'ını istenen simülasyon penceresinin
    DIŞINDA, ayrıca sağlar (HATA 5A).

    Raises:
        ValueError: `period`, `SUPPORTED_BACKTEST_PERIODS` içinde değilse.
        TradingCalendarUnsupportedError: İSTENEN pencere (`[target_start,
            target_end]`) VEYA mandatory warm-up aralığı (`[warmup_history_
            start, target_end]`) desteklenmeyen bir yıla değerse (FAIL-FAST,
            provider çağrılmadan ÖNCE — HİÇBİR ZAMAN authoritative takvimin
            sınırına KIRPILMAZ, evidence pre-roll'un aksine).
        DataQualityError (`TradingDayContinuityError` dahil): mandatory
            warm-up aralığındaki (`warmup_history_start .. target_end`) TEK
            bir eksik/beklenmeyen işlem günü bile HARD VETO'ya yol açar —
            evidence durumundan (`VERIFIED_PRE_WINDOW`/`LEADING_EDGE_
            UNVERIFIED`) TAMAMEN BAĞIMSIZ (bkz. aşağıdaki HATA 5A final
            blocker notu).
    """
    if period not in SUPPORTED_BACKTEST_PERIODS:
        raise ValueError(
            f"Desteklenmeyen backtest period'u: '{period}' — desteklenenler: "
            f"{sorted(SUPPORTED_BACKTEST_PERIODS)}"
        )

    target_end = latest_expected_completed_date(now)
    target_start = target_end - BACKTEST_PERIOD_DELTAS[period]

    # HATA 3E — REQUESTED WINDOW CALENDAR COVERAGE (değişmedi): provider'a
    # hiç gidilmeden, yalnızca [target_start, target_end] üzerinde fail-fast
    # doğrulama.
    validate_calendar_coverage(target_start, target_end)

    # `simulation_start`: target_start'ın KENDİSİ zaten bir expected session
    # değilse (hafta sonu/planlı tatil), ondan SONRAKİ ilk expected session.
    # FINAL PRE-COMMIT CLEANUP (27.08.2026): arama üst sınırı artık ARBITRARY
    # bir sabit (eski "14 gün yeter" correctness varsayımı) DEĞİL, isteğin
    # KENDİ authoritative-doğrulanmış (`validate_calendar_coverage` az önce
    # geçti) üst sınırı olan `target_end`'dir — `[target_start, target_end]`
    # zaten TAMAMEN desteklenen yıllarda olduğundan bu çağrı asla `None`
    # dönmeyi BEKLEMEZ (yalnızca teorik/defense-in-depth durum aşağıda ele alınır).
    simulation_start = first_expected_session_on_or_after(target_start, target_end)
    if simulation_start is None:
        raise DataQualityError(
            "NO_EXPECTED_SESSION_IN_REQUESTED_WINDOW",
            f"'{symbol}' için istenen pencerede ([{target_start.isoformat()}, "
            f"{target_end.isoformat()}]) hiç beklenen BIST işlem günü yok.",
        )

    # HATA 5A — EXACT 60-SESSION MANDATORY WARM-UP: calendar-day yaklaşık
    # DEĞİL, authoritative takvim üzerinden `simulation_start`'tan HEMEN
    # ÖNCEki tam 60 expected session. `simulation_start`'ın KENDİSİ bu 60'a
    # DAHİL DEĞİLDİR (off-by-one, `previous_expected_sessions` docstring'i).
    # Desteklenmeyen bir yıla taşarsa CLIP YAPILMAZ — deterministic failure
    # (`TradingCalendarUnsupportedError`), pre-roll'un aksine.
    warmup_history_start = previous_expected_sessions(simulation_start, INDICATOR_WARMUP_SESSIONS)[0]

    # Mandatory warm-up aralığı da (target_start'tan daha geriye taşıyabilir)
    # fail-fast kontrol edilir — provider'a gitmeden ÖNCE.
    validate_calendar_coverage(warmup_history_start, target_end)

    # Evidence pre-roll artık `warmup_history_start`'ın (target_start'ın
    # DEĞİL) öncesine anchor edilir — advisory, 15 takvim günü, desteklenmeyen
    # bir yıla taşarsa authoritative takvimin sınırına KIRPILIR (mandatory
    # warm-up'ın aksine).
    provider_start = max(warmup_history_start - timedelta(days=PRE_ROLL_DAYS), EARLIEST_SUPPORTED_CALENDAR_DATE)
    provider_end = target_end + timedelta(days=1)  # Yahoo `end` EXCLUSIVE — target_end'i dahil etmek için +1

    raw_history = provider.get_history(
        symbol, start=provider_start.isoformat(), end=provider_end.isoformat(), interval="1d"
    )
    completed_history = filter_completed_daily_bars(raw_history, now=now)
    normalized_history, normalization_result = normalize_bist_daily_sessions(
        completed_history, symbol=symbol, provider="yahoo_finance"
    )

    # HATA 5A FINAL BLOCKER FIX: evidence/status belirlemesi (VERIFIED_PRE_
    # WINDOW / LEADING_EDGE_UNVERIFIED) artık YALNIZCA `history_validation_
    # status` METADATA'sı içindir — mandatory warm-up continuity kontrolünün
    # alt sınırını ASLA belirlemez. Önceki tasarım hatası (pre-commit audit'te
    # gerçek kodla kanıtlandı): `resolve_expected_start()`'ın döndürdüğü
    # tarih, evidence yoksa `first_observed`'a kayabilir — bu tarih hem crop
    # hem continuity anchor'ı için kullanılırsa, mandatory warm-up'ın TAM
    # BAŞINDAKİ bir gerçek boşluk (ör. warmup_history_start'ın kendisi
    # provider'da yoksa) "muhtemelen kanıtsız" sanılıp SESSİZCE MASKELENİR.
    _, validation_status = resolve_expected_start(normalized_history, warmup_history_start)

    # `indicator_history` HER ZAMAN `warmup_history_start`'ta kırpılır —
    # evidence durumundan BAĞIMSIZ, asla ileri taşınmaz (mandatory, HATA 2C'nin
    # OPSİYONEL pre-roll'undan farklı). NOT: `.index.date` (vektörize) YERİNE
    # liste comprehension — tz-karışık/`object` dtype index'lerde güvenli
    # (`resolve_expected_start()` ile aynı desen).
    keep_mask = [ts.date() >= warmup_history_start for ts in normalized_history.index]
    indicator_history = normalized_history[keep_mask]

    # Continuity HER ZAMAN `warmup_history_start`'a anchor edilir — evidence
    # status'undan TAMAMEN BAĞIMSIZ. Mandatory warm-up aralığındaki (ki bu
    # aralık `[warmup_history_start, target_end]`'dir) TEK bir eksik/
    # beklenmeyen gün bile HARD VETO'dur.
    check_trading_day_continuity(indicator_history, symbol, now=now, expected_start=warmup_history_start)
    check_data_quality(indicator_history, symbol, min_history_days=INDICATOR_WARMUP_SESSIONS, now=now)

    sim_mask = [ts.date() >= simulation_start for ts in indicator_history.index]
    simulation_history = indicator_history[sim_mask]

    return PreparedBacktestHistory(
        indicator_history=indicator_history,
        simulation_history=simulation_history,
        requested_window_start=target_start,
        simulation_start=simulation_start,
        warmup_history_start=warmup_history_start,
        indicator_warmup_sessions=INDICATOR_WARMUP_SESSIONS,
        actual_history_start=simulation_history.index[0].date(),
        actual_indicator_history_start=indicator_history.index[0].date(),
        history_validation_status=validation_status.value,
        backtest_data_as_of=indicator_history.index[-1].date(),
        normalization=normalization_result,
    )
