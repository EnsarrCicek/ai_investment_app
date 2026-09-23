"""Üretimle BİREBİR (production-exact) Technical durum yeniden kurulumu.

Her (sembol, tamamlanmış seans T) için: kesintisiz segmentte T − 6 ay
penceresi (üretim ANALYSIS_WINDOW_MONTHS) → `compute_technical_analysis`
(dondurulmuş V1 ağırlıkları, dondurulmuş XU100). `classify_signal`'a verilen
`SignalInputs`, YALNIZCA bu araştırma sürecinde bir çalışma-zamanı sarmalayıcı
ile yakalanır — üretim kodu değişmez.

Çıktı getiri İÇERMEZ (yalnızca durum/sınıf); ham fiyat da içermez. Yerel
dosyaya yazılır (git/docker-ignored), hash'i commit'lenir.

Çalıştırma: `python -m app.research.technical_volume_audit.states`
"""

from __future__ import annotations

import dataclasses
import gzip
import io
import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from app.research.canonical_hash import content_sha256

AUDIT_DIR = Path(__file__).resolve().parent
DATA_DIR = AUDIT_DIR / "data"
STATES_FILE = DATA_DIR / "production_states.json.gz"
STATES_MANIFEST_FILE = DATA_DIR / "production_states_manifest.json"

ANALYSIS_WINDOW_MONTHS = 6  # app/engines/technical/history_window.py ile aynı
MIN_HISTORY_DAYS = 60  # app/engines/technical/engine.py ile aynı
HIGH_VOLUME_RATIO = 1.5  # relative_volume.DEFAULT_THRESHOLDS["high"]
DIRECTION_BAND = 0.005
STATE_COLUMNS = ["date", "symbol", "technical_score_prod", "rv20", "signal_class", "strong_preconditions_without_volume",
                 "bullish_confirmed_breakout", "r_1d", "high_equals_low", "prior4_high_count"]
IST = ZoneInfo("Europe/Istanbul")


# ------------------------------------------------------------------ saf yardımcılar


def window_start(T: pd.Timestamp):
    return (T - relativedelta(months=ANALYSIS_WINDOW_MONTHS)).date()


def production_window(seg: pd.DataFrame, pos: int) -> pd.DataFrame | None:
    """Üretim penceresi: segmentte T−6ay'dan önce en az bir bar olmalı
    (VERIFIED_PRE_WINDOW eşdeğeri) ve pencere ≥ MIN_HISTORY_DAYS olmalı;
    aksi halde None (gözlem uygun değil)."""
    T = seg.index[pos]
    start = window_start(T)
    if seg.index[0].date() >= start:
        return None
    df = seg.iloc[: pos + 1]
    df = df[df.index.date >= start]
    if len(df) < MIN_HISTORY_DAYS:
        return None
    return df


def is_high_volume(rv: float) -> bool | None:
    if rv is None or not np.isfinite(rv):
        return None
    return bool(rv >= HIGH_VOLUME_RATIO)


def price_direction(r: float) -> str | None:
    if r is None or not np.isfinite(r):
        return None
    if r > DIRECTION_BAND:
        return "UP"
    if r < -DIRECTION_BAND:
        return "DOWN"
    return "FLAT"


def spike_or_sustained(prior4_high_count: int | None) -> str | None:
    if prior4_high_count is None:
        return None
    if prior4_high_count == 0:
        return "SPIKE"
    if prior4_high_count >= 2:
        return "SUSTAINED"
    return "INTERMEDIATE"


def strong_preconditions_without_volume(inputs, classify) -> bool:
    """STRONG_BULLISH_INITIATION'ın high_volume DIŞINDAKİ tüm üretim koşulları
    sağlanıyor mu? Hacim HIGH'a zorlanarak ÜRETİM `classify_signal`'ı ile
    değerlendirilir: koşullar ayrıca kopyalanmaz (formül ikizi yok). Girdinin
    kendi `relative_volume_class`'ı sonuca ETKİ ETMEZ — predicate hacimden
    bağımsızdır; A/B (yüksek/yüksek-olmayan) bu predicate TRUE iken ayrılır."""
    forced = dataclasses.replace(inputs, relative_volume_class="HIGH")
    return classify(forced) == "STRONG_BULLISH_INITIATION"


