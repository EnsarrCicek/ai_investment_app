"""Gelecek sonuç etiketleri — YALNIZ değerlendirme içindir; motora asla girmez.

Değerlendirme anı T'de kullanıcının işlem yapabileceği fiyat: T'de veya sonra başlayan ilk barın açılışı (`entry`).
(Motor 15 dk gecikmeli veriyi görür; gerçek piyasa fiyatı T'dedir.)

* Label A (60 dk): T sonrası 60 dk içindeki en yüksek / entry − 1 ≥ X
* Label B (gün sonu MFE): T sonrası seans sonuna kadarki en yüksek / entry − 1 ≥ X
* Label C (kapanış): seans kapanışı / entry − 1 ≥ X

Seans düzeyinde olay: seans içi en büyük yükseliş (o ana kadarki en düşükten sonraki en yükseğe) ≥ E → EVENT.
Aynı günün onlarca barı ayrı pozitif sayılmaz; metrikler seans başına ilk alarmı kullanır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EvalLabel:
    entry: float | None
    mfe_60: float | None
    mfe_close: float | None
    ret_close: float | None
    low_before: float | None  # T'ye kadar seansın en düşüğü (gerçekleşen hareket payı için)


@dataclass(frozen=True)
class SessionOutcome:
    max_runup: float  # oran (0.05 = %5)
    high: float
    high_time: datetime
    open_price: float


def session_outcome(day_bars: pd.DataFrame) -> SessionOutcome:
    lows = day_bars["Low"].to_numpy()
    highs = day_bars["High"].to_numpy()
    running_low = np.minimum.accumulate(lows)
    runup = float(np.max(highs / running_low) - 1)
    j = int(np.argmax(highs))
    return SessionOutcome(runup, float(highs[j]), day_bars.index[j].to_pydatetime(), float(day_bars["Open"].iloc[0]))


def label_at(day_bars: pd.DataFrame, t: datetime) -> EvalLabel:
    after = day_bars[day_bars.index >= pd.Timestamp(t)]
    before = day_bars[day_bars.index < pd.Timestamp(t)]
    if after.empty:
        return EvalLabel(None, None, None, None, None)
    entry = float(after["Open"].iloc[0])
    in_60 = after[after.index < pd.Timestamp(t + timedelta(minutes=60))]
    return EvalLabel(entry=entry,
                     mfe_60=float(in_60["High"].max() / entry - 1),
                     mfe_close=float(after["High"].max() / entry - 1),
                     ret_close=float(after["Close"].iloc[-1] / entry - 1),
                     low_before=float(before["Low"].min()) if len(before) else entry)


def labels_for_session(bars: pd.DataFrame, day: date, times: list[datetime]) -> tuple[SessionOutcome, list[EvalLabel]]:
    """`label_at` ile aynı tanım, seans başına vektörize (sonsoneki maksimum / öndeki minimum)."""
    day_bars = bars[bars.index.date == day].dropna()
    starts = day_bars.index.asi8 if day_bars.index.unit == "ns" else day_bars.index.as_unit("ns").asi8
    opens, highs, lows, closes = (day_bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    suffix_high = np.maximum.accumulate(highs[::-1])[::-1] if len(highs) else highs
    prefix_low = np.minimum.accumulate(lows) if len(lows) else lows
    out = []
    for t in times:
        t_ns = pd.Timestamp(t).as_unit("ns").value
        j = int(np.searchsorted(starts, t_ns, side="left"))  # ilk bar başlangıcı >= t
        if j >= len(starts):
            out.append(EvalLabel(None, None, None, None, None))
            continue
        entry = float(opens[j])
        k = int(np.searchsorted(starts, pd.Timestamp(t + timedelta(minutes=60)).as_unit("ns").value, side="left"))
        # T sonrası 60 dk içinde bar yoksa (seans içi boşluk) `label_at` gibi NaN
        mfe_60 = float(highs[j:k].max() / entry - 1) if k > j else float("nan")
        out.append(EvalLabel(entry=entry, mfe_60=mfe_60,
                             mfe_close=float(suffix_high[j] / entry - 1), ret_close=float(closes[-1] / entry - 1),
                             low_before=float(prefix_low[j - 1]) if j > 0 else entry))
    return session_outcome(day_bars), out
