"""Erken momentum fizibilite denetimi — saf, vektörize yardımcılar (YALNIZ araştırma; üretim kodu değil).

* Eşik ızgarası yalnız ROC/Pareto yüzeyi içindir; sonuçtan üretim yapılandırması ÜRETİLMEZ.
* Gecikme simülasyonu: motor T anında yalnız `başlangıç ≤ T − gecikme − 5 dk` barlarını görür. Bu yüzden d dk
  gecikmeli değerlendirme, 15 dk gecikmeli değerlendirmenin (15 − d) dk ÖNCEYE kaydırılmışıdır: öznitelikler ve
  düzey dizisi aynıdır, yalnız alarmın gerçek zamanı (ve giriş fiyatı/etiketleri) değişir. (Üretim
  `compute_features` ile 360 örnekte doğrulandı; testte de denetlenir.)
* Doğrulama penceresi: seans içinde son n değerlendirmenin ≥k'si + şimdiki değerlendirme (seans öncesi = yok),
  üretim `confirm_level` ile aynı anlam.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

R1_WEIGHTS = {"price_impulse": 0.30, "volume_anomaly": 0.25, "breakout": 0.15, "range_expansion": 0.10,
              "reversal": 0.10, "vwap": 0.05}  # katalizör yok (events=None) → 0 katkı; toplam ağırlık 1.0


def confirm(raw: np.ndarray, seg_start: np.ndarray, k: int, n: int) -> np.ndarray:
    """Satırlar (seans, zaman) sıralı; `seg_start[i]` satır i'nin seansının ilk satır indeksi."""
    raw = raw.astype(bool)
    if n <= 1:
        return raw.copy()
    cs = np.concatenate([[0], np.cumsum(raw)])
    i = np.arange(len(raw))
    lo = np.maximum(i - n + 1, seg_start)
    return raw & ((cs[i + 1] - cs[lo]) >= k)


def first_alert_rows(final: np.ndarray, sess: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(seans kimlikleri, o seansın ilk alarm satırı). Satırlar seans içinde zamana göre sıralı olmalı."""
    idx = np.flatnonzero(final)
    if not len(idx):
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    uniq, pos = np.unique(sess[idx], return_index=True)
    return uniq, idx[pos]


@dataclass
class LabelArrays:
    """Bir gecikme senaryosu için satır başına gerçek zaman ve etiketler + seans sonuçları."""

    t_ns: np.ndarray  # satırın gerçek değerlendirme zamanı
    entry: np.ndarray
    mfe_close: np.ndarray
    ret_close: np.ndarray
    ok: np.ndarray  # durum OK
    sess_event: np.ndarray  # seans başına
    sess_high_ns: np.ndarray
    sess_high: np.ndarray
    sess_run_low: np.ndarray


def metrics(final: np.ndarray, sess: np.ndarray, lab: LabelArrays, x: float) -> dict:
    uniq, rows = first_alert_rows(final, sess)
    n_sess = len(lab.sess_event)
    events = lab.sess_event
    n_ev, n_non = int(events.sum()), int((~events).sum())
    hit = np.nan_to_num(lab.mfe_close[rows], nan=-1) >= x
    ev = events[uniq]
    caught = ev & (lab.t_ns[rows] <= lab.sess_high_ns[uniq])
    span = lab.sess_high[uniq] - lab.sess_run_low[uniq]
    lead = np.maximum(0.0, (lab.entry[rows] - lab.sess_run_low[uniq]) / np.where(span > 0, span, np.nan))
    leads = lead[caught & np.isfinite(lead)]
    mins = (lab.t_ns[rows] // 60_000_000_000 + 180) % 1440  # UTC → İstanbul (+3, yaz saati yok)
    return {"alert_sessions": int(len(uniq)), "alert_day_ratio": len(uniq) / n_sess if n_sess else None,
            "precision": float(hit.mean()) if len(uniq) else None,
            "recall": float(caught.sum() / n_ev) if n_ev else None,
            "false_positive_rate": float((~ev).sum() / n_non) if n_non else None,
            "lead_fraction_median": float(np.median(leads)) if len(leads) else None,
            "median_first_alert_minute": float(np.median(mins)) if len(mins) else None,
            "caught_events": int(caught.sum()), "events": n_ev}


def pareto_mask(points: list[dict], maximize=("recall", "precision"), minimize=("false_positive_rate",
                                                                                 "lead_fraction_median")
                ) -> np.ndarray:
    """Baskın (dominated) olmayan noktalar. Eksik değer en kötü kabul edilir."""
    def vec(p):
        return [(p[k] if p[k] is not None else -np.inf) for k in maximize] + \
               [-(p[k] if p[k] is not None else np.inf) for k in minimize]
    m = np.array([vec(p) for p in points], dtype=float)
    keep = np.ones(len(points), dtype=bool)
    for i in range(len(points)):
        if not keep[i]:
            continue
        dominated = np.all(m >= m[i], axis=1) & np.any(m > m[i], axis=1)
        if dominated.any():
            keep[i] = False
    return keep


def best_under(points: list[dict], objective: str, maximize: bool, constraints: dict) -> dict | None:
    """Kısıtlar ({metrik: (op, değer)}) altında hedef metriği en iyileyen nokta (yalnız raporlama)."""
    ok = []
    for p in points:
        good = True
        for k, (op, v) in constraints.items():
            val = p.get(k)
            if val is None or (op == "<=" and val > v) or (op == ">=" and val < v):
                good = False
                break
        if good and p.get(objective) is not None:
            ok.append(p)
    if not ok:
        return None
    return (max if maximize else min)(ok, key=lambda p: p[objective])