# ------------------------------------------------------------------ worker

_W: dict = {}


def install_capture(engine_module) -> tuple:
    """`engine_module.classify_signal`'ı, girdiyi yakalayıp ÜRETİM sonucunu
    aynen döndüren bir sarmalayıcıyla değiştirir. YALNIZCA işçi süreçlerinin
    initializer'ında çağrılır: ProcessPoolExecutor her işçiyi AYRI bir süreçte
    çalıştırır (thread yok), her süreç görevleri sırayla işler ve kendi
    `captured` sözlüğünü tutar; ana süreçteki modül ASLA yamanmaz."""
    original = engine_module.classify_signal
    captured: dict = {}

    def capturing(inputs):
        captured["inputs"] = inputs
        return original(inputs)

    engine_module.classify_signal = capturing
    return original, captured


def _init_worker() -> None:
    logging.disable(logging.CRITICAL)
    import app.engines.technical.engine as eng
    from app.research.flow_v1.dataset import preprocess_symbol
    from app.research.flow_v1.panel import load_technical_baseline
    from app.research.flow_v1c.dataset import load_external_dataset

    frames, manifest = load_external_dataset()
    freeze_now = datetime.fromisoformat(manifest["freeze_now_utc"])
    bench_segments, _ = preprocess_symbol("XU100", frames["XU100"], freeze_now)
    bench = pd.concat([s["Close"] for s in bench_segments])
    bench.index = [ts.date() for ts in bench.index]
    original, captured = install_capture(eng)
    _W.update(frames=frames, freeze_now=freeze_now, bench=bench, baseline=load_technical_baseline(),
              eng=eng, original=original, captured=captured, preprocess=preprocess_symbol)


def _symbol_states(symbol: str) -> tuple[str, list[list], dict]:
    from app.engines.technical.relative_volume import relative_volume_series

    w = _W
    segments, _ = w["preprocess"](symbol, w["frames"][symbol], w["freeze_now"])
    rows: list[list] = []
    counts = {"windows_evaluated": 0, "ineligible_window": 0, "score_unavailable": 0, "compute_error": 0}
    b = w["baseline"]
    for seg in segments:
        rv_full = pd.to_numeric(relative_volume_series(seg["Volume"].astype(float)), errors="coerce")
        for pos in range(len(seg)):
            df = production_window(seg, pos)
            if df is None:
                counts["ineligible_window"] += 1
                continue
            T = seg.index[pos]
            w["captured"].clear()
            try:
                analysis = w["eng"].compute_technical_analysis(
                    df, symbol, b["weights"], b["family_weights"], b["scoring_config_hash"], "RESEARCH_TECH_VOL_1A", {},
                    benchmark_close_series=w["bench"], now=datetime.combine(T.date(), dtime(18, 45), IST),
                )
            except Exception:
                counts["compute_error"] += 1
                continue
            counts["windows_evaluated"] += 1
            inputs = w["captured"].get("inputs")
            if analysis.technical_score is None or inputs is None:
                counts["score_unavailable"] += 1
                continue
            rv_win = pd.to_numeric(relative_volume_series(df["Volume"].astype(float)), errors="coerce")
            rv = float(rv_win.iloc[-1]) if pd.notna(rv_win.iloc[-1]) else None
            prior = rv_full.iloc[max(0, pos - 4): pos]
            prior4 = int((prior >= HIGH_VOLUME_RATIO).sum()) if len(prior) == 4 and prior.notna().all() else None
            close = df["Close"]
            r1 = float(close.iloc[-1] / close.iloc[-2] - 1.0)
            be = inputs.breakout_event
            rows.append([
                T.date().isoformat(), symbol, float(analysis.technical_score), rv, analysis.signal_class,
                strong_preconditions_without_volume(inputs, w["original"]),
                bool(be is not None and be.direction == "BULLISH" and be.confirmed is True),
                r1, bool(df["High"].iloc[-1] == df["Low"].iloc[-1]), prior4,
            ])
    return symbol, rows, counts


