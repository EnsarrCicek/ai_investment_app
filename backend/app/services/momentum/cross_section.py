"""Kesitsel (cross-sectional) bağlam ve basit piyasa rejimi — TARAYICI düzeyi, SAF fonksiyonlar.

Motor çekirdeğine girmez: tarayıcı aynı değerlendirme anında evrendeki tüm varlıkların özniteliklerini hesapladıktan
sonra bu bağlamı üretir. Yalnız AYNI anın (zaten nedensel) öznitelikleri kullanılır → gelecek sızıntısı yok.
Referans paneli yetersizse (`min_universe`) değer `None` (uydurma 0 YOK).
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import median

REGIME_NORMAL = "NORMAL"
REGIME_SHOCK = "SHOCK"
MIN_UNIVERSE = 10
SHOCK_MEDIAN_MOVE_PCT = 1.5  # evren medyan seans getirisi |≥%1.5| → genel şok günü
SHOCK_BENCH_RV_RATIO = 2.0  # benchmark gün içi gerçekleşen oynaklığı tabanın ≥2 katı


def percentile_against(value: float | None, panel: list[float | None], min_universe: int = MIN_UNIVERSE
                       ) -> float | None:
    """`value`'nun panel içindeki yüzdelik sırası (0..1; eşitlikler yarım sayılır). Panel değeri kendini içermemeli."""
    vals = [p for p in panel if p is not None]
    if value is None or len(vals) < min_universe:
        return None
    less = sum(p < value for p in vals)
    equal = sum(p == value for p in vals)
    return (less + 0.5 * equal) / len(vals)


def cross_sectional_ranks(features: Mapping[str, float | None], reference: Mapping[str, float | None],
                          min_universe: int = MIN_UNIVERSE) -> dict[str, float | None]:
    """Her varlık için referans panelindeki (KENDİSİ HARİÇ) yüzdelik sıra."""
    return {sym: percentile_against(val, [v for s, v in reference.items() if s != sym], min_universe)
            for sym, val in features.items()}


def market_regime(session_returns_pct: Mapping[str, float | None], bench_rv_ratio: float | None,
                  min_universe: int = MIN_UNIVERSE) -> dict:
    vals = [v for v in session_returns_pct.values() if v is not None]
    if len(vals) < min_universe:
        breadth = med = None
    else:
        breadth = sum(v > 0 for v in vals) / len(vals)
        med = median(vals)
    shock = ((med is not None and abs(med) >= SHOCK_MEDIAN_MOVE_PCT)
             or (bench_rv_ratio is not None and bench_rv_ratio >= SHOCK_BENCH_RV_RATIO))
    known = med is not None or bench_rv_ratio is not None
    return {"breadth": breadth, "median_session_move_pct": med, "bench_rv_ratio": bench_rv_ratio,
            "regime": (REGIME_SHOCK if shock else REGIME_NORMAL) if known else None}
