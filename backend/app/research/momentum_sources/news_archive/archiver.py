"""İleriye dönük haber arşivleme çalıştırıcısı (ham toplama; momentum sonucu hesaplanmaz).

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.news_archive.archiver run --sources foreks,google --max-symbols 10

* Varsayılan yalnız Foreks (tek RSS isteği). Sembol başına kaynaklar (Google News, Yahoo News) açıkça
  `--max-symbols` ile sınırlanır ve istekler arasında bekler (saldırgan kazıma yok). KAP yapılandırılmadıysa
  `KAP_SOURCE_NOT_CONFIGURED` hatası olarak kaydedilir.
* Tekil çalışma: OS dosya kilidi `store/locks/news_archive.lock` (süreç ölünce OS bırakır → bayat kilit engellemez).
  Kilit tutuluyorsa `SKIPPED_ALREADY_RUNNING`, çıkış 0.
* Log: `store/logs/news_archive_YYYY-MM-DD.log` (JSON satırı, gizli bilgi yok). Çıkış: 0 tamam/atlandı, 3 bir
  kaynak başarısız.
* `received_at` = gerçek alım anı (sağlayıcının çağrı anı); `published_at` kaynağın orijinal zamanı. Geçmiş tarihli
  RSS öğesi bugün alındıysa received_at = bugün; ikisi asla birbirinin yerine konmaz.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector.ops import AlreadyRunning, SingletonLock, log_line
from app.research.momentum_sources import holdout
from app.research.momentum_sources.news_archive import adapters as ad
from app.research.momentum_sources.storage import DEFAULT_ROOT, SecondaryStore

STORE_DIR = DEFAULT_ROOT.parent
LOCK_PATH = STORE_DIR / "locks" / "news_archive.lock"
LOG_DIR = STORE_DIR / "logs"
RAW_DIR = STORE_DIR / "raw"  # ham yanıtlar (içerik adresli), Git dışı
EXIT_OK, EXIT_PARTIAL = 0, 3


def run(adapters, store: SecondaryStore, now_fn=lambda: datetime.now(timezone.utc)) -> dict:
    out = {}
    for a in adapters:
        started = now_fn()
        assert holdout.raw_collection_allowed(started.date())  # ham toplama serbest; sonuç hesabı yok
        run_id = store.begin_run(a.provider, "news_archive", {"requests": a.requests_per_run}, started)
        try:
            items = a.fetch()
        except Exception as e:  # sağlayıcı hatası kaydedilir, veri uydurulmaz
            store.log_failure(run_id, a.provider, now_fn(), e)
            finished = now_fn()
            store.finish_run(run_id, finished, "FAILED", {"error": type(e).__name__})
            out[a.provider] = {"status": "FAILED", "run_id": run_id, "started_at": started.isoformat(),
                               "finished_at": finished.isoformat(), "error": str(e)[:300], "failures": 1}
            continue
        res = Counter(store.add_news(i, run_id) for i in items)
        stats = getattr(a, "last_stats", {}) or {}
        summary = {"records": len(items), "items_inserted": res["NEW"], "duplicates": res["DUPLICATE"],
                   "duplicate_conflicts": res["DUPLICATE_CONFLICT"], "failures": res["DUPLICATE_CONFLICT"],
                   "known_conflict_repeats": res["DUPLICATE_CONFLICT_KNOWN"],
                   "items_received": stats.get("items_received", len(items)),
                   "rss_items_in_feed": stats.get("rss_items_in_feed"),
                   "items_resolved_to_universe": stats.get("items_resolved_to_universe"),
                   "raw_response_sha256": stats.get("raw_response_sha256"),
                   "production_provider_items": stats.get("production_provider_items"),
                   "symbols_resolved": stats.get("symbols_resolved", len({i.symbol for i in items})),
                   "symbols_unresolved": stats.get("items_unresolved_or_near_duplicate"),
                   "oldest_published_at": min((i.published_at for i in items if i.published_at), default=None),
                   "newest_published_at": max((i.published_at for i in items if i.published_at), default=None),
                   "retrieved_at": max((i.received_at for i in items), default=None)}
        finished = now_fn()
        store.finish_run(run_id, finished, "COMPLETED", summary)
        out[a.provider] = {"status": "COMPLETED", "run_id": run_id, "started_at": started.isoformat(),
                           "finished_at": finished.isoformat(), **summary}
    return out


def build_adapters(sources: list[str], max_symbols: int) -> list:
    universe = list(mm.load()["config"]["universe"])
    table = {"foreks": lambda: ad.ForeksArchiveAdapter(universe, raw_dir=RAW_DIR / "foreks"),
             "google": lambda: ad.GoogleNewsArchiveAdapter(universe, max_symbols),
             "yahoo": lambda: ad.YahooNewsArchiveAdapter(universe, max_symbols),
             "kap": lambda: ad.KapArchiveAdapter()}
    return [table[s]() for s in sources]


def invoke(sources: list[str], max_symbols: int = 0, root=DEFAULT_ROOT, lock_path=LOCK_PATH, log_dir=LOG_DIR,
           adapters=None, now_fn=lambda: datetime.now(timezone.utc)) -> tuple[int, dict]:
    """Kilitli tek çağrı + log satırı. (çıkış kodu, sonuç)."""
    started = now_fn()
    log_name = f"news_archive_{started.astimezone(ISTANBUL_TZ).date().isoformat()}.log"
    try:
        with SingletonLock(lock_path):
            store = SecondaryStore(root)
            try:
                res = run(adapters if adapters is not None else build_adapters(sources, max_symbols), store, now_fn)
            finally:
                store.close()
    except AlreadyRunning:
        rec = {"timestamp": now_fn().isoformat(), "status": "SKIPPED_ALREADY_RUNNING", "exit_code": EXIT_OK,
               "sources": sources}
        log_line(log_dir, log_name, rec)
        return EXIT_OK, rec
    code = EXIT_PARTIAL if any(v["status"] != "COMPLETED" for v in res.values()) else EXIT_OK
    for provider, v in res.items():
        log_line(log_dir, log_name, {
            "timestamp": now_fn().isoformat(), "run_id": v.get("run_id"), "provider": provider,
            "started_at": v.get("started_at"), "finished_at": v.get("finished_at"), "exit_code": code,
            "status": v["status"], **{k: v.get(k) for k in ("items_received", "items_inserted", "duplicates",
                                                            "duplicate_conflicts", "failures", "symbols_resolved",
                                                            "symbols_unresolved", "rss_items_in_feed",
                                                            "items_resolved_to_universe")},
            "error": v.get("error")})
    return code, res


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["run"])
    p.add_argument("--sources", default="foreks")
    p.add_argument("--max-symbols", type=int, default=0)
    args = p.parse_args(argv)
    code, res = invoke([s.strip() for s in args.sources.split(",") if s.strip()], args.max_symbols)
    print(json.dumps({"exit_code": code, "result": res}, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
