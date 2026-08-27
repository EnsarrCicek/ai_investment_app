"""Breakout event timeline — HATA 4B (27.08.2026).

HATA 4A denetimi, `breakout.py`'deki `detect_breakout()`/`confirm_breakout()`/
`check_retest()` üçlüsünün `TechnicalAnalysisEngine._compute_enrichment()`
içinde HER GÜN yeniden, `index=len(df)-1` ("bugün") ile çağrıldığını kanıtladı
— bu, `confirm_breakout()`'un ihtiyaç duyduğu `confirm_bars` kadar GELECEK
barın hiçbir zaman "bugün"ün ÖTESİNDE var olamayacağı anlamına gelir, yani
`confirmed` DAİMA `None` kalır ve `STRONG_BULLISH_INITIATION` (dolayısıyla
`notify_if_new_opportunity()`) production'da asla erişilemez. Kök neden bir
look-ahead LEAK değil, tam tersi: event'in `event_at`'ının her çağrıda
"bugün"e yeniden ANKORLANMASI (event lifecycle/state persistence yokluğu).

Bu modül, o event'i STATELESS bir zaman çizelgesi olarak yeniden inşa eder —
Firestore'da hiçbir şey PERSIST ETMEDEN (bkz. HATA 4B final contract audit'i):
her çağrıda tüm geçmiş, üç aşamalı bir state machine ile TEK GEÇİŞTE yeniden
taranır (`build_breakout_timeline`), `event_at`/`known_at` ayrımı her aşamada
(confirmation, retest) açıkça korunur, ve `select_live_breakout_event()`
"bugün" için gösterilecek TEK event'i seçer.

Kesin kontrat (HATA 4B audit turlarında gerçek kodla/gerçek BIST verisiyle
doğrulandı):

1. BREAKOUT = TRANSITION, state değil. Bir close'un bir seviyenin ÜSTÜNDE
   KALMASI event üretmez; yalnız seviyeyi YENİ GEÇMESİ (`prev<=level<curr`)
   üretir. Aksi halde bir levelin üstünde 5 gün kalmak 5 ayrı event üretirdi.

2. STRICT CAUSAL ZONE: T günündeki bir event için kullanılan zone, YALNIZCA
   `T-1`'e kadar bilinen swing point'lerden (`known_at = point.index +
   right_bars <= T-1`) ve `ATR[T-1]` ile kurulur — `T` veya sonrasının hiçbir
   bilgisi zone inşasına giremez (aksi halde ileride oluşacak volatilite
   geçmişteki zone sınırlarını/breakout tespitini değiştirebilir — HATA 4B
   audit'inde gerçek kodla kanıtlandı: aynı iki swing point, düşük ATR'de
   ayrı iki zone, yüksek ATR'de TEK birleşmiş zone oluşturabiliyor).

3. ATR AYRIMI: zone clustering ATR'si (`ATR[T-1]`) ile breakout GÜCÜ ATR'si
   (`ATR[T]`) FARKLI şeylerdir — ikincisi T kapanışı itibarıyla zaten bilinen
   (dolayısıyla causal) bir değerdir, zone inşasına KARIŞTIRILMAZ.

4. FROZEN SNAPSHOT: event T'de oluştuğunda `level`/`zone_snapshot` DONDURULUR
   — confirmation (T+1..T+3) ve retest (confirmed_at+1..+10) aşamalarında
   zone YENİDEN CLUSTER EDİLMEZ, yalnız bu dondurulmuş değerler kullanılır.

5. DIRECTIONAL SCAN: eski `nearest_zone()`'un tip-agnostik ("fiyata en yakın
   TEK zone, tipi ne olursa olsun") seçimi breakout tespiti için KULLANILMAZ
   (gerçek false-negative kanıtlandı: fiyat resistance'ı kırmışken en yakın
   support seçilip kırılım hiç görülmeyebiliyordu). Bullish tespit yalnız
   RESISTANCE zone'ları, bearish yalnız SUPPORT zone'ları tarar. Aynı gün
   aynı yönde birden fazla zone kırılırsa (gerçek BIST verisinde gözlemlendi,
   nadir ama gerçek), en DIŞTAKİ (bullish: en yüksek `zone.high`, bearish: en
   düşük `zone.low`) "dominant" event olarak seçilir, diğerleri o gün için
   bastırılır (v1 kapsamı — ayrı "secondary" event listesi YOK).

6. EVENT IDENTITY: `event_index` (DataFrame pozisyonu, yalnız dahili
   hesaplama için) ile `event_at` (takvim tarihi, kalıcı/karşılaştırılabilir
   kimlik) AYRI alanlardır. `event_id = f"{symbol}:{direction}:{event_at}"`
   — zone'un float sınırları identity'ye DAHİL DEĞİLDİR (zone clustering
   günden güne hafifçe kayabilir; `zone_snapshot` yalnız açıklama/UI amaçlı).

Confirmation/retest state modelleri, `MAX_EVENT_AGE_SESSIONS`, live-selection
önceliği ve eski (`BreakoutEvent.confirmed`/`retest_held`) API'ye mapping —
hepsi HATA 4B final contract audit'lerinde satır satır kesinleştirildi (bkz.
TEKNIK_ANALIZ_METODOLOJISI.md, HATA 4B bölümü).

Performans: naif "her T için swing tespitini yeniden çalıştır" yaklaşımı 5
yıllık (1254 bar) bir seri için ~98 SANİYE sürüyor — kullanılamaz. Bu modül,
`find_swing_points()`'in `i` için penceresinin sabit `[i-left, i+right]`
olduğunu (asla `i+right`'ın ÖTESİNE bakmadığını) kullanarak swing tespitini
VE ATR serisini TEK SEFERDE (tüm df üzerinde) hesaplar, sonra her `T` için
yalnızca `known_at<=T-1` olan noktaları FİLTRELER — bu, per-T yeniden
hesaplamayla MATEMATİKSEL OLARAK KANITLANMIŞ ŞEKİLDE eşdeğerdir (HATA 4B
audit'i, sentetik + gerçek THYAO verisiyle uçtan uca event-timeline parity:
189/189 ve tam alan bazında birebir eşitlik) ve ~340 kat daha hızlıdır
(~5y için ~290ms).
"""

