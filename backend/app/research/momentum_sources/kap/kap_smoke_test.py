"""Resmi KAP API kısa, sınırlı smoke testi — HAZIRLIK. Resmi doküman + yetki + API anahtarı olmadan ÇALIŞMAZ.

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.kap.kap_smoke_test

Beklenen gelecek akış (en fazla MAX_RECORDS bildirim; veritabanı yazımı yalnız --persist ile):
    1. yapılandırmayı doğrula         2. lastDisclosureIndex
    3. çok küçük bildirim listesi     4. ham şemayı incele
    5. resmi yayın zamanlarını doğrula 6. bildirim kimliklerini doğrula
    7. üye/menkul kıymet kimliğini doğrula 8. bağlantıyı kapat
Yapılandırma eksikse çıkış kodu 2, ağ çağrısı yok.
"""

from __future__ import annotations

import json
import sys

from app.research.momentum_sources.kap import field_mapping as fm
from app.research.momentum_sources.kap.adapter import KapOfficialAdapter
from app.research.momentum_sources.kap.config import KapConfigurationRequired

MAX_RECORDS = 5
STEPS = ("validate_configuration", "lastDisclosureIndex", "small_disclosure_list", "inspect_raw_schema",
         "verify_publication_timestamps", "verify_disclosure_ids", "verify_member_security_identity", "disconnect")


def main(argv=None) -> int:
    persist = "--persist" in (argv if argv is not None else sys.argv[1:])
    adapter = KapOfficialAdapter()
    try:
        adapter.config.require(fm.endpoints_mapped())
    except KapConfigurationRequired as e:
        print(json.dumps({"status": "NOT ACTIVE", "access_state": adapter.status()["access_state"], "reason": str(e),
                          "steps": STEPS, "network_calls": 0, "persist": persist}, ensure_ascii=False))
        return 2
    idx = adapter.last_disclosure_index()
    rows = adapter.disclosures_after(idx - MAX_RECORDS, MAX_RECORDS)
    raise NotImplementedError(f"schema/timestamp/id/identity verification pending official docs ({len(rows)} rows)")


if __name__ == "__main__":
    sys.exit(main())
