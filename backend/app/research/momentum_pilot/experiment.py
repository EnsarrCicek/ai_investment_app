"""Momentum PILOT geliştirme — bölme manifesti ve pilot analizi (YALNIZ araştırma; toplayıcıya/üretime dokunmaz).

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment split
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment analyze
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_pilot.experiment mobile <momentum_shadow.db>

* split: toplayıcının FULL seans sınıflamasından (yalnız XU100 bar zaman meta verisi) pilot manifestini oluşturur /
  sona ekleyerek günceller. Fiyat/olay/alarm okunmaz.
* analyze: YALNIZ manifestteki pilot seansları (+ başlangıç öncesi ısınma seansları). Her metrik
  "PILOT / DEVELOPMENT ONLY"; PASS/FAIL, aday dondurma, BUY/SELL/HOLD yok.
* mobile: dışa aktarılmış MOBILE_SHADOW veritabanını pilot seanslarında Windows ile karşılaştırır (birleştirme yok).
* Arşiv salt okunur açılır (SQLite `mode=ro`); toplayıcı çalışmaya devam eder.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time as clock
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from app.research.momentum_collector import integrity as ig
from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import storage as st
from app.research.momentum_final import candidate as cd
from app.research.momentum_final import experiment as mf
from app.research.momentum_pilot import analysis as an
from app.research.momentum_pilot import split as sp


class _ReadOnlyArchive:
    """`integrity.classify_sessions` için `.db` taşıyan salt okunur bağlantı."""

    def __init__(self, root: Path = st.PRIMARY_ROOT):
        self.db = sqlite3.connect(f"file:{(root / 'archive.sqlite').as_posix()}?mode=ro", uri=True)

    def close(self):
        self.db.close()


def session_classes(a) -> tuple[list[str], list[str]]:
    """(başlangıç ve sonrası FULL seanslar, başlangıç öncesi FULL ısınma seansları)."""
    m = mm.load()
    start = m["config"]["prospective_start_session"]
    sess = ig.classify_sessions(a, m["config"]["benchmark"])
    full = sp.observed_full_sessions(sess, start)
    warm = sorted(d for d, c in zip(sess["session_date"], sess["session_class"])
                  if c == "FULL" and d < start and not mm.in_consumed_final(date.fromisoformat(d)))
    return full, warm


def split_stage() -> dict:
    a = _ReadOnlyArchive()
    try:
        full, _ = session_classes(a)
    finally:
        a.close()
    m, changed = sp.refresh_manifest(full, mm.load(), datetime.now(timezone.utc))
    out = {"observed_full_sessions": full, "manifest_changed": changed, "sha256": m["sha256"], **m["manifest"]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def _write(name: str, payload) -> Path:
    sp.RUNS.mkdir(parents=True, exist_ok=True)
    path = sp.RUNS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def analyze_stage(workers: int = 7) -> dict:
    started = clock.perf_counter()
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    study = mm.load()
    c = study["config"]
    pilot = list(manifest["manifest"]["pilot_sessions"])
    a = _ReadOnlyArchive()
    try:
        _, warm = session_classes(a)
        sessions = warm + pilot
        symbols = list(c["universe"]) + [c["benchmark"]]
        b5 = sp.load_primary_bars(a.db, guard, sessions, "5m", symbols)
        b1 = sp.load_primary_bars(a.db, guard, sessions, "1m", symbols)
        rev5 = sp.load_primary_revisions(a.db, guard, pilot, "5m")
        rev1 = sp.load_primary_revisions(a.db, guard, pilot, "1m")
    finally:
        a.close()
    assert set(b5["source"]) == {sp.PRIMARY_SOURCE}
    data = {s: an.to_asset_data(s, g) for s, g in b5.groupby("symbol")}
    bench = data.pop(c["benchmark"])
    days = [date.fromisoformat(d) for d in pilot]
    rows = an.build_rows(data, bench, days, workers)
    p = an.PilotPanel(rows, {s: d.bars for s, d in data.items()})
    for d in an.DELAYS:
        p.build_labels(d)
    events, gap = an.build_events(p)
    cand = cd.load_frozen(mf.MANIFEST)["candidate"]
    rules = an.rule_masks(p, cand)
    pb5, pb1 = b5[b5["session_date"].isin(pilot)], b1[b1["session_date"].isin(pilot)]
    latency = an.latency_stats(pd.concat([pb5, pb1]))
    table = an.event_table(p, events, gap, rules, an.latency_by_asset_session(pb5))
    ev_by_key = {(sym, str(day), k): ev for (sym, day), evs in zip(p.sessions, events) for k, ev in enumerate(evs)}
    present = {d: sorted(set(pb5.loc[pb5["session_date"] == d, "symbol"]) & set(c["universe"])) for d in pilot}
    out = {
        "label": sp.PILOT_LABEL, "never": "PROSPECTIVE FINAL",
        "pilot_manifest_sha256": manifest["sha256"], "pilot_status": manifest["manifest"]["status"],
        "pilot_sessions": pilot, "warmup_sessions": warm, "access_cutoff": guard.cutoff,
        "label_v2_sha256": sp.LABEL_V2_SHA256, "alert_unit": an.lv.FIRST_ALERT,
        "data_source": sp.PRIMARY_SOURCE, "bar_values": "FIRST_SEEN (revisions not applied)",
        "coverage": {"assets_per_pilot_session": {d: len(v) for d, v in present.items()},
                     "missing_primary_assets": {d: sorted(set(c["universe"]) - set(v)) for d, v in present.items()},
                     "panel_asset_sessions": len(p.sessions), "rows": len(p.rows),
                     "rows_status_ok": int(p.ok.sum()),
                     "pilot_5m_bars": int(len(pb5)), "pilot_1m_bars": int(len(pb1)),
                     "pilot_5m_null_volume_bars": int(pb5["volume"].isna().sum()),
                     "pilot_revisions_5m": int(len(rev5)), "pilot_revisions_1m": int(len(rev1))},
        "event_census": an.lx.event_census(events, gap),
        "rules": {name: {"description": an.RULE_NAMES[name],
                         **{f"d{d}": an.rule_metrics(p, events, mask, d) for d in an.DELAYS}}
                  for name, mask in rules.items()},
        "early_moves": an.early_summary(table),
        "false_positives_d15": {name: an.fp_analysis(p, events, mask, 15) for name, mask in rules.items()},
        "timing_1m_vs_5m": an.timing_comparison(table, ev_by_key, pb5, pb1),
        "provider_latency_probe": latency,
        "event_table": table,
        "elapsed_seconds": round(clock.perf_counter() - started, 1)}
    path = _write(f"pilot_analysis_{guard.cutoff}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("event_table",)}, ensure_ascii=False, indent=1,
                     default=str))
    print("WRITTEN", path)
    return out


def mobile_stage(db_path: str | None) -> dict:
    manifest = sp.load_manifest()
    guard = sp.HoldoutGuard(manifest)
    pilot = list(manifest["manifest"]["pilot_sessions"])
    if not db_path or not Path(db_path).exists():
        out = {"status": "NO_MOBILE_EXPORT_AVAILABLE", "label": sp.PILOT_LABEL}
        print(json.dumps(out))
        return out
    a = _ReadOnlyArchive()
    mob = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        out = {"label": sp.PILOT_LABEL, "pilot_sessions": pilot}
        for iv in ("5m", "1m"):
            w = sp.load_primary_bars(a.db, guard, pilot, iv)
            m = sp.load_mobile_bars(mob, guard, pilot, iv)
            out[iv] = an.compare_sources(w, m, sp.load_primary_revisions(a.db, guard, pilot, iv),
                                         sp.load_mobile_revisions(mob, guard, pilot, iv))
    finally:
        a.close()
        mob.close()
    _write(f"mobile_vs_windows_{guard.cutoff}.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main(argv: list[str]):
    stage = argv[0] if argv else ""
    if stage == "split":
        split_stage()
    elif stage == "analyze":
        analyze_stage()
    elif stage == "mobile":
        mobile_stage(argv[1] if len(argv) > 1 else None)
    else:
        raise SystemExit("aşama: split | analyze | mobile <db>")


if __name__ == "__main__":
    main(sys.argv[1:])