from dataclasses import dataclass
from datetime import date as date_type
from enum import Enum

import pandas as pd

from app.engines.technical import indicators as ind
from app.engines.technical.breakout import BreakoutEvent
from app.engines.technical.market_structure import find_swing_points
from app.engines.technical.support_resistance import SRZone, build_zones

LEFT_BARS = 5
RIGHT_BARS = 5
CONFIRM_BARS = 3
RETEST_BARS = 10
MAX_EVENT_AGE_SESSIONS = 15


class ConfirmationState(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"


class RetestState(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class BreakoutTimelineEvent:
    event_id: str
    symbol: str
    direction: str  # "BULLISH" / "BEARISH"

    event_index: int  # DataFrame pozisyonu -- yalnız dahili hesaplama için
    event_at: date_type  # takvim tarihi -- kalıcı kimlik

    level: float  # dondurulmuş kırılım seviyesi (zone.high veya zone.low)
    zone_snapshot: SRZone  # yalnız açıklama/UI, identity'ye DAHİL DEĞİL
    zone_known_at: int  # zone'un hangi bar'a kadarki (T-1) veriyle kurulduğu
    breakout_strength_atr: float  # ATR[T] ile hesaplanan, zone ATR'sinden AYRI

    confirmation_state: str  # ConfirmationState değeri
    confirmed_at: int | None
    invalidated_at: int | None

    retest_state: str | None  # RetestState değeri, confirmation PENDING/INVALIDATED ise None
    retest_event_at: int | None  # ilk dokunuş bar'ı
    retest_known_at: int | None  # HELD/FAILED/EXPIRED kesinleştiği bar
    retest_deadline: int | None  # confirmed_at + RETEST_BARS

    resolved_at: int | None  # terminal state'e ulaşıldığı bar (açık event'lerde None)


def build_breakout_timeline(
    df: pd.DataFrame,
    symbol: str,
    left_bars: int = LEFT_BARS,
    right_bars: int = RIGHT_BARS,
    confirm_bars: int = CONFIRM_BARS,
    retest_bars: int = RETEST_BARS,
) -> list[BreakoutTimelineEvent]:
    """Verilen (zaten completed-daily-only + BIST-3D-normalize edilmiş) `df`
    üzerinde, sözleşmedeki 6 ilkeyi uygulayarak TAM breakout event zaman
    çizelgesini tek geçişte inşa eder. Stateless — hiçbir şey persist etmez,
    her çağrıda `df`'in izin verdiği kadarını yeniden üretir."""
    close = df["Close"]
    n = len(df)
    if n < left_bars + right_bars + 2:
        return []

    atr_series = ind.atr(df)
    all_points = find_swing_points(df, left_bars=left_bars, right_bars=right_bars)

    candidates: list[tuple[int, str, SRZone]] = []
    for t in range(1, n):
        atr_t_minus_1 = float(atr_series.iloc[t - 1]) if not pd.isna(atr_series.iloc[t - 1]) else 0.0
        if atr_t_minus_1 <= 0:
            continue
        known_points = [p for p in all_points if p.index + right_bars <= t - 1]
        if not known_points:
            continue
        zones = build_zones(known_points, atr=atr_t_minus_1)

        prev_close, curr_close = float(close.iloc[t - 1]), float(close.iloc[t])
        bullish = [z for z in zones if z.type == "RESISTANCE" and prev_close <= z.high < curr_close]
        bearish = [z for z in zones if z.type == "SUPPORT" and prev_close >= z.low > curr_close]

        if bullish:
            candidates.append((t, "BULLISH", max(bullish, key=lambda z: z.high)))
        if bearish:
            candidates.append((t, "BEARISH", min(bearish, key=lambda z: z.low)))

    events: list[BreakoutTimelineEvent] = []
    for event_index, direction, zone in candidates:
        level = zone.high if direction == "BULLISH" else zone.low
        atr_t = float(atr_series.iloc[event_index]) if not pd.isna(atr_series.iloc[event_index]) else 0.0
        strength_atr = round(abs(float(close.iloc[event_index]) - level) / atr_t, 3) if atr_t > 0 else 0.0

        confirmation_state, confirmed_at, invalidated_at = _resolve_confirmation(
            close, event_index, direction, level, confirm_bars, n
        )

        retest_state = retest_event_at = retest_known_at = retest_deadline = None
        if confirmation_state == ConfirmationState.CONFIRMED.value:
            retest_deadline = confirmed_at + retest_bars
            retest_state, retest_event_at, retest_known_at = _resolve_retest(
                close, confirmed_at, direction, zone, retest_bars, n
            )

        if confirmation_state == ConfirmationState.INVALIDATED.value:
            resolved_at = invalidated_at
        elif retest_state in (RetestState.HELD.value, RetestState.FAILED.value, RetestState.EXPIRED.value):
            resolved_at = retest_known_at
        else:
            resolved_at = None

        event_at = df.index[event_index]
        event_at = event_at.date() if hasattr(event_at, "date") else event_at

        events.append(
            BreakoutTimelineEvent(
                event_id=f"{symbol}:{direction}:{event_at.isoformat()}",
                symbol=symbol,
                direction=direction,
                event_index=event_index,
                event_at=event_at,
                level=round(level, 6),
                zone_snapshot=zone,
                zone_known_at=event_index - 1,
                breakout_strength_atr=strength_atr,
                confirmation_state=confirmation_state,
                confirmed_at=confirmed_at,
                invalidated_at=invalidated_at,
                retest_state=retest_state,
                retest_event_at=retest_event_at,
                retest_known_at=retest_known_at,
                retest_deadline=retest_deadline,
                resolved_at=resolved_at,
            )
        )
    return events


def _resolve_confirmation(
    close: pd.Series, event_index: int, direction: str, level: float, confirm_bars: int, n: int
) -> tuple[str, int | None, int | None]:
    """confirm_bars=3: T+1/T+2/T+3 kapanışlarının ÜÇÜ DE level'ın doğru
    tarafında kalırsa CONFIRMED (confirmed_at=T+3); herhangi biri (İLK ihlal
    barı) level'a geri dönerse INVALIDATED (invalidated_at=ilk ihlal barı);
    T+3 henüz mevcut değilse ve ihlal de yoksa PENDING_CONFIRMATION."""
    for offset in range(1, confirm_bars + 1):
        i = event_index + offset
        if i >= n:
            return ConfirmationState.PENDING_CONFIRMATION.value, None, None
        price = float(close.iloc[i])
        broke_back = price <= level if direction == "BULLISH" else price >= level
        if broke_back:
            return ConfirmationState.INVALIDATED.value, None, i
    return ConfirmationState.CONFIRMED.value, event_index + confirm_bars, None


def _resolve_retest(
    close: pd.Series, confirmed_at: int, direction: str, zone: SRZone, retest_bars: int, n: int
) -> tuple[str, int | None, int | None]:
    """Retest, confirmation TAMAMLANDIKTAN SONRA (confirmed_at+1) başlar --
    confirmation penceresiyle ASLA ÇAKIŞMAZ. Dondurulmuş `zone_snapshot`
    (low/high bandı) üzerinden: pencerede fiyat önce zone'a geri DOKUNUR
    (bullish: Close<=zone.high), sonra o andan pencere sonuna kadar karşı
    sınırın (zone.low) altına/üstüne hiç kırılmazsa HELD, kırılırsa (ilk
    ihlal barında) FAILED. Pencere boyunca hiç dokunuş olmazsa, pencere
    TAMAMEN tamamlandıysa EXPIRED, henüz tamamlanmadıysa PENDING."""
    start = confirmed_at + 1
    deadline = confirmed_at + retest_bars
    end = min(deadline, n - 1)
    window_fully_elapsed = deadline < n

    if start > end:
        return (RetestState.EXPIRED.value if window_fully_elapsed else RetestState.PENDING.value), None, (
            deadline if window_fully_elapsed else None
        )

    touch_idx = None
    for i in range(start, end + 1):
        price = float(close.iloc[i])
        touched = price <= zone.high if direction == "BULLISH" else price >= zone.low
        if touched:
            touch_idx = i
            break

    if touch_idx is None:
        if window_fully_elapsed:
            return RetestState.EXPIRED.value, None, deadline
        return RetestState.PENDING.value, None, None

    for i in range(touch_idx, end + 1):
        price = float(close.iloc[i])
        ok = price >= zone.low if direction == "BULLISH" else price <= zone.high
        if not ok:
            return RetestState.FAILED.value, touch_idx, i

    if window_fully_elapsed:
        return RetestState.HELD.value, touch_idx, end
    return RetestState.PENDING.value, touch_idx, None


def select_live_breakout_event(
    timeline: list[BreakoutTimelineEvent],
    today_index: int,
    max_age_sessions: int = MAX_EVENT_AGE_SESSIONS,
) -> BreakoutTimelineEvent | None:
    """"Bugün" (`today_index`) için gösterilecek TEK event'i seçer:
    1. En yeni AÇIK event (PENDING_CONFIRMATION, veya CONFIRMED+retest PENDING).
    2. Yoksa, `max_age_sessions` içindeki en yeni RESOLVED event (CONFIRMED +
       HELD/FAILED/EXPIRED). INVALIDATED event'ler burada HİÇ seçilmez --
       timeline'da/geçmişte kalırlar ama "güncel breakout" olarak
       gösterilmezler (başarısız bir setup'ı güncelmiş gibi göstermenin
       kullanıcıya değeri yok).
    3. Hiçbiri yoksa None.
    """
    open_events = [
        e
        for e in timeline
        if e.event_index <= today_index
        and (
            e.confirmation_state == ConfirmationState.PENDING_CONFIRMATION.value
            or (e.confirmation_state == ConfirmationState.CONFIRMED.value and e.retest_state == RetestState.PENDING.value)
        )
    ]
    if open_events:
        return max(open_events, key=lambda e: e.event_index)

    resolved = [
        e
        for e in timeline
        if e.event_index <= today_index
        and e.confirmation_state == ConfirmationState.CONFIRMED.value
        and e.retest_state in (RetestState.HELD.value, RetestState.FAILED.value, RetestState.EXPIRED.value)
        and (today_index - e.event_index) <= max_age_sessions
    ]
    if resolved:
        return max(resolved, key=lambda e: e.event_index)
    return None


_CONFIRMED_LEGACY_MAP = {
    ConfirmationState.PENDING_CONFIRMATION.value: None,
    ConfirmationState.CONFIRMED.value: True,
    ConfirmationState.INVALIDATED.value: False,
}

_RETEST_LEGACY_MAP = {
    None: None,
    RetestState.PENDING.value: None,
    RetestState.HELD.value: True,
    RetestState.FAILED.value: False,
    RetestState.EXPIRED.value: None,  # "hiç retest gelmedi" != "retest başarısız oldu"
}


def to_legacy_breakout_event(event: BreakoutTimelineEvent | None) -> BreakoutEvent | None:
    """Yeni state modelini, `signal_classifier.classify_signal()`'ın hâlâ
    beklediği eski `BreakoutEvent(confirmed: bool|None, retest_held: bool|None)`
    sözleşmesine çevirir -- `signal_classifier.py`/`engine.py`'nin geri kalanı
    HİÇ DEĞİŞMEDEN çalışmaya devam eder."""
    if event is None:
        return None
    return BreakoutEvent(
        index=event.event_index,
        direction=event.direction,
        zone=event.zone_snapshot,
        breakout_atr=event.breakout_strength_atr,
        confirmed=_CONFIRMED_LEGACY_MAP[event.confirmation_state],
        retest_held=_RETEST_LEGACY_MAP[event.retest_state],
    )
