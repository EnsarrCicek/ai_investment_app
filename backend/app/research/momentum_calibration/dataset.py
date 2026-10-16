"""Momentum kalibrasyon veri kümesi — gerçek Yahoo 5 dk barları, yerel önbellek, kronolojik bölme.

* Sembol başına TEK istek (`5m`, `period="60d"`); ham veri `runs/cache/` altında yerel artefakttır, Git'e girmez.
* KTLEV kalibrasyon kümesinde YOKTUR; yalnız final örnek olay (holdout case) olarak kullanılır.
* Bölme rastgele değil, işlem günü sırasına göredir (ilk %50 kalibrasyon, sonraki %25 doğrulama, son %25 holdout).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ

RUNS = Path(__file__).resolve().parent / "runs"
CACHE = RUNS / "cache"
HOLDOUT_CASE = "KTLEV"

# Sektör/likidite çeşitliliği için seçildi (aktif evrenden): bankacılık, holding, enerji, sanayi, perakende,
# havacılık, telekom, gıda, savunma, oynak orta ölçek. KTLEV bilinçli olarak YOK.
CALIBRATION_ASSETS: tuple[str, ...] = (
    "AKBNK", "GARAN", "YKBNK", "ISCTR", "HALKB", "VAKBN", "TSKB",          # bankacılık
    "KCHOL", "SAHOL", "ALARK", "DOHOL",                                    # holding
    "TUPRS", "AKSEN", "ZOREN", "ENJSA", "CWENE", "ASTOR", "PETKM",         # enerji
    "EREGL", "KRDMD", "ARCLK", "VESTL", "OTKAR", "FROTO", "TOASO", "SISE",  # sanayi
    "CIMSA", "BTCIM", "SASA", "GUBRF", "HEKTS",                            # sanayi/kimya
    "BIMAS", "MGROS", "SOKM",                                              # perakende
    "THYAO", "PGSUS",                                                      # havacılık
    "TTKOM", "TCELL",                                                      # telekom
    "ULKER", "CCOLA", "AEFES", "TUKAS",                                    # gıda/içecek
    "ASELS",                                                               # savunma
    "BERA", "CANTE", "CVKMD", "TRENJ", "FENER", "GSRAY", "MIATK",           # oynak orta ölçek
)
SPLIT_FRACTIONS = (0.50, 0.25, 0.25)
WARMUP_SESSIONS = 3  # motorun en az 3 önceki seans şartı: ilk 3 seans değerlendirilmez
WINDOW_SESSIONS = 15  # canlı tarayıcı `period="15d"` ile aynı pencere


@dataclass(frozen=True)
class AssetData:
    symbol: str
    bars: pd.DataFrame  # İstanbul saatli, bar başlangıç zamanları
    provenance: dict
    fetched_at: datetime


def load(symbol: str, provider=None) -> AssetData:
    """Önbellekte varsa onu, yoksa TEK Yahoo isteğini kullanır."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol}_5m_60d.pkl"
    if path.exists():
        with path.open("rb") as f:
            raw = pickle.load(f)
    else:
        from app.services.momentum.intraday_provider import YahooIntradayProvider

        got = (provider or YahooIntradayProvider()).get_intraday(symbol, interval="5m", period="60d")
        raw = {"bars": got.bars, "provenance": got.provenance, "fetched_at": datetime.now(timezone.utc)}
        with path.open("wb") as f:
            pickle.dump(raw, f)
    bars = raw["bars"].copy()
    bars.index = pd.DatetimeIndex(bars.index).tz_convert(ISTANBUL_TZ)
    return AssetData(symbol, bars, raw["provenance"], raw["fetched_at"])


def complete_sessions(data: AssetData) -> list[date]:
    """Veri çekildiği gün (olası yarım seans) hariç tüm seans tarihleri."""
    fetched_day = data.fetched_at.astimezone(ISTANBUL_TZ).date()
    return sorted(d for d in set(data.bars.index.date) if d < fetched_day)


def split_sessions(dates: list[date], fractions=SPLIT_FRACTIONS, warmup=WARMUP_SESSIONS) -> dict[str, list[date]]:
    """Kronolojik bölme (rastgele değil). İlk `warmup` seans yalnız taban içindir, değerlendirilmez."""
    evaluable = sorted(dates)[warmup:]
    n = len(evaluable)
    a = round(n * fractions[0])
    b = a + round(n * fractions[1])
    return {"calibration": evaluable[:a], "validation": evaluable[a:b], "holdout": evaluable[b:]}


def window_for(data: AssetData, day: date, sessions: int = WINDOW_SESSIONS) -> pd.DataFrame:
    """`day` dahil son `sessions` seansın barları (canlı pencereyle aynı). Gelecek barları motor ayrıca dışlar."""
    days = sorted(d for d in set(data.bars.index.date) if d <= day)[-sessions:]
    return data.bars[(data.bars.index.date >= days[0]) & (data.bars.index.date <= day)] if days else data.bars.iloc[:0]
