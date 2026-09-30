"""Dondurulmuş 100 sembollük evrende eski Yahoo (düzeltilmiş) ile resmî BIST bülteni (ham) veri kalitesi kapsamı.

Saf karşılaştırma fonksiyonları + ağsız koşucu. Fiyat temelleri farklıdır: sabit bir ölçek oranı TEK BAŞINA hata
DEĞİLDİR. Sınıflar (önceden sabitlendi):
  * NO_DIFF_IN_SCOPE          : karşılaştırılabilir tüm seanslarda O/H/L/C oranı 1 (tolerans içinde)
  * SCALE_DIFF_UNEXPLAINED    : seans içi O/H/L/C oranları tutarlı, fakat oran 1 değil (ekonomik açıklaması incelenmedi)
  * FIELD_INCONSISTENCY_CANDIDATE : aynı seansta O/H/L/C oranları birbirinden tolerans ötesinde farklı
  * MISSING_OR_NOT_COMPARABLE : beklenen seansta resmî veya Yahoo satırı yok / geçersiz
Hiçbir sınıf serinin tamamına doğruluk onayı vermez; adaylar CONFIRMED kayda otomatik taşınmaz.
Tolerans: dosya hassasiyeti — Yahoo değerleri ~7 anlamlı basamaklı (float32 kökenli, göreli ~6e-8); resmî değerler
ondalıklı metin. Göreli tolerans 1e-6 (~16×float32 epsilonu), tarama öncesinde manifeste yazılır.
Hacim: resmî TOPLAM ISLEM ADEDI ile Yahoo Volume birim/düzeltme temeli doğrulanmadığından yalnızca bilgi olarak raporlanır.
"""

from __future__ import annotations

import math
from decimal import Decimal

REL_TOL = Decimal("1e-6")
FIELDS = ("open", "high", "low", "close")


def _valid_prices(p: dict) -> bool:
    try:
        vals = [Decimal(str(p[f])) for f in FIELDS]
    except Exception:  # noqa: BLE001
        return False
    if not all(v.is_finite() and v > 0 for v in vals):
        return False
    o, h, l, c = vals
    return l <= o <= h and l <= c <= h


def _valid_volume(v) -> bool:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x >= 0


def compare_session(yahoo: dict | None, official: dict | None) -> dict:
    """yahoo/official: {'open','high','low','close','volume'} (metin veya sayı). Doldurma yapılmaz."""
    if official is None:
        return {"status": "OFFICIAL_MISSING"}
    if yahoo is None:
        return {"status": "YAHOO_MISSING"}
    problems = []
    if not _valid_prices(official):
        problems.append("OFFICIAL_OHLC_INVALID")
    if not _valid_prices(yahoo):
        problems.append("YAHOO_OHLC_INVALID")
    if not _valid_volume(official.get("volume")) or not _valid_volume(yahoo.get("volume")):
        problems.append("VOLUME_INVALID")
    if any(p.endswith("OHLC_INVALID") for p in problems):
        return {"status": "NOT_COMPARABLE", "problems": problems}
    ratios = {f: Decimal(str(yahoo[f])) / Decimal(str(official[f])) for f in FIELDS}
    lo, hi = min(ratios.values()), max(ratios.values())
    consistent = (hi / lo - 1) <= REL_TOL
    scale = ratios["close"]
    out = {"status": "COMPARED", "ratios": {f: str(v.quantize(Decimal("0.000001"))) for f, v in ratios.items()},
           "fields_consistent": consistent, "scale_is_one": abs(scale - 1) <= REL_TOL, "problems": problems}
    ov, yv = Decimal(str(official.get("volume"))), Decimal(str(yahoo.get("volume")))
    out["volume_ratio_info"] = str((yv / ov).quantize(Decimal("0.000001"))) if ov > 0 else None
    return out


def scale_segments(compared: list[tuple[str, dict]]) -> list[dict]:
    """Ardışık seanslarda (alanları tutarlı) kapanış oranı tolerans içinde aynıysa tek segment."""
    segs = []
    for day, r in compared:
        if r.get("status") != "COMPARED" or not r["fields_consistent"]:
            continue
        ratio = Decimal(r["ratios"]["close"])
        if segs and abs(ratio / Decimal(segs[-1]["ratio"]) - 1) <= REL_TOL * 10:
            segs[-1]["to"] = day
            segs[-1]["sessions"] += 1
        else:
            segs.append({"from": day, "to": day, "ratio": str(ratio), "sessions": 1})
    return segs


def classify_symbol(compared: list[tuple[str, dict]]) -> dict:
    missing = [d for d, r in compared if r["status"] != "COMPARED"]
    inconsistent = [d for d, r in compared if r["status"] == "COMPARED" and not r["fields_consistent"]]
    scaled = [d for d, r in compared if r["status"] == "COMPARED" and r["fields_consistent"] and not r["scale_is_one"]]
    findings = []
    if inconsistent:
        findings.append("FIELD_INCONSISTENCY_CANDIDATE")
    if scaled:
        findings.append("SCALE_DIFF_UNEXPLAINED")
    if missing:
        findings.append("MISSING_OR_NOT_COMPARABLE")
    if not findings:
        findings.append("NO_DIFF_IN_SCOPE")
    return {"findings": findings, "compared": sum(r["status"] == "COMPARED" for _, r in compared),
            "missing_or_not_comparable": missing, "field_inconsistency_dates": inconsistent, "scaled_dates": scaled,
            "scale_segments": scale_segments(compared)}
