"""Erken momentum fizibilite denetimi — olay zaman çizgisi, gecikme ayrıştırması ve FP/FN sınıflamaları.

Saf yardımcılar (YALNIZ araştırma). Gelecek bilgi (seans tepesi, MFE, kapanış getirisi, sonraki satırlar) yalnız
DEĞERLENDİRME/SINIFLAMA için kullanılır; hiçbir alarm kuralına girdi olmaz.

Zaman kavramları (UTC ns):
* bilgi zamanı = kullanılan son 5 dk barın BİTİŞİ (gecikmesiz sağlayıcıda alarmın görülebileceği en erken an);
* görünür zaman = bilgi zamanı + sağlayıcı gecikmesi (Yahoo BIST ≈ 15 dk).
"""

from __future__ import annotations

import numpy as np

MIN_NS = 60_000_000_000
BAR_MINUTES = 5
LEAD_TARGET = 0.5  # "gerçekten erken" sınırı: hareketin ilk yarısında alarm

# Dokunulmamış final dilimi (Round 2): bu artefaktlar fizibilite çalışmasında AÇILAMAZ.
FORBIDDEN_ARTIFACTS = ("merged_new", "ext_new", "r1_new", "final.json", "final_candidate")
UNTOUCHED_FINAL_ERROR = "Untouched final is forbidden in feasibility study"
CONSUMED_FINAL_ERROR = "Consumed final cannot be reused for candidate selection"

_SELECTION_DEPTH = 0  # >0: aday seçimi/eşik/sıralama kodu çalışıyor


class candidate_selection:
    """Aday seçimi bağlamı: içindeyken tüketilmiş final (postmortem yolu dahil) açılamaz."""

    def __enter__(self):
        global _SELECTION_DEPTH
        _SELECTION_DEPTH += 1
        return self

    def __exit__(self, *exc):
        global _SELECTION_DEPTH
        _SELECTION_DEPTH -= 1
        return False


def selection_active() -> bool:
    return _SELECTION_DEPTH > 0


def guard_artifact(name: str) -> str:
    if any(f in name for f in FORBIDDEN_ARTIFACTS):
        raise RuntimeError(f"{UNTOUCHED_FINAL_ERROR}; {CONSUMED_FINAL_ERROR}")
    return name


def guard_rows(rows: list[dict], untouched_assets, final_days) -> None:
    """Dokunulmamış varlık VEYA final tarihi içeren satır görülürse dur (sessizce süzme yok)."""
    bad_assets = set(untouched_assets)
    if any(r["symbol"] in bad_assets for r in rows):
        raise RuntimeError(f"{UNTOUCHED_FINAL_ERROR}; {CONSUMED_FINAL_ERROR}")
    finals = set(final_days)
    if any(r["day"] in finals for r in rows):
        raise RuntimeError(f"{UNTOUCHED_FINAL_ERROR}; {CONSUMED_FINAL_ERROR}")


# ------------------------------------------------------------------ zaman çizgisi
def lead_fraction(entry: float, run_low: float, high: float) -> float | None:
    span = high - run_low
    if not np.isfinite(entry) or not span > 0:
        return None
    return max(0.0, float((entry - run_low) / span))


def first_before(info_ns: np.ndarray, mask: np.ndarray, peak_ns: int) -> int | None:
    """Tepeden önce (bilgi zamanı ≤ tepe barı başlangıcı) koşulun ilk sağlandığı satır (yerel indeks)."""
    hit = np.flatnonzero(mask & (info_ns <= peak_ns))
    return int(hit[0]) if len(hit) else None


def event_timeline(info_ns: np.ndarray, masks: dict[str, np.ndarray], move_start_ns: int, peak_ns: int) -> dict:
    """Tek olay seansı için her kanıtın ilk (tepe öncesi) bilgi zamanı. Girdi satırları zaman sıralı olmalı."""
    out = {"move_start": int(move_start_ns), "peak": int(peak_ns)}
    for name, mask in masks.items():
        j = first_before(info_ns, mask, peak_ns)
        out[name] = None if j is None else int(info_ns[j])
    return out


def decompose_delay(move_start_ns: int, evidence_info_ns: int | None, raw_info_ns: int | None,
                    confirmed_info_ns: int | None, provider_delay_min: float) -> dict | None:
    """Toplam gecikme = özellik oluşumu + bar tamamlanma + eşik/kapı + doğrulama + sağlayıcı (dakika).

    Toplam, hareket başlangıcından (dip barı başlangıcı) doğrulanmış alarmın GÖRÜNÜR olduğu ana kadardır.
    """
    if evidence_info_ns is None or raw_info_ns is None or confirmed_info_ns is None:
        return None
    feature = (evidence_info_ns - BAR_MINUTES * MIN_NS - move_start_ns) / MIN_NS
    gating = (raw_info_ns - evidence_info_ns) / MIN_NS
    confirmation = (confirmed_info_ns - raw_info_ns) / MIN_NS
    total = (confirmed_info_ns - move_start_ns) / MIN_NS + provider_delay_min
    return {"D_feature_formation": feature, "A_bar_completion": float(BAR_MINUTES), "E_threshold_gating": gating,
            "C_confirmation": confirmation, "B_provider": float(provider_delay_min), "total": total}


