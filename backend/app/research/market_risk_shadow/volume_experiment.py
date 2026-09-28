"""MARKET-RISK-1 — hacim deneyi (yerel, keşifsel; tek çalıştırma).

Sözleşme: runs/volume_experiment_contract_20260928/contract.json (sonuç görülmeden kaydedildi).
Tek ek özellik: dvol_20_100 = ln( mean(V[T-19..T]) / mean(V[T-119..T-20]) ), T dahil son
120 beklenen BIST seansı. Bu ham Yahoo hacim oranıdır: devir hızı DEĞİLDİR ve NBER w7687
ölçüsünün birebir uygulaması DEĞİLDİR (hacim birimi ve bölünme düzeltmesi resmî olarak
doğrulanmadı). Eksik/sonlu olmayan/negatif hacim geçersizdir; penceredeki sıfır hacim
ZERO_VOLUME_IN_WINDOW olarak dışlanır (anlamı doğrulanmadı).

Fiyat modeli (6 özellik) ve fiyat+hacim modeli (7 özellik) AYNI ortak satırlarda birer kez
eğitilir; ölçekleyici ve p90 eşiği yalnızca kendi eğitim verisinden öğrenilir. İlk AL
günleri orijinal ham karar dizisinden belirlenir, uygunluk filtresi SONRA uygulanır.

Kullanım: python -m app.research.market_risk_shadow.volume_experiment <universe_run_dir> <contract_dir> <out_dir>
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.market_risk_shadow.asset_gate_analysis import ALT_BLOCKED, alternative_gate
from app.research.market_risk_shadow.basket_review import BUY
from app.research.market_risk_shadow.early_risk_model import (
    ALERT_PERCENTILE,
    EVAL_YEAR,
    FEATURES,
    MODEL_SPEC,
    TRAIN_YEAR,
    compute_features,
    evaluate_subset,
    fit_model,
    target_window_end,
)
from app.research.market_risk_shadow.event_review import BACKEND_ROOT, _sha256_file, load_saved_provider_csv
from app.research.market_risk_shadow.sharp_drop_coverage import DROP, NO_DROP, first_days, forward_drop_outcome
from app.research.market_risk_shadow.universe_review import _calendar_end
from app.services.market_data.trading_calendar import expected_trading_sessions

VOLUME_SESSIONS, RECENT = 120, 20
CODE_FILES = ("app/research/market_risk_shadow/volume_experiment.py",
              "app/research/market_risk_shadow/early_risk_model.py",
              "app/research/market_risk_shadow/sharp_drop_coverage.py")


def compute_dvol(volume_by_date: pd.Series, t: date) -> tuple[float | None, str | None]:
    """volume_by_date: tarih indeksli hacim serisi. Yalnızca T ve öncesi kullanılır."""
    series = volume_by_date[volume_by_date.index <= t]
    expected = expected_trading_sessions(t - timedelta(days=VOLUME_SESSIONS * 2 + 60), t)
    if expected is None:
        return None, "CALENDAR_UNSUPPORTED"
    if not expected or expected[-1] != t:
        return None, "AS_OF_NOT_EXPECTED_SESSION"
    window = expected[-VOLUME_SESSIONS:]
    if len(window) < VOLUME_SESSIONS or any(d not in series.index for d in window):
        return None, "VOLUME_MISSING_EXPECTED_SESSIONS"
    values = [float(series[d]) for d in window]
    if not all(math.isfinite(v) for v in values):
        return None, "VOLUME_NON_FINITE"
    if any(v < 0 for v in values):
        return None, "NEGATIVE_VOLUME"
    if any(v == 0 for v in values):
        return None, "ZERO_VOLUME_IN_WINDOW"
    recent = sum(values[-RECENT:]) / RECENT
    baseline = sum(values[:-RECENT]) / (VOLUME_SESSIONS - RECENT)
    return math.log(recent / baseline), None


def build_common(run_dir: Path):
    symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    entries = json.loads((run_dir / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    calendar = expected_trading_sessions(date(TRAIN_YEAR, 1, 1), _calendar_end(entries))
    eval_start = next(d for d in calendar if d.year == EVAL_YEAR)
    index_df = load_saved_provider_csv(run_dir / "inputs" / "XU100_provider_ohlcv.csv")
    index_close = pd.Series(index_df["Close"].to_numpy(), index=[ts.date() for ts in index_df.index])
    samples, exclusions, zero_any, zero_unique, start_counts = [], Counter(), Counter(), Counter(), Counter()
    for s in symbols:
        rows = json.loads((run_dir / "results" / f"{s}.json").read_text(encoding="utf-8"))["rows"]
        if not rows:
            continue
        df = load_saved_provider_csv(run_dir / "inputs" / f"{s}_provider_ohlcv.csv")
        dates = [ts.date() for ts in df.index]
        close = pd.Series(df["Close"].to_numpy(), index=dates)
        volume = pd.Series(df["Volume"].to_numpy(dtype=float), index=dates)
        closes = {d: float(v) for d, v in close.items() if v == v}
        firsts = {r["session"] for r in first_days(rows)}  # orijinal ham dizi; filtre SONRA
        for r in rows:
            if r["raw_class_technical_only"] not in BUY:
                continue
            t = date.fromisoformat(r["session"])
            start_counts[t.year] += 1
            dvol, vol_reason = compute_dvol(volume, t)
            reason = None
            if t.year == TRAIN_YEAR and ((end := target_window_end(t, calendar)) is None or end >= eval_start):
                reason = "TRAIN_TARGET_WINDOW_CROSSES_EVAL_START"
            features, price_reason = compute_features(close, index_close, t)
            reason = reason or price_reason or vol_reason
            outcome = forward_drop_outcome(closes, t, calendar)
            if reason is None and outcome not in (DROP, NO_DROP):
                reason = "TARGET_UNDETERMINED"
            if vol_reason == "ZERO_VOLUME_IN_WINDOW":
                zero_any[t.year] += 1
                if reason == "ZERO_VOLUME_IN_WINDOW":
                    zero_unique[t.year] += 1  # yalnızca sıfır hacim kuralıyla dışlanan
            if reason is not None:
                exclusions[(t.year, reason)] += 1
                continue
            samples.append({"symbol": s, "session": r["session"], "year": t.year, "y": int(outcome == DROP),
                            "x_price": [features[f] for f in FEATURES], "dvol": dvol,
                            "first_day": r["session"] in firsts,
                            "sharp_at_t": r["asset_rules"]["SHARP_DAILY_DECLINE_OBSERVED"]["triggered"] is True,
                            "current_blocked": r["shadow_gate"] == "BLOCKED",
                            "current_indeterminate": r["shadow_gate"] == "INDETERMINATE",
                            "asset_blocked": alternative_gate(r) == ALT_BLOCKED})
    return samples, exclusions, zero_any, zero_unique, start_counts, calendar, eval_start, symbols, entries


def design(samples: list[dict], with_volume: bool) -> np.ndarray:
    return np.array([s["x_price"] + ([s["dvol"]] if with_volume else []) for s in samples])


def run(run_dir: Path, contract_dir: Path, out: Path) -> dict:
    import scipy
    import sklearn

    out.mkdir(parents=True, exist_ok=True)
    samples, exclusions, zero_any, zero_unique, start_counts, calendar, eval_start, symbols, entries = build_common(run_dir)
    train = [s for s in samples if s["year"] == TRAIN_YEAR]
    evaluation = [s for s in samples if s["year"] == EVAL_YEAR]
    ty = np.array([s["y"] for s in train])
    models = {}
    for name, with_volume in (("price_6", False), ("price_volume_7", True)):
        tx, ex = design(train, with_volume), design(evaluation, with_volume)
        model, converged = fit_model(tx, ty)
        train_scores = model.predict_proba(tx)[:, 1]
        threshold = float(np.percentile(train_scores, ALERT_PERCENTILE))
        scores = model.predict_proba(ex)[:, 1]

        def subset(pred, scores=scores, threshold=threshold):
            idx = [i for i, s in enumerate(evaluation) if pred(s)]
            return evaluate_subset([evaluation[i] for i in idx], scores[idx], threshold, float(ty.mean()))

        models[name] = {
            "converged": converged, "alert_threshold_score": round(threshold, 6),
            "coefficients_standardized": [round(float(c), 4) for c in model.named_steps["lr"].coef_[0]],
            "all_days": subset(lambda s: True), "first_day": subset(lambda s: s["first_day"]),
            "no_sharp_at_t": subset(lambda s: not s["sharp_at_t"]),
        }
    ap = lambda m, k: models[m][k].get("average_precision", {}).get("model")
    br = lambda m, k: models[m][k].get("brier", {}).get("model")
    improved = all(ap("price_volume_7", k) is not None and ap("price_volume_7", k) > ap("price_6", k) for k in ("all_days", "first_day"))
    brier_ok = all(br("price_volume_7", k) <= br("price_6", k) for k in ("all_days", "first_day"))
    decision = "EK_BILGI_ISARETI" if improved and brier_ok else "EK_ISARET_YOK"

    def coverage(year):
        rows = [s for s in samples if s["year"] == year]
        return {"buy_days_start": start_counts[year], "common_sample": len(rows), "symbols": len({s["symbol"] for s in rows}),
                "drop_rate": round(sum(s["y"] for s in rows) / len(rows), 4) if rows else "N/A",
                "exclusions": {r: c for (y, r), c in sorted(exclusions.items()) if y == year},
                "zero_volume_rule_hits_any": zero_any[year], "zero_volume_rule_sole_reason": zero_unique[year]}

    contract_path = contract_dir / "contract.json"
    result = {
        "identity": {"sklearn": sklearn.__version__, "scipy": scipy.__version__, "numpy": np.__version__, "pandas": pd.__version__,
                     "contract_sha256": _sha256_file(contract_path), "model_spec": MODEL_SPEC,
                     "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in CODE_FILES},
                     "input_sha256": {s: entries[s].get("sha256") for s in ("XU100", *symbols)}},
        "date_boundaries": {"eval_start": eval_start.isoformat(), "calendar_end": calendar[-1].isoformat(),
                            "last_train_session": max(s["session"] for s in train)},
        "coverage": {str(TRAIN_YEAR): coverage(TRAIN_YEAR), str(EVAL_YEAR): coverage(EVAL_YEAR)},
        "models": models,
        "decision_rule": "AP hem tüm günlerde hem ilk AL günlerinde artar VE Brier iki alt grupta da kötüleşmez",
        "decision": decision,
        "decision_inputs": {"ap": {k: [ap("price_6", k), ap("price_volume_7", k)] for k in ("all_days", "first_day")},
                            "brier": {k: [br("price_6", k), br("price_volume_7", k)] for k in ("all_days", "first_day")}},
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print(sys.argv[3])
