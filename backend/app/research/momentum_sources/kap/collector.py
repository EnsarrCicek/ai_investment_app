"""İleriye dönük artımlı KAP toplama TASARIMI (ağ çağrısı yok; istemci soyut).

Akış (resmi `lastDisclosureIndex` + `disclosures` + `disclosureDetail` servisleri üzerinden):
    0. checkpoint yoksa: yalnız güncel indeks başlangıç olarak kaydedilir (BASELINE_ESTABLISHED; geçmiş doldurulmaz)
    1. son başarıyla arşivlenen bildirim indeksini (checkpoint) oku
    2. resmi lastDisclosureIndex'i sorgula
    3. yalnız daha yeni bildirimleri iste (sınırlı adet)
    4. gerekirse disclosureDetail
    5. değişmez kayıtları ekle
    6. checkpoint'i YALNIZ başarılı kalıcılaştırmadan SONRA ilerlet (append-only checkpoint satırı)
Bildirim kimliği semantiği (tekillik/monotonluk) resmi olarak doğrulanmadan çalışmaz.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.research.momentum_sources import holdout
from app.research.momentum_sources.kap import field_mapping as fm
from app.research.momentum_sources.kap.adapter import KapServiceClient
from app.research.momentum_sources.kap.config import KapConfigurationRequired
from app.research.momentum_sources.storage import SecondaryStore

MAX_RECORDS_PER_RUN = 200


def incremental_run(client: KapServiceClient, store: SecondaryStore, now_fn=lambda: datetime.now(timezone.utc),
                    max_records: int = MAX_RECORDS_PER_RUN, fetch_detail: bool = False,
                    id_semantics_confirmed: bool | None = None) -> dict:
    confirmed = fm.DISCLOSURE_ID_SEMANTICS_CONFIRMED if id_semantics_confirmed is None else id_semantics_confirmed
    if not confirmed:
        raise KapConfigurationRequired("disclosure ID / index semantics not officially confirmed")
    started = now_fn()
    assert holdout.raw_collection_allowed(started.date())  # ham toplama serbest; sonuç birleştirme yok
    run_id = store.begin_kap_run("incremental", {"max_records": max_records}, started)
    try:
        last = store.kap_checkpoint()
        remote = client.last_disclosure_index()
        if last is None:  # ileriye dönük başlangıç: geçmiş doldurulmaz, yalnız başlangıç indeksi kaydedilir
            store.add_kap_checkpoint(remote, run_id, now_fn())
            store.finish_kap_run(run_id, now_fn(), "BASELINE_ESTABLISHED", {"checkpoint": remote})
            return {"status": "BASELINE_ESTABLISHED", "checkpoint": remote, "remote_index": remote}
        if remote <= last:
            store.finish_kap_run(run_id, now_fn(), "NO_NEW_DISCLOSURES", {"checkpoint": last, "remote": remote})
            return {"status": "NO_NEW_DISCLOSURES", "checkpoint": last, "remote_index": remote}
        rows = client.disclosures_after(last, max_records)
        res = {"NEW": 0, "DUPLICATE": 0, "DUPLICATE_CONFLICT": 0, "DUPLICATE_CONFLICT_KNOWN": 0}
        for d in rows:
            if fetch_detail and d.disclosure_id:
                client.disclosure_detail(d.disclosure_id)  # ham detay ayrı saklanır (doküman gelince)
            res[store.add_kap_disclosure(d, run_id)] += 1
        persisted = [d.disclosure_index for d in rows if d.disclosure_index is not None]
        new_cp = max(persisted) if persisted else last
        if new_cp is not None and (last is None or new_cp > last):
            store.add_kap_checkpoint(new_cp, run_id, now_fn())  # yalnız kalıcılaştırmadan sonra
        summary = {"received": len(rows), **{k.lower(): v for k, v in res.items()}, "checkpoint_before": last,
                   "checkpoint_after": new_cp, "remote_index": remote}
        store.finish_kap_run(run_id, now_fn(), "COMPLETED", summary)
        return {"status": "COMPLETED", **summary}
    except Exception as e:
        store.log_kap_failure(run_id, now_fn(), e)
        store.finish_kap_run(run_id, now_fn(), "FAILED", {"error": type(e).__name__})
        raise
