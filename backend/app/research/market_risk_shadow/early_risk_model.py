"""MARKET-RISK-1 — erken düşüş riski için tek ve basit yerel araştırma modeli (keşifsel).

Soru: T ve öncesindeki fiyat bilgisi, sonradan sert düşen AL günlerini diğer AL
günlerinden ayırabiliyor mu? Kesin tahmin, kalibre edilmiş olasılık veya üretim
kararı DEĞİLDİR. 2024 eğitim, 2025 kronolojik değerlendirme; her iki yılın sonuçları
daha önce görüldüğü için 2025 "dokunulmamış holdout" DEĞİLDİR.

Hedef (sharp_drop_coverage ile aynı): T kapanışına göre T+1..T+10 beklenen BIST
seanslarının kapanışlarından biri <= -%10 -> 1; tam pencerede yok -> 0; aksi BELİRSİZ.

Özellik sözleşmesi (yalnızca T ve öncesi; fiyat temeli: kayıtlı Yahoo auto_adjust
kapanışları; pencereler beklenen BIST seanslarıyla doğrulanır, eksik seans atlanmaz
veya doldurulmaz — eksikse örnek dışlanır):
  ret5       = C[T]/C[T-5] - 1                         (hisse, 6 kapanış)
  ret20      = C[T]/C[T-20] - 1                        (hisse, 21 kapanış)
  dd20       = 1 - C[T]/max(C[T-19..T])                (hisse, 20 kapanış)
  vol20      = std(ddof=1) of 20 günlük basit getiri   (hisse, 21 kapanış)
  dist_sma50 = C[T]/mean(C[T-49..T]) - 1               (hisse, 50 kapanış)
  rel20      = ret20(hisse) - ret20(XU100)             (hisse ve XU100, 21 kapanış)

Model: StandardScaler + LogisticRegression(penalty L2, C=1.0, class_weight=None,
solver lbfgs, max_iter=100). Ölçekleyici yalnızca eğitimde öğrenilir. Tarama/seçim yok.
Deneysel uyarı eşiği: eğitim skorlarının %90 persentili (optimal eşik DEĞİL).

Kullanım: python -m app.research.market_risk_shadow.early_risk_model <universe_run_dir> <out_dir>
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
import warnings
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.engines.risk.shadow_inputs import INSUFFICIENT, validate_daily_closes
from app.research.market_risk_shadow.asset_gate_analysis import ALT_BLOCKED, alternative_gate
from app.research.market_risk_shadow.basket_review import BUY
from app.research.market_risk_shadow.event_review import BACKEND_ROOT, _sha256_file, load_saved_provider_csv
from app.research.market_risk_shadow.sharp_drop_coverage import DROP, NO_DROP, first_days, forward_drop_outcome
from app.research.market_risk_shadow.universe_review import _calendar_end
from app.services.market_data.trading_calendar import expected_trading_sessions

FEATURES = ("ret5", "ret20", "dd20", "vol20", "dist_sma50", "rel20")
ASSET_SESSIONS, INDEX_SESSIONS = 50, 21
TRAIN_YEAR, EVAL_YEAR = 2024, 2025
MODEL_SPEC = {"scaler": "StandardScaler", "estimator": "LogisticRegression", "penalty": "l2", "C": 1.0,
              "class_weight": None, "solver": "lbfgs", "max_iter": 100}
ALERT_PERCENTILE = 90
HORIZON = 10
CODE_FILES = ("app/research/market_risk_shadow/early_risk_model.py",
              "app/research/market_risk_shadow/sharp_drop_coverage.py",
              "app/engines/risk/shadow_inputs.py")


def compute_features(asset_closes: pd.Series, index_closes: pd.Series, t: date) -> tuple[dict | None, str | None]:
    asset = validate_daily_closes(asset_closes, t, ASSET_SESSIONS)
    if asset.status == INSUFFICIENT:
        return None, "ASSET_" + asset.reason_codes[0]
    index = validate_daily_closes(index_closes, t, INDEX_SESSIONS)
    if index.status == INSUFFICIENT:
        return None, "INDEX_" + index.reason_codes[0]
    c, x = asset.closes.to_numpy(dtype=float), index.closes.to_numpy(dtype=float)
    ret20 = c[-1] / c[-21] - 1
    daily = c[-20:] / c[-21:-1] - 1
    return {
        "ret5": c[-1] / c[-6] - 1,
        "ret20": ret20,
        "dd20": 1 - c[-1] / c[-20:].max(),
        "vol20": float(np.std(daily, ddof=1)),
        "dist_sma50": c[-1] / c[-50:].mean() - 1,
        "rel20": ret20 - (x[-1] / x[-21] - 1),
    }, None


def target_window_end(t: date, calendar: list[date]) -> date | None:
    i = calendar.index(t)
    return calendar[i + HORIZON] if i + HORIZON < len(calendar) else None


def fit_model(train_x: np.ndarray, train_y: np.ndarray):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(C=MODEL_SPEC["C"], class_weight=MODEL_SPEC["class_weight"],
                                  solver=MODEL_SPEC["solver"], max_iter=MODEL_SPEC["max_iter"])),
    ])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(train_x, train_y)
    converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
    return model, converged


def _ratio(num, den):
    return {"num": int(num), "den": int(den), "share": round(num / den, 4) if den else "N/A"}


def evaluate_subset(samples: list[dict], scores: np.ndarray, threshold: float, train_rate: float) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss

    y = np.array([s["y"] for s in samples])
    n, drops = len(y), int(y.sum())
    alert = scores >= threshold
    out = {"n": n, "drops": drops, "drop_rate": round(drops / n, 4) if n else "N/A"}
    if n == 0 or drops in (0, n):
        out["note"] = "AP/Brier hesaplanamadı (tek sınıf veya boş)"
    else:
        out["average_precision"] = {"model": round(float(average_precision_score(y, scores)), 4),
                                    "constant_reference": round(drops / n, 4)}
        out["brier"] = {"model": round(float(brier_score_loss(y, scores)), 4),
                        "constant_train_rate": round(float(brier_score_loss(y, np.full(n, train_rate))), 4)}
    out["model_alert"] = {"alert_rate": _ratio(alert.sum(), n), "drops_alerted": _ratio((alert & (y == 1)).sum(), drops),
                          "alerted_that_dropped": _ratio((alert & (y == 1)).sum(), alert.sum())}
    for name, key in (("current_combined_gate", "current_blocked"), ("asset_filter_alternative", "asset_blocked")):
        b = np.array([s[key] for s in samples], dtype=bool)
        indet = int(sum(s["current_indeterminate"] for s in samples)) if key == "current_blocked" else 0
        out[name] = {"blocked_rate": _ratio(b.sum(), n), "drops_blocked": _ratio((b & (y == 1)).sum(), drops),
                     "blocked_that_dropped": _ratio((b & (y == 1)).sum(), b.sum()), "gate_indeterminate": indet}
    return out


def build_samples(run_dir: Path):
    symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    entries = json.loads((run_dir / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    calendar = expected_trading_sessions(date(TRAIN_YEAR, 1, 1), _calendar_end(entries))
    eval_start = next(d for d in calendar if d.year == EVAL_YEAR)
    index_df = load_saved_provider_csv(run_dir / "inputs" / "XU100_provider_ohlcv.csv")
    index_close = pd.Series(index_df["Close"].to_numpy(), index=[ts.date() for ts in index_df.index])
    train, evaluation, exclusions = [], [], Counter()
    per_symbol = {}
    for s in symbols:
        rows = json.loads((run_dir / "results" / f"{s}.json").read_text(encoding="utf-8"))["rows"]
        counts = Counter()
        if rows:
            df = load_saved_provider_csv(run_dir / "inputs" / f"{s}_provider_ohlcv.csv")
            asset_close = pd.Series(df["Close"].to_numpy(), index=[ts.date() for ts in df.index])
            closes = {d: float(v) for d, v in asset_close.items() if v == v}
            firsts = {r["session"] for r in first_days(rows)}
        for r in rows:
            if r["raw_class_technical_only"] not in BUY:
                continue
            t = date.fromisoformat(r["session"])
            year = t.year
            counts[f"{year}:buy_days"] += 1
            if year == TRAIN_YEAR:
                end = target_window_end(t, calendar)
                if end is None or end >= eval_start:
                    reason = "TRAIN_TARGET_WINDOW_CROSSES_EVAL_START"
                    counts[f"{year}:excluded:{reason}"] += 1
                    exclusions[(year, reason)] += 1
                    continue
            features, why = compute_features(asset_close, index_close, t)
            if features is None:
                counts[f"{year}:excluded:{why}"] += 1
                exclusions[(year, why)] += 1
                continue
            outcome = forward_drop_outcome(closes, t, calendar)
            if outcome not in (DROP, NO_DROP):
                counts[f"{year}:excluded:TARGET_UNDETERMINED"] += 1
                exclusions[(year, "TARGET_UNDETERMINED")] += 1
                continue
            sample = {"symbol": s, "session": r["session"], "y": int(outcome == DROP), "x": [features[f] for f in FEATURES],
                      "first_day": r["session"] in firsts,
                      "sharp_at_t": r["asset_rules"]["SHARP_DAILY_DECLINE_OBSERVED"]["triggered"] is True,
                      "current_blocked": r["shadow_gate"] == "BLOCKED",
                      "current_indeterminate": r["shadow_gate"] == "INDETERMINATE",
                      "asset_blocked": alternative_gate(r) == ALT_BLOCKED}
            counts[f"{year}:included"] += 1
            (train if year == TRAIN_YEAR else evaluation).append(sample)
        per_symbol[s] = dict(counts)
    return train, evaluation, exclusions, per_symbol, calendar, eval_start, symbols, entries


def run(run_dir: Path, out: Path) -> dict:
    import scipy
    import sklearn

    out.mkdir(parents=True, exist_ok=True)
    contract = {"features": FEATURES, "asset_sessions_required": ASSET_SESSIONS, "index_sessions_required": INDEX_SESSIONS,
                "price_basis": "kayıtlı Yahoo auto_adjust kapanışları (round_trip okuma)", "model": MODEL_SPEC,
                "alert_threshold": f"eğitim skorlarının %{ALERT_PERCENTILE} persentili", "train_year": TRAIN_YEAR,
                "eval_year": EVAL_YEAR, "target": "T+1..T+10 beklenen seans kapanışlarından biri <= -%10"}
    (out / "contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")

    train, evaluation, exclusions, per_symbol, calendar, eval_start, symbols, entries = build_samples(run_dir)
    tx, ty = np.array([s["x"] for s in train]), np.array([s["y"] for s in train])
    model, converged = fit_model(tx, ty)
    train_scores = model.predict_proba(tx)[:, 1]
    threshold = float(np.percentile(train_scores, ALERT_PERCENTILE))
    train_rate = float(ty.mean())
    ex = np.array([s["x"] for s in evaluation])
    eval_scores = model.predict_proba(ex)[:, 1]

    def subset(pred):
        idx = [i for i, s in enumerate(evaluation) if pred(s)]
        return evaluate_subset([evaluation[i] for i in idx], eval_scores[idx], threshold, train_rate)

    result = {
        "identity": {"sklearn": sklearn.__version__, "scipy": scipy.__version__, "numpy": np.__version__, "pandas": pd.__version__,
                     "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in CODE_FILES},
                     "input_sha256": {s: entries[s].get("sha256") for s in ("XU100", *symbols)},
                     "contract_sha256": hashlib.sha256((out / "contract.json").read_bytes()).hexdigest()},
        "date_boundaries": {"eval_start": eval_start.isoformat(), "calendar_end": calendar[-1].isoformat(),
                            "train_rule": "2024 AL günleri; hedef penceresinin son seansı (T+10) < eval_start"},
        "converged": converged,
        "coefficients_standardized": dict(zip(FEATURES, [round(float(c), 4) for c in model.named_steps["lr"].coef_[0]])),
        "intercept": round(float(model.named_steps["lr"].intercept_[0]), 4),
        "train": {"n": len(train), "drops": int(ty.sum()), "drop_rate": round(train_rate, 4), "alert_threshold_score": round(threshold, 6),
                  "last_train_session": max(s["session"] for s in train)},
        "exclusions": {f"{y}:{r}": c for (y, r), c in sorted(exclusions.items())},
        "eval_all_days": subset(lambda s: True),
        "eval_first_day_of_buy_run": subset(lambda s: s["first_day"]),
        "eval_no_sharp_rule_at_t": subset(lambda s: not s["sharp_at_t"]),
        "eval_first_day_no_sharp_rule_at_t": subset(lambda s: s["first_day"] and not s["sharp_at_t"]),
        "per_symbol_counts": per_symbol,
    }
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(run(Path(sys.argv[1]), Path(sys.argv[2])) and sys.argv[2])
