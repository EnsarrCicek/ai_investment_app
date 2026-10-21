"""Görünürlük sondası — "Yahoo BIST ~15 dk gecikmeli" varsayımını gerçek first_seen ölçümüyle sınamak (YALNIZ araştırma).

* Manifestte dondurulmuş deterministik alt küme (5m: 10 varlık + XU100; 1m: ilk 4 + XU100), ~5 dk aralık,
  yalnız hafta içi 09:55–18:30 TSİ. Her istek period=1d (en küçük yanıt).
* Her gözlem: probe_time, en son bar (oluşan dahil), en son TAMAMLANMIŞ bar ve gecikmesi
  (probe_time − bar_end), bu sondada ilk kez görülen tamamlanmış barların medyan first_seen gecikmesi, kimlik,
  yanıt hash'i. Gelen barlar aynı append-only arşive yazılır (first_seen = bu sonda).
* Ardışık hatalarda üstel geri çekilme (en çok 30 dk); sağlayıcıya ek yük bindirilmez.
"""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timezone
from statistics import median
from typing import Callable

import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector.collector import CollectorSource, roles
from app.research.momentum_collector.storage import (INTERVAL_NS, Archive, IngestCounts, _starts_ns,
                                                       partial_flags, response_hash, ts_ns, utc_iso)

PROBE_PERIOD = "1d"
WINDOW = (dtime(9, 55), dtime(18, 30))
MAX_BACKOFF_SECONDS = 1800


def probe_plan(m: dict) -> list[tuple[str, str]]:
    p = m["config"]["visibility_probe_policy"]
    b = m["config"]["benchmark"]
    return ([(s, "5m") for s in [*p["subset_5m"], b]] + [(s, "1m") for s in [*p["subset_1m"], b]])


def in_window(now: datetime) -> bool:
    local = now.astimezone(ISTANBUL_TZ)
    return local.weekday() < 5 and WINDOW[0] <= local.time() <= WINDOW[1]


def probe_once(archive: Archive, source: CollectorSource, m: dict,
               now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    if archive.role != "primary":
        raise RuntimeError("sonda yalnız birincil depoya yazar")
    plan = probe_plan(m)
    role = roles(m)
    run_id = archive.begin_run("PROBE", {"plan": plan, "manifest_sha256": m["sha256"]}, now())
    ok, failed, errors, identity_fail = set(), set(), [], set()
    total = IngestCounts()
    for symbol, interval in plan:
        try:
            res = source.fetch(symbol, interval, PROBE_PERIOD)
        except Exception as exc:
            archive.log_failure(run_id, symbol, interval, {"interval": interval, "period": PROBE_PERIOD}, now(), exc)
            failed.add(symbol)
            errors.append({"symbol": symbol, "interval": interval, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        if res.identity_check != "MATCH":
            identity_fail.add(f"{symbol}:{res.identity_check}")
        counts = archive.ingest(res, run_id, mode="PROBE", universe_role=role[symbol], manifest=m)
        total.add(counts)
        archive.record_probe(observation(res, run_id, counts.new_keys))
        ok.add(symbol)
    summary = {"run_id": run_id, "mode": "PROBE", "manifest_sha256": m["sha256"],
               "symbols_requested": sorted({s for s, _ in plan}), "symbols_succeeded": sorted(ok - failed),
               "symbols_failed": sorted(failed), "intervals": sorted({i for _, i in plan}),
               "request_count": len(plan), "new_bars": total.new_bars, "duplicate_bars": total.duplicate_bars,
               "revisions": total.revisions, "partial_observations": total.partial_observations,
               "finalizations": total.finalizations, "invalid_rows": total.invalid_rows,
               "identity_failures": sorted(identity_fail), "errors": errors}
    return archive.finish_run(run_id, summary, now())


def observation(res, run_id: str, new_keys: list[tuple[int, int]]) -> dict:
    """Tek yanıtın görünürlük gözlemi (saf). Gecikmeler saniye; tamamlanmamış son bar ayrı raporlanır."""
    starts = _starts_ns(res.bars.sort_index())
    probe_ns = ts_ns(res.retrieved_at)
    step = INTERVAL_NS[res.interval]
    out = {"run_id": run_id, "probe_time": res.retrieved_at.astimezone(timezone.utc).isoformat(),
           "probe_ns": probe_ns, "symbol": res.symbol, "interval": res.interval,
           "identity_check": res.identity_check, "response_hash": response_hash(res),
           "new_final_bars": len(new_keys),
           "new_final_latency_median_seconds": (median((probe_ns - end) / 1e9 for _, end in new_keys)
                                                if new_keys else None)}
    if len(starts):
        partial = partial_flags(starts, res.interval, res.retrieved_at)
        last = int(starts.max())
        finals = starts[~partial]
        out.update({"latest_bar_start": utc_iso(last), "latest_bar_end": utc_iso(last + step),
                    "latest_is_partial": int(partial[starts.argmax()])})
        if len(finals):
            lf = int(finals.max())
            out.update({"latest_final_bar_start": utc_iso(lf), "latest_final_bar_end": utc_iso(lf + step),
                        "latest_final_latency_seconds": (probe_ns - lf - step) / 1e9})
    return out


def probe_loop(archive: Archive, source: CollectorSource, m: dict, *, max_runs: int | None = None,
               now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
               sleep: Callable[[float], None] = time.sleep) -> int:
    """Seans penceresinde ~5 dk'da bir sonda. Tüm istekler başarısızsa geri çekilme ikiye katlanır."""
    cadence = m["config"]["visibility_probe_policy"]["cadence_seconds"]
    backoff, runs = cadence, 0
    while max_runs is None or runs < max_runs:
        t = now()
        if not in_window(t):
            local = t.astimezone(ISTANBUL_TZ)
            if local.weekday() >= 5 or local.time() > WINDOW[1]:
                return runs
            sleep(min(cadence, 60))
            continue
        summary = probe_once(archive, source, m, now)
        runs += 1
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS) if not summary["symbols_succeeded"] else cadence
        elapsed = (now() - t).total_seconds()
        sleep(max(0.0, backoff - elapsed))
    return runs


def latency_summary(archive: Archive) -> pd.DataFrame:
    """Sonda gözlemleri: aralık başına en son tamamlanmış bar gecikmesinin dağılımı (s)."""
    df = pd.read_sql_query("SELECT interval, latest_final_latency_seconds AS s FROM probe_observations WHERE "
                           "latest_final_latency_seconds IS NOT NULL", archive.db)
    if df.empty:
        return df
    return df.groupby("interval")["s"].describe(percentiles=[0.1, 0.5, 0.9])