def _cache_file(symbol: str) -> Path:
    return DATA_DIR / f"state_cache_{symbol}.json.gz"


def _write_gz_json(path: Path, obj) -> None:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    path.write_bytes(buf.getvalue())


def build_states(workers: int = 4, max_tasks_per_child: int = 20) -> dict:
    """Sembol başına kontrol noktası (checkpoint) yazar; çökme sonrası yeniden
    çalıştırma tamamlanmış sembolleri atlar. Nihai içerik iş sırasından
    bağımsızdır (satırlar (tarih, sembol) sıralı)."""
    from app.research.flow_v1c.dataset import load_external_dataset
    from app.research.flow_v1c.universe import load_external_universe

    symbols, universe = load_external_universe()
    _, manifest = load_external_dataset()
    available = [s for s in symbols if manifest["symbols"][s]["status"] == "OK"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pending = [s for s in available if not _cache_file(s).exists()]
    print(f"[states] cached={len(available) - len(pending)} pending={len(pending)}", file=sys.stderr, flush=True)
    if pending:
        from concurrent.futures import as_completed

        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 max_tasks_per_child=max_tasks_per_child) as pool:
            futures = [pool.submit(_symbol_states, s) for s in pending]
            for i, fut in enumerate(as_completed(futures)):
                symbol, rows, counts = fut.result()
                _write_gz_json(_cache_file(symbol), {"symbol": symbol, "rows": rows, "counts": counts})
                if i % 25 == 0:
                    print(f"[states] {i + 1}/{len(pending)} {symbol}", file=sys.stderr, flush=True)
    all_rows: list[list] = []
    per_symbol: dict[str, dict] = {}
    for s in available:
        cached = json.loads(gzip.decompress(_cache_file(s).read_bytes()).decode("utf-8"))
        all_rows.extend(cached["rows"])
        per_symbol[s] = {**cached["counts"], "state_rows": len(cached["rows"])}
    all_rows.sort(key=lambda r: (r[0], r[1]))
    payload = {"columns": STATE_COLUMNS, "rows": all_rows}
    _write_gz_json(STATES_FILE, payload)
    states_manifest = {
        "artifact": "TECH_VOL_1A_PRODUCTION_STATES",
        "source_dataset_sha256": manifest["dataset_sha256"],
        "external_symbols_sha256": universe["external_symbols_sha256"],
        "rows": len(all_rows),
        "states_content_sha256": content_sha256(payload),
        "per_symbol": per_symbol,
        "method": "compute_technical_analysis on 6-month production window per (symbol, T); SignalInputs captured by a worker-local runtime wrapper (process isolation)",
    }
    STATES_MANIFEST_FILE.write_text(json.dumps(states_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return states_manifest


def load_verified_states() -> pd.DataFrame:
    from app.research.flow_v1.dataset import FrozenDatasetMissingError

    if not STATES_FILE.exists():
        raise FrozenDatasetMissingError(
            f"Yerel production-state dosyası yok: {STATES_FILE}. Önce `python -m app.research.technical_volume_audit.states` çalıştırın."
        )
    manifest = json.loads(STATES_MANIFEST_FILE.read_text(encoding="utf-8"))
    payload = json.loads(gzip.decompress(STATES_FILE.read_bytes()).decode("utf-8"))
    if content_sha256(payload) != manifest["states_content_sha256"]:
        raise ValueError("production_states hash uyuşmazlığı")
    df = pd.DataFrame(payload["rows"], columns=payload["columns"])
    df["date"] = pd.to_datetime(df["date"])
    return df


if __name__ == "__main__":
    _workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    print(json.dumps({k: v for k, v in build_states(workers=_workers).items() if k != "per_symbol"}))
