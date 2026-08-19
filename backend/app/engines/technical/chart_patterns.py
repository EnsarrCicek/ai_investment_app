"""Klasik grafik formasyonları (chart patterns) — TECHNICAL_ANALYSIS_
RESEARCH1.md, rapor madde 7 adım 14 (kısmi: günlük bar üzerinden çalışan
kısım).

Dokümanın vurgusu: klasik formasyonlar (Double Bottom, Double Top vb.)
yalnızca TAMAMLANDIĞINDA — neckline kırılımıyla ONAYLANDIĞINDA — anlamlıdır;
"iki dip birbirine yakın" tespiti tek başına yeterli değildir, fiyatın
aradaki tepeyi (neckline) KIRMASI gerekir (breakout.py'deki confirm_breakout
ile aynı "onay gecikmesi" ilkesi). Bu modül market_structure.
find_swing_points()'in ürettiği SwingPoint listesini girdi alır (kendi
başına swing tespiti yapmaz — tek sorumluluk).

Kapsam: yalnızca Double Bottom/Double Top (en sık aranan, en net tanımlı iki
formasyon). Head & Shoulders gibi 3+ nokta gerektiren formasyonlar daha
karmaşık/daha çok yanlış-pozitif üretir; ihtiyaç oldukça ayrı eklenebilir.
"""

from dataclasses import dataclass

import pandas as pd

from app.engines.technical.market_structure import SwingPoint, SwingType


@dataclass
class ChartPatternEvent:
    type: str  # "DOUBLE_BOTTOM" veya "DOUBLE_TOP"
    first_point_index: int
    second_point_index: int
    neckline_price: float
    neckline_index: int
    confirmed: bool  # neckline (henüz) kırıldı mı


def find_double_bottom_candidates(points: list[SwingPoint], atr: float, tolerance_atr: float = 0.5) -> list[dict]:
    """İki swing low, aralarında bir swing high (neckline) varsa ve fiyat
    seviyeleri birbirine yakınsa (tolerance_atr * atr içinde) aday sayılır.
    Henüz kırılım kontrolü yapılmaz (bkz. confirm_double_bottom)."""
    if atr <= 0:
        return []
    lows = [p for p in points if p.type == SwingType.LOW]
    highs = [p for p in points if p.type == SwingType.HIGH]

    candidates = []
    for i in range(len(lows) - 1):
        first, second = lows[i], lows[i + 1]
        if abs(first.price - second.price) > tolerance_atr * atr:
            continue
        between_highs = [h for h in highs if first.index < h.index < second.index]
        if not between_highs:
            continue
        neckline = max(between_highs, key=lambda h: h.price)
        candidates.append({"first": first, "second": second, "neckline": neckline})
    return candidates


def find_double_top_candidates(points: list[SwingPoint], atr: float, tolerance_atr: float = 0.5) -> list[dict]:
    """Double Bottom'un aynası — iki swing high, aralarında bir swing low (neckline)."""
    if atr <= 0:
        return []
    highs = [p for p in points if p.type == SwingType.HIGH]
    lows = [p for p in points if p.type == SwingType.LOW]

    candidates = []
    for i in range(len(highs) - 1):
        first, second = highs[i], highs[i + 1]
        if abs(first.price - second.price) > tolerance_atr * atr:
            continue
        between_lows = [low for low in lows if first.index < low.index < second.index]
        if not between_lows:
            continue
        neckline = min(between_lows, key=lambda low: low.price)
        candidates.append({"first": first, "second": second, "neckline": neckline})
    return candidates


def confirm_double_bottom(close: pd.Series, candidate: dict) -> ChartPatternEvent:
    """`second` noktasından SONRAKİ barlarda fiyat neckline'ı kırdıysa
    (kapanış > neckline fiyatı) formasyon onaylanmış sayılır. Henüz
    kırılmadıysa confirmed=False — pattern henüz tamamlanmamış demektir."""
    neckline = candidate["neckline"]
    after = close.iloc[candidate["second"].index + 1 :]
    confirmed = bool((after > neckline.price).any())
    return ChartPatternEvent(
        type="DOUBLE_BOTTOM",
        first_point_index=candidate["first"].index,
        second_point_index=candidate["second"].index,
        neckline_price=neckline.price,
        neckline_index=neckline.index,
        confirmed=confirmed,
    )


def confirm_double_top(close: pd.Series, candidate: dict) -> ChartPatternEvent:
    """Double Bottom'un aynası — kapanış neckline'ın ALTINA inerse onaylanır."""
    neckline = candidate["neckline"]
    after = close.iloc[candidate["second"].index + 1 :]
    confirmed = bool((after < neckline.price).any())
    return ChartPatternEvent(
        type="DOUBLE_TOP",
        first_point_index=candidate["first"].index,
        second_point_index=candidate["second"].index,
        neckline_price=neckline.price,
        neckline_index=neckline.index,
        confirmed=confirmed,
    )
