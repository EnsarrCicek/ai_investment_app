"""FLOW 1B gözlem paneli: (tarih, sembol) başına T anındaki özellikler,
Technical kontrol değişkenleri ve T+h ileri getiriler.

Her şey TEK bir kesintisiz segment içinde hesaplanır (bkz. dataset.py).
Gözlem tarihi T, segmentin ilk `WARMUP_SESSIONS` seansından sonra başlar.
Getiri hedefleri T'den SONRAKİ barları kullanır; özellikler yalnızca T ve
öncesini — ileriye bakma yok (her özellik rolling/shift(+k) ile, hedef
yalnızca shift(-h) ile).
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from app.engines.backtest.engine import technical_score_series
from app.engines.technical import indicators as ind
from app.engines.technical.relative_volume import relative_volume_series
from app.research.canonical_hash import content_sha256
from app.research.flow_v1 import indicators as fi
from app.research.flow_v1.dataset import BENCHMARK_SYMBOL, FLOW_V1_DIR, SymbolQuality, preprocess_symbol

WARMUP_SESSIONS = 60
HORIZONS = (1, 5, 10, 20)
FREEZE_MANIFEST_FILE = FLOW_V1_DIR.parent / "resources" / "technical_v1_freeze_manifest.json"


def load_technical_baseline() -> dict:
    """Technical V1 dondurulmuş ağırlıkları + kimlik (manifest'in kendi hash'i
    ve scoring_config_hash yeniden hesaplanıp manifest ile karşılaştırılır)."""
    from app.engines.technical.engine import ENGINE_VERSION
    from app.engines.technical.scoring import compute_scoring_config_hash

    manifest = json.loads(FREEZE_MANIFEST_FILE.read_text(encoding="utf-8"))
    weights = dict(manifest["technical_indicator_weights"])
    family_weights = dict(manifest["technical_family_weights"])
    recomputed = compute_scoring_config_hash(weights, family_weights)
    expected = manifest["methodology_identity"]["scoring_config_hash"]
    if recomputed != expected:
        raise ValueError(f"scoring_config_hash uyuşmazlığı: {recomputed} != {expected}")
    return {
        "weights": weights,
        "family_weights": family_weights,
        "scoring_config_hash": recomputed,
        "freeze_manifest_sha256": content_sha256(manifest),
        "manifest_engine_version": manifest["methodology_identity"]["engine_version"],
        "current_engine_version": ENGINE_VERSION,
        "methodology_git_commit": manifest["methodology_identity"]["methodology_git_commit"],
        "score_function": "app.engines.backtest.engine.technical_score_series",
    }


def benchmark_table(segments: list[pd.DataFrame]) -> pd.DataFrame:
    """XU100: tarih -> Open, Close ve segment içi 20 seanslık geçmiş getirisi."""
    parts = []
    for seg in segments:
        part = pd.DataFrame(
            {
                "b_open": seg["Open"].to_numpy(float),
                "b_close": seg["Close"].to_numpy(float),
                "b_roc20": fi.price_roc(seg["Close"].astype(float), 20).to_numpy(float),
            },
            index=[ts.date() for ts in seg.index],
        )
        parts.append(part)
    return pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=["b_open", "b_close", "b_roc20"])


def segment_observations(symbol: str, seg: pd.DataFrame, bench: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    close = seg["Close"].astype(float)
    open_ = seg["Open"].astype(float)
    dates = [ts.date() for ts in seg.index]

    atr = ind.atr(seg)
    cmf20 = fi.cmf(seg)
    nsv20 = fi.nsv(seg)
    frame = pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "cmf20": cmf20.to_numpy(float),
            "nsv20": nsv20.to_numpy(float),
            "pvfs": fi.pvfs(cmf20, nsv20).to_numpy(float),
            "mfi14": fi.mfi(seg).to_numpy(float),
            "rv20": relative_volume_series(seg["Volume"].astype(float)).astype(float).to_numpy(float),
            "turnover20": fi.median_turnover(seg).to_numpy(float),
            "roc20_price": fi.price_roc(close).to_numpy(float),
            "technical_score": technical_score_series(seg, baseline["weights"], baseline["family_weights"]).to_numpy(float),
            "rsi14": ind.rsi(close).to_numpy(float),
            "momentum_component": ((ind.momentum(close) / atr) * 20).to_numpy(float),
            "roc_component": (ind.roc(close) * 8).to_numpy(float),
            "segment_position": np.arange(len(seg)),
        }
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        frame["log_rv20"] = np.where(frame["rv20"] > 0, np.log(frame["rv20"]), np.nan)
    for col in ["momentum_component", "roc_component", "rv20", "log_rv20"]:
        frame[col] = frame[col].replace([np.inf, -np.inf], np.nan)

    b_close_t = bench["b_close"].reindex(dates).to_numpy(float)
    frame["bench_roc20"] = bench["b_roc20"].reindex(dates).to_numpy(float)
    date_arr = np.array(dates, dtype=object)
    for h in HORIZONS:
        fwd_dates = list(pd.Series(date_arr).shift(-h))
        close_h = close.shift(-h).to_numpy(float)
        open_1 = open_.shift(-1).to_numpy(float)
        b_close_h = bench["b_close"].reindex(fwd_dates).to_numpy(float)
        e1_dates = list(pd.Series(date_arr).shift(-1))
        b_open_1 = bench["b_open"].reindex(e1_dates).to_numpy(float)
        raw = close_h / close.to_numpy(float) - 1.0
        b_raw = b_close_h / b_close_t - 1.0
        frame[f"raw_{h}"] = raw
        frame[f"ex_{h}"] = raw - b_raw
        exec_raw = close_h / open_1 - 1.0
        b_exec = b_close_h / b_open_1 - 1.0
        frame[f"exec_ex_{h}"] = exec_raw - b_exec

    return frame[frame["segment_position"] >= WARMUP_SESSIONS].drop(columns=["segment_position"])


def build_panel(frames: dict[str, pd.DataFrame], freeze_now: datetime, baseline: dict) -> tuple[pd.DataFrame, list[SymbolQuality], dict]:
    bench_segments, bench_quality = preprocess_symbol(BENCHMARK_SYMBOL, frames[BENCHMARK_SYMBOL], freeze_now)
    bench = benchmark_table(bench_segments)
    qualities = [bench_quality]
    pieces = []
    warmup_excluded = 0
    short_segments = 0
    for symbol, raw in frames.items():
        if symbol == BENCHMARK_SYMBOL:
            continue
        segments, quality = preprocess_symbol(symbol, raw, freeze_now)
        qualities.append(quality)
        for seg in segments:
            warmup_excluded += min(len(seg), WARMUP_SESSIONS)
            if len(seg) <= WARMUP_SESSIONS:
                short_segments += 1
                continue
            pieces.append(segment_observations(symbol, seg, bench, baseline))
    panel = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    build_info = {
        "warmup_sessions": WARMUP_SESSIONS,
        "warmup_excluded_bars": int(warmup_excluded),
        "segments_too_short_for_warmup": int(short_segments),
        "benchmark_valid_sessions": int(len(bench)),
    }
    return panel, qualities, build_info