def classify_timing(evidence_lead: float | None, d0_raw_lead: float | None, d15_raw_lead: float | None,
                    d15_alert_lead: float | None, target: float = LEAD_TARGET) -> str:
    """Olay başına (lead = hareketin alınmış kısmı; erken = tepe öncesi ve lead < hedef):

    * EARLY_OK: gerçekçi (15 dk) doğrulanmış alarm erken;
    * DATA_LATE: fiyat kanıtı kaynakta (gecikmesiz) bile erken oluşmuyor;
    * ENGINE_LATE: kanıt erken; ya eşik/kapı gecikmesizken bile ham alarmı geciktiriyor ya da 15 dk gecikmeli ham
      (1/1) alarm hâlâ erken ama doğrulama onu geç yapıyor;
    * MIXED: kanıt ve gecikmesiz ham alarm erken; 15 dk sağlayıcı gecikmesi tek başına ham alarmı geç yapıyor
      (doğrulama da eklenebilir).
    """
    def early(x):
        return x is not None and x < target
    if early(d15_alert_lead):
        return "EARLY_OK"
    if not early(evidence_lead):
        return "DATA_LATE"
    if not early(d0_raw_lead) or early(d15_raw_lead):
        return "ENGINE_LATE"
    return "MIXED"


# ------------------------------------------------------------------ sınıflamalar
FP_ORDER = ("LOCKED_OR_ILLIQUID_HISTORY", "BENCHMARK_SHOCK", "BROAD_MARKET_MOVE", "GAP_THEN_FADE",
            "BREAKOUT_FAILURE", "PRICE_SPIKE_NO_VOLUME", "VOLUME_SPIKE_NO_CONTINUATION", "SHORT_LIVED_ACCELERATION",
            "LATE_DAY_NOISE")
FN_ORDER = ("BASELINE_UNAVAILABLE", "ABRUPT_VERTICAL_JUMP", "NO_EARLY_PRICE_EVIDENCE", "NO_VOLUME_CONFIRMATION",
            "FEATURE_THRESHOLD", "PROVIDER_DELAY", "CONFIRMATION_DELAY", "BENCHMARK/CROSS_SECTION_GATE")


def _primary_secondary(flags: dict[str, bool], order: tuple[str, ...]) -> tuple[str, list[str]]:
    on = [k for k in order if flags.get(k)]
    return (on[0], on[1:]) if on else ("OTHER", [])


def classify_fp(flags: dict[str, bool]) -> tuple[str, list[str]]:
    return _primary_secondary(flags, FP_ORDER)


def classify_fn(flags: dict[str, bool]) -> tuple[str, list[str]]:
    return _primary_secondary(flags, FN_ORDER)


def fp_flags(*, locked: bool, volume_missing: bool, regime_shock: bool, rel_ret_z_3: float, gap_pct: float,
             ret_close: float, breakout: float, volume_anomaly: float, relvol_3: float, mfe_close: float,
             accel: float, accel_next_min: float, visible_minute: float, evidence_threshold: float = 0.5,
             x: float = 0.03) -> dict[str, bool]:
    """Yanlış pozitif ilk alarm satırının bayrakları (NaN = bayrak yok)."""
    def f(v, default):
        return default if v is None or not np.isfinite(v) else v
    return {
        "LOCKED_OR_ILLIQUID_HISTORY": bool(locked or volume_missing),
        "BENCHMARK_SHOCK": bool(regime_shock),
        "BROAD_MARKET_MOVE": f(rel_ret_z_3, 9.0) < 1.0,
        "GAP_THEN_FADE": f(gap_pct, 0.0) >= 1.0 and f(ret_close, 0.0) < 0,
        "BREAKOUT_FAILURE": f(breakout, 0.0) >= evidence_threshold and f(ret_close, 0.0) < 0,
        "PRICE_SPIKE_NO_VOLUME": f(volume_anomaly, 0.0) < evidence_threshold,
        "VOLUME_SPIKE_NO_CONTINUATION": f(relvol_3, 0.0) >= 2.0 and f(mfe_close, 0.0) < 0.01,
        "SHORT_LIVED_ACCELERATION": f(accel, -9.0) >= 0.5 and f(accel_next_min, 9.0) <= 0 and f(mfe_close, 0.0) < x,
        "LATE_DAY_NOISE": visible_minute >= 17 * 60,
    }
