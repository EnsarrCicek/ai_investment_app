"""Seans başına ilk alarm temelli metrikler (WATCH ve STRONG ayrı).

Bir seansta onlarca değerlendirme yapılır; aynı hareket için yüzlerce alarm SAYILMAZ: her (varlık, seans) için ilk
WATCH ve ilk STRONG anı esas alınır.

* İsabet (TP): ilk alarm anındaki Label B (gün sonu MFE) ≥ X.
* Kesinlik = TP / alarm alan seans.
* Olay seansı: seans içi en büyük yükseliş ≥ E. Duyarlılık (recall) = alarmı seans zirvesinden ÖNCE gelen olay
  seansı / olay seansı.
* Yanlış pozitif oranı = alarm alan olaysız seans / olaysız seans; özgüllük = 1 − YPO.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from app.models import momentum_alert as ma

RANK = {ma.LEVEL_NONE: 0, ma.LEVEL_WATCH: 1, ma.LEVEL_STRONG: 2}


def first_alerts(rows: list[dict], level: str) -> dict[tuple, dict]:
    """rows: {symbol, day, t, final_level, label, outcome} — zamana göre sıralı. Seans başına ilk alarm satırı."""
    out = {}
    for r in rows:
        key = (r["symbol"], r["day"])
        if key not in out and RANK[r["final_level"]] >= RANK[level]:
            out[key] = r
    return out


def summarize(rows: list[dict], sessions: dict[tuple, object], level: str, x: float, event_e: float,
              label: str = "mfe_close") -> dict:
    """`sessions`: (symbol, day) → SessionOutcome (değerlendirilen tüm seanslar)."""
    alerts = first_alerts(rows, level)
    events = {k for k, o in sessions.items() if o.max_runup >= event_e}
    non_events = set(sessions) - events
    tp = [k for k, r in alerts.items() if getattr(r["label"], label) is not None and getattr(r["label"], label) >= x]
    caught = [k for k in events if k in alerts and alerts[k]["t"] <= sessions[k].high_time]
    fp_sessions = [k for k in non_events if k in alerts]
    done = []
    for k, r in alerts.items():
        o, lab = sessions[k], r["label"]
        if k in events and lab.entry is not None and o.high > lab.low_before:
            done.append((lab.entry - lab.low_before) / (o.high - lab.low_before))
    minutes = [r["t"].hour * 60 + r["t"].minute for r in alerts.values()]
    per_asset = defaultdict(lambda: [0, 0, 0])  # alarm, isabet, seans
    for k in sessions:
        per_asset[k[0]][2] += 1
    for k in alerts:
        per_asset[k[0]][0] += 1
    for k in tp:
        per_asset[k[0]][1] += 1
    n_alerts = len(alerts)
    return {
        "level": level, "label": label, "x": x, "event_e": event_e,
        "sessions": len(sessions), "event_sessions": len(events),
        "alert_sessions": n_alerts,
        "alert_day_ratio": round(n_alerts / len(sessions), 4) if sessions else None,
        "precision": round(len(tp) / n_alerts, 4) if n_alerts else None,
        "recall": round(len(caught) / len(events), 4) if events else None,
        "false_positive_rate": round(len(fp_sessions) / len(non_events), 4) if non_events else None,
        "specificity": round(1 - len(fp_sessions) / len(non_events), 4) if non_events else None,
        "missed_events": len(events) - len(caught),
        "alert_evaluations_per_session": round(sum(RANK[r["final_level"]] >= RANK[level] for r in rows)
                                               / len(sessions), 3) if sessions else None,
        "median_first_alert_time": (f"{int(median(minutes)) // 60:02d}:{int(median(minutes)) % 60:02d}"
                                    if minutes else None),
        "median_move_completed": round(median(done), 3) if done else None,
        "median_future_mfe_pct": round(median(r["label"].mfe_close for r in alerts.values()
                                              if r["label"].mfe_close is not None) * 100, 3) if alerts else None,
        "per_asset": {s: {"alert_sessions": a, "hits": h, "sessions": n} for s, (a, h, n) in sorted(per_asset.items())},
        "max_asset_share_of_alerts": (round(max(a for a, _, _ in per_asset.values()) / n_alerts, 3)
                                      if n_alerts else None),
    }


def base_rate(rows: list[dict], x: float, label: str = "mfe_close") -> float | None:
    vals = [getattr(r["label"], label) for r in rows if r["status"] == ma.STATUS_OK
            and getattr(r["label"], label) is not None]
    return round(sum(v >= x for v in vals) / len(vals), 4) if vals else None
