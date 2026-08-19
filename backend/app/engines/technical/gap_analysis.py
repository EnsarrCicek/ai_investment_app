"""Gap analizi — TECHNICAL_ANALYSIS_RESEARCH1.md, rapor madde 7 adım 14
(kısmi: günlük bar üzerinden çalışan kısım; seans-içi/intraday analiz YOK —
bkz. KURULUM_GUNLUGU.md AŞAMA 48/14 kapsam notu).

RiskEngine.gap_risk() zaten bir DÖNEM boyunca ortalama/maksimum gap
büyüklüğünü ölçüyordu (risk profili amaçlı). Bu modül farklı bir soruya
cevap verir: SON bar'daki gap ne kadar büyük ve hâlâ "açık" mı (aynı bar
içinde doldurulmadı mı)? Bu, sinyal sınıflandırmasında (signal_classifier.py)
"büyük/doldurulmamış gap sonrası pozisyon açmak riskli" gibi bir uyarı/veto
koşulu için kullanılacak — henüz oraya bağlanmadı.
"""

import pandas as pd


def latest_gap(df: pd.DataFrame, atr: float) -> dict | None:
    """Son bar'ın açılışı ile bir önceki kapanış arasındaki farkı hem % hem
    ATR-normalize olarak döner. En az 2 bar ve pozitif ATR gerekir; yoksa
    None döner (Missing Data Davranışı).
    """
    if len(df) < 2 or atr <= 0:
        return None
    prev_close = float(df["Close"].iloc[-2])
    open_price = float(df["Open"].iloc[-1])
    if prev_close == 0:
        return None
    gap_pct = (open_price - prev_close) / prev_close * 100
    gap_atr = (open_price - prev_close) / atr
    return {
        "gap_pct": round(gap_pct, 3),
        "gap_atr": round(gap_atr, 3),
        "direction": "UP" if gap_pct > 0 else "DOWN" if gap_pct < 0 else "NONE",
    }


def is_gap_filled(df: pd.DataFrame) -> bool | None:
    """Son bar'daki gap, aynı bar içinde (gün içi Low-High aralığında) bir
    önceki kapanış seviyesine geri dönüldüyse "dolduruldu" sayılır."""
    if len(df) < 2:
        return None
    prev_close = float(df["Close"].iloc[-2])
    low, high = float(df["Low"].iloc[-1]), float(df["High"].iloc[-1])
    return low <= prev_close <= high


def classify_gap(gap: dict | None, filled: bool | None, significant_atr: float = 1.0) -> str:
    """NO_SIGNIFICANT_GAP / GAP_FILLED / GAP_UP_OPEN / GAP_DOWN_OPEN / UNKNOWN."""
    if gap is None:
        return "UNKNOWN"
    if abs(gap["gap_atr"]) < significant_atr:
        return "NO_SIGNIFICANT_GAP"
    if filled:
        return "GAP_FILLED"
    return f"GAP_{gap['direction']}_OPEN"
