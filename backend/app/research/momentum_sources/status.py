"""İkincil kaynak durum raporu — YALNIZ toplama sağlığı (model metriği YOK).

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.status

Rapor: sağlayıcı yapılandırıldı mı, yetenekler, son alım zamanı, gecikme istatistikleri, kimlik durumu, satır
sayıları, hatalar, depo bütünlüğü. Depo yoksa oluşturulmaz (salt okunur).
"""

from __future__ import annotations

import json

from app.research.momentum_sources import holdout
from app.research.momentum_sources.matriks.adapter import MatriksAdapter
from app.research.momentum_sources.news_archive import adapters as ad
from app.research.momentum_sources.storage import DB_NAME, DEFAULT_ROOT, SecondaryStore

FORBIDDEN_KEYS = ("precision", "recall", "fpr", "lead", "alert", "label", "event_v2", "candidate")


def _kap_status() -> dict:
    from app.research.momentum_sources.kap.adapter import KapOfficialAdapter
    st = KapOfficialAdapter().status()
    return {k: st[k] for k in ("access_state", "live_integration", "public_site_scraping", "missing")}


def report(root=DEFAULT_ROOT) -> dict:
    out = {"providers": {
        "matriks": MatriksAdapter().status(),
        "foreks_rss": {"configured": True, "kind": "public RSS via existing project provider (no credentials)"},
        "google_news_rss": {"configured": True, "kind": "public RSS search via existing project provider"},
        "yahoo_news": {"configured": True, "kind": "existing project provider (yfinance)"},
        "kap": {"configured": False, "status": ad.KAP_SOURCE_NOT_CONFIGURED, **_kap_status()}},
        "holdout_policy": {"raw_collection_allowed": holdout.RAW_COLLECTION_ALLOWED,
                           "outcome_analysis": "forbidden after pilot cutoff (HoldoutAccessError)"}}
    if not (root / DB_NAME).exists():
        out["storage"] = {"status": "NO_STORE_YET", "path": str(root / DB_NAME)}
        return out
    s = SecondaryStore(root, readonly=True)
    try:
        out["storage"] = {"status": "OK", "path": str(s.path), "integrity": s.integrity(), "stats": s.stats()}
    finally:
        s.close()
    return out


def main() -> int:
    print(json.dumps(report(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
