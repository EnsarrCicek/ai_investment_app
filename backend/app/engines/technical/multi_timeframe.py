"""Çoklu zaman dilimi uyumu (multi-timeframe alignment) —
TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7, adım 11.

Tek bir zaman diliminde (günlük bar) "yükseliş" görünen bir sinyal, daha
büyük resimde (haftalık) hâlâ bir düşüş trendinin içindeki geçici bir
toparlanma olabilir. Bu modül, aynı varlığın farklı zaman dilimlerindeki
(interval) EMA eğimi yönlerini karşılaştırıp bir "uyum" (alignment) sonucu
üretir — BistProvider.get_history zaten `interval` parametresini destekliyor
(bkz. base.py), bunun için yeni bir provider metoduna gerek yoktur; bu modül
yalnızca zaten çekilmiş Close serileri üzerinde çalışır (tek sorumluluk).

Kapsam notu: Yalnızca yön (pozitif/negatif/nötr) karşılaştırılır, büyüklük
değil — farklı zaman dilimlerindeki EMA eğimi büyüklükleri doğrudan
karşılaştırılabilir değildir (farklı bar sıklığı, farklı volatilite ölçeği).
"""

import pandas as pd

from app.engines.technical.indicators import ema_slope

DEFAULT_TIMEFRAMES = ("1d", "1wk")


def _direction(slope_value: float, neutral_band: float = 0.5) -> str:
    if pd.isna(slope_value):
        return "UNKNOWN"
    if slope_value > neutral_band:
        return "UP"
    if slope_value < -neutral_band:
        return "DOWN"
    return "FLAT"


def timeframe_direction(close: pd.Series, window: int = 20, slope_lookback: int = 5) -> str:
    """Tek bir zaman dilimi için EMA eğimi yönü (UP/DOWN/FLAT/UNKNOWN)."""
    slope = ema_slope(close, window=window, slope_lookback=slope_lookback)
    if slope.empty or pd.isna(slope.iloc[-1]):
        return "UNKNOWN"
    return _direction(float(slope.iloc[-1]))


def check_alignment(directions: dict[str, str]) -> dict:
    """Farklı zaman dilimlerindeki yönleri karşılaştırıp genel bir uyum sonucu üretir.

    - Tüm bilinen zaman dilimleri aynı yöndeyse (UP ya da DOWN): aligned=True.
    - UP ve DOWN bir arada varsa: "CONFLICTING" (en riskli durum — sinyal
      zaman dilimine göre çelişiyor).
    - Diğer karışık durumlar (ör. UP+FLAT): "MIXED".
    - Hiçbir zaman dilimi için yön belirlenemediyse: "UNKNOWN".
    """
    known = {tf: d for tf, d in directions.items() if d != "UNKNOWN"}
    if not known:
        return {"aligned": False, "consensus": "UNKNOWN", "directions": directions}

    unique = set(known.values())
    if len(unique) == 1:
        consensus = next(iter(unique))
        return {"aligned": consensus in ("UP", "DOWN"), "consensus": consensus, "directions": directions}

    if "UP" in unique and "DOWN" in unique:
        return {"aligned": False, "consensus": "CONFLICTING", "directions": directions}

    return {"aligned": False, "consensus": "MIXED", "directions": directions}
