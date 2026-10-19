"""Round 2 metrikleri: Round 1 seans başına ilk alarm metrikleri + erkenlik (lead_fraction).

lead_fraction (olay seansında, alarm anında hareketin tamamlanan payı):
    (giriş fiyatı − yükseliş tabanı) / (seans tepesi − yükseliş tabanı), alt sınır 0
    yükseliş tabanı = seans tepesinden ÖNCEKİ en düşük fiyat (olay tanımındaki seans içi yükselişin başlangıcı).
0 → hareket başlamadan, 1 → tepede. Yalnız tepeden ÖNCE gelen (yakalanan) alarmlar için hesaplanır.
`lead_all_events`: kaçırılan olaylar 1.0 sayılarak tüm olaylar üzerinden medyan (duyarlılık cezalı erkenlik).
"""

from __future__ import annotations

from statistics import median

import numpy as np
import pandas as pd

from app.research.momentum_calibration.metrics import first_alerts, summarize

EARLY_LEAD = 1 / 3


def run_low(bars: pd.DataFrame, day) -> float:
    d = bars[bars.index.date == day].dropna()
    highs, lows = d["High"].to_numpy(), d["Low"].to_numpy()
    return float(lows[: int(np.argmax(highs)) + 1].min())


def lead_fraction(entry: float, low: float, high: float) -> float | None:
    if entry is None or high <= low:
        return None
    return max(0.0, (entry - low) / (high - low))


def summarize2(rows, sessions, run_lows, level, x, e, label="mfe_close") -> dict:
    out = summarize(rows, sessions, level, x, e, label)
    alerts = first_alerts(rows, level)
    events = [k for k, o in sessions.items() if o.max_runup >= e]
    leads, all_leads = [], []
    for k in events:
        o = sessions[k]
        r = alerts.get(k)
        lf = None
        if r is not None and r["t"] <= o.high_time and r["label"].entry is not None:
            lf = lead_fraction(r["label"].entry, run_lows[k], o.high)
        if lf is not None:
            leads.append(lf)
        all_leads.append(lf if lf is not None else 1.0)
    out.update({
        "lead_fraction_median": round(median(leads), 3) if leads else None,
        "lead_fraction_p25": round(float(np.percentile(leads, 25)), 3) if leads else None,
        "lead_fraction_p75": round(float(np.percentile(leads, 75)), 3) if leads else None,
        "lead_all_events_median": round(median(all_leads), 3) if all_leads else None,
        "early_catch_rate": round(sum(lf <= EARLY_LEAD for lf in leads) / len(events), 4) if events else None,
    })
    return out


BRIEF_KEYS = ("alert_sessions", "alert_day_ratio", "precision", "recall", "false_positive_rate", "missed_events",
              "alert_evaluations_per_session", "median_first_alert_time", "lead_fraction_median",
              "lead_fraction_p75", "lead_all_events_median", "early_catch_rate", "median_future_mfe_pct",
              "max_asset_share_of_alerts")


def brief(m: dict) -> dict:
    return {k: m.get(k) for k in BRIEF_KEYS}
