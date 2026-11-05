"""İkincil veri için holdout politikası.

* HAM toplama her tarihte serbesttir (2026-11-02 sonrası dahil): kaynak kaydı, zaman damgası, gecikme, kimlik,
  satır sayısı, depolama bütünlüğü.
* SONUÇ analizi (V2 olayı, etiket, alarm, precision/recall/FPR/lead, aday sonucu) pilot kesiminden SONRAKİ hiçbir
  seans için hesaplanamaz → `HoldoutAccessError` (pilot manifesti kesimi; sessiz süzme yok).
"""

from __future__ import annotations

from datetime import date

from app.research.momentum_pilot import split as sp

RAW_COLLECTION_ALLOWED = True
OUTCOME_KINDS = ("v2_events", "labels", "alerts", "precision", "recall", "fpr", "lead", "candidate_outcome")


def raw_collection_allowed(day: date | str) -> bool:
    """Ham ileriye dönük toplama tarih kısıtı olmadan serbesttir (yalnız ham kayıt; sonuç hesabı ayrı korunur)."""
    return RAW_COLLECTION_ALLOWED


def assert_outcome_analysis_allowed(sessions, kind: str) -> None:
    if kind not in OUTCOME_KINDS:
        raise ValueError(f"bilinmeyen sonuç türü: {kind}")
    sp.HoldoutGuard(sp.load_manifest()).check_sessions([str(s) for s in sessions])


# Haberle birleştirilemeyecek (holdout tarihlerinde) sonuç alanları
FORBIDDEN_NEWS_JOINS = ("price_outcome", "v2_events", "peak", "mfe", "alerts", "lead", "candidate_results")


def assert_news_join_allowed(sessions, joined_fields) -> None:
    """Ham haber veri kalitesi için her tarihte okunabilir (birleştirme yok → serbest). Sonuç alanıyla
    birleştirme ise pilot kesimi sonrası her seans için `HoldoutAccessError`."""
    bad = [f for f in joined_fields if f in FORBIDDEN_NEWS_JOINS]
    unknown = [f for f in joined_fields if f not in FORBIDDEN_NEWS_JOINS]
    if unknown:
        raise ValueError(f"bilinmeyen birleştirme alanı: {unknown}")
    if bad:
        sp.HoldoutGuard(sp.load_manifest()).check_sessions([str(s) for s in sessions])
