"""Breakout kalitesi, false breakout tespiti ve retest onayı
(TECHNICAL_ANALYSIS_RESEARCH1.md — rapor madde 7, adım 5).

Üç kavram:
1. Breakout quality: kapanış bir direnç/destek bölgesinin dışına çıktığında,
   bu çıkışın büyüklüğü ATR'ye göre normalize edilir (`breakout_atr`) — ham
   fiyat farkı değil, volatiliteye göre anlamlı bir büyüklük kullanılır.
2. False breakout: fiyat bölgeyi kırar ama belirli bir bar sayısı içinde geri
   bölgenin içine kapanırsa, kırılım "yanlış" (false) sayılır. Bunun için de
   look-ahead-bias-safe bir onay gecikmesi gerekir — kırılımın gerçek olup
   olmadığı ancak `confirm_bars` kadar bar sonra bilinebilir; o bar'lar henüz
   oluşmadıysa `confirmed=None` kalır ("henüz bilinmiyor" ile "false
   breakout" birbirine KARIŞTIRILMAZ).
3. Retest: gerçek (confirmed=True) bir kırılımdan sonra fiyat kırılan
   bölgeye geri dönüp (artık ters rolde — eski direnç yeni destek olur) o
   seviyeyi kırmadan tutarsa, bu ek bir doğrulama sinyalidir.

Girdi olarak support_resistance.SRZone ve bir Close serisi alır — kendi
başına zone tespiti yapmaz (tek sorumluluk). Henüz TechnicalAnalysisEngine'e
bağlanmadı (bkz. o modülün docstring'i).
"""

from dataclasses import dataclass

import pandas as pd

from app.engines.technical.support_resistance import SRZone


@dataclass
class BreakoutEvent:
    index: int
    direction: str  # "BULLISH" veya "BEARISH"
    zone: SRZone
    breakout_atr: float
    confirmed: bool | None = None  # None = henüz confirm_bars kadar veri yok
    retest_held: bool | None = None  # None = henüz retest penceresi yok / hiç retest olmadı


def detect_breakout(close: pd.Series, zone: SRZone, index: int, atr: float) -> BreakoutEvent | None:
    """`index` bar'ında zone'un kırılıp kırılmadığını kontrol eder (henüz confirm/retest hesaplamaz)."""
    if atr <= 0:
        return None
    price = float(close.iloc[index])
    if zone.type == "RESISTANCE" and price > zone.high:
        return BreakoutEvent(
            index=index,
            direction="BULLISH",
            zone=zone,
            breakout_atr=round((price - zone.high) / atr, 3),
        )
    if zone.type == "SUPPORT" and price < zone.low:
        return BreakoutEvent(
            index=index,
            direction="BEARISH",
            zone=zone,
            breakout_atr=round((zone.low - price) / atr, 3),
        )
    return None


def confirm_breakout(close: pd.Series, event: BreakoutEvent, confirm_bars: int = 3) -> BreakoutEvent:
    """Kırılımdan sonraki `confirm_bars` bar'a bakarak false breakout olup olmadığını belirler."""
    window_end = event.index + confirm_bars
    if window_end >= len(close):
        return event  # yeterli bar henüz yok — confirmed None kalır

    window = close.iloc[event.index + 1 : window_end + 1]
    if event.direction == "BULLISH":
        event.confirmed = bool((window > event.zone.high).all())
    else:
        event.confirmed = bool((window < event.zone.low).all())
    return event


def check_retest(close: pd.Series, event: BreakoutEvent, retest_bars: int = 10) -> BreakoutEvent:
    """Kırılımdan sonraki `retest_bars` içinde fiyatın kırılan bölgeye geri dönüp
    (artık ters roldeki) seviyeyi tutup tutmadığını kontrol eder.

    - confirmed != True ise (henüz bilinmiyor ya da false breakout) retest
      anlamsızdır, kontrol edilmez.
    - Pencerede hiç geri dönüş (touch) yoksa retest_held=None ("retest hiç
      olmadı" — ne teyit ne ret).
    - Geri dönüş olduysa: ilk temastan sonra seviye hep tutulduysa True,
      seviyenin altına/üstüne (yöne göre) kırıldıysa False.
    """
    if event.confirmed is not True:
        return event

    start = event.index + 1
    end = min(event.index + retest_bars, len(close) - 1)
    if start > end:
        return event

    window = close.iloc[start : end + 1]

    if event.direction == "BULLISH":
        touch_mask = window <= event.zone.high
        if not touch_mask.any():
            return event
        first_touch_pos = int(touch_mask.to_numpy().argmax())
        after_touch = window.iloc[first_touch_pos:]
        event.retest_held = bool((after_touch >= event.zone.low).all())
    else:
        touch_mask = window >= event.zone.low
        if not touch_mask.any():
            return event
        first_touch_pos = int(touch_mask.to_numpy().argmax())
        after_touch = window.iloc[first_touch_pos:]
        event.retest_held = bool((after_touch <= event.zone.high).all())

    return event
