"""Mum formasyonları (candlestick patterns) — TECHNICAL_ANALYSIS_RESEARCH1.md,
rapor madde 7 adım 14 (kısmi: günlük bar üzerinden çalışan kısım).

ÖNEMLİ UYARI (dokümanın kendi vurgusu): mum formasyonları TEK BAŞINA asla bir
AL/SAT sinyali değildir — bağlam (trend, S/R yakınlığı, hacim) olmadan
anlamsızdır. Bu modül yalnızca formasyonu TESPİT eder; formasyonun "anlamlı"
olup olmadığına (ör. bir destek bölgesinde mi oluştu, düşüş trendinin
sonunda mı) karar vermek signal_classifier.py'nin ya da gelecekteki bir
entegrasyon adımının işidir — burada bilinçli olarak yapılmaz.

Kapsam: en yaygın/en net tanımlı 5 formasyon (Doji, Hammer, Shooting Star,
Bullish/Bearish Engulfing). Daha fazla bar gerektiren formasyonlar (Morning/
Evening Star, Three White Soldiers vb.) daha çok yanlış-pozitif üretir;
ihtiyaç oldukça ayrı eklenebilir.
"""

import pandas as pd


def _body(open_: float, close_: float) -> float:
    return abs(close_ - open_)


def _range(high: float, low: float) -> float:
    return high - low


def is_doji(open_: float, high: float, low: float, close: float, body_ratio: float = 0.1) -> bool:
    """Gövde, toplam aralığın küçük bir kısmıysa (kararsızlık) — açılış≈kapanış."""
    total_range = _range(high, low)
    if total_range == 0:
        return False
    return (_body(open_, close) / total_range) <= body_ratio


def is_hammer(open_: float, high: float, low: float, close: float) -> bool:
    """Küçük gövde, üstte kısa/yok fitil, altta gövdenin en az 2 katı uzunlukta
    fitil — düşüş trendinin sonunda görülürse potansiyel dönüş adayı (bağlama bağlı)."""
    body = _body(open_, close)
    total_range = _range(high, low)
    if total_range == 0 or body == 0:
        return False
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    return lower_wick >= 2 * body and upper_wick <= body * 0.5


def is_shooting_star(open_: float, high: float, low: float, close: float) -> bool:
    """Hammer'ın aynası — küçük gövde, üstte uzun fitil, altta kısa/yok fitil."""
    body = _body(open_, close)
    total_range = _range(high, low)
    if total_range == 0 or body == 0:
        return False
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    return upper_wick >= 2 * body and lower_wick <= body * 0.5


def is_bullish_engulfing(prev_open: float, prev_close: float, open_: float, close: float) -> bool:
    """Önceki bar düşüş (kırmızı), bu bar yükseliş (yeşil) ve önceki gövdeyi tamamen 'yutuyor'."""
    prev_bearish = prev_close < prev_open
    curr_bullish = close > open_
    engulfs = open_ <= prev_close and close >= prev_open
    return prev_bearish and curr_bullish and engulfs


def is_bearish_engulfing(prev_open: float, prev_close: float, open_: float, close: float) -> bool:
    prev_bullish = prev_close > prev_open
    curr_bearish = close < open_
    engulfs = open_ >= prev_close and close <= prev_open
    return prev_bullish and curr_bearish and engulfs


def detect_patterns(df: pd.DataFrame, index: int = -1) -> list[str]:
    """Verilen bar'da (varsayılan: son bar) tespit edilen formasyon adlarını
    döner (birden fazlası aynı anda tetiklenebilir). Yalnızca `index` ve bir
    önceki bar'a bakar — sonraki barlara ASLA bakmaz (causal).
    """
    pos = index if index >= 0 else len(df) + index
    row = df.iloc[pos]
    open_, high, low, close = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])

    patterns: list[str] = []
    if is_doji(open_, high, low, close):
        patterns.append("DOJI")
    if is_hammer(open_, high, low, close):
        patterns.append("HAMMER")
    if is_shooting_star(open_, high, low, close):
        patterns.append("SHOOTING_STAR")

    if pos > 0:
        prev_row = df.iloc[pos - 1]
        prev_open, prev_close = float(prev_row["Open"]), float(prev_row["Close"])
        if is_bullish_engulfing(prev_open, prev_close, open_, close):
            patterns.append("BULLISH_ENGULFING")
        if is_bearish_engulfing(prev_open, prev_close, open_, close):
            patterns.append("BEARISH_ENGULFING")

    return patterns
