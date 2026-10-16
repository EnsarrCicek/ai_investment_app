"""Momentum kalibrasyonu — aşamalı, kronolojik, holdout korumalı deney.

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_calibration.experiment <stage>

Aşamalar (sırayla): fetch → quality → features → equivalence → calibrate → validate → holdout → ktlev

* Öznitelikler ÜRETİM motorunun `compute_features` fonksiyonuyla hesaplanır (farklı matematik yok); eşik/kural
  adayları aynı `classify_raw` + `confirm_level` ile uygulanır. `equivalence` aşaması rastgele örnekte araştırma
  sonucunu üretim `evaluate()` ile karşılaştırır.
* Seçim yalnız kalibrasyon + doğrulama seanslarıyla yapılır. `validate` tek adayı FINAL_CANDIDATE olarak dondurur
  (yapılandırma + SHA-256). `holdout` yalnız dondurulmuş adayla ve YALNIZ BİR KEZ çalışır (sonuç dosyası varsa reddeder).
* KTLEV hiçbir seçim aşamasında yoktur; dondurmadan sonra `ktlev` aşamasında raporlanır.
* Haber bağlamı kullanılmaz (events=None): kalibrasyon piyasa öznitelikleriyle yapılır.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import random
import sys
import time as clock
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from statistics import median

import numpy as np

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_calibration import dataset as ds
from app.research.momentum_calibration.labels import labels_for_session
from app.research.momentum_calibration.metrics import base_rate, summarize
from app.services.momentum.early_momentum_engine import (DEFAULT_CONFIG, FeatureSnapshot, classify_raw,
                                                         classify_session_quality, compute_features, confirm_level,
                                                         evaluate)

PRIMARY_X = 0.03  # Label B: alarmdan sonra gün içinde ≥%3 daha yükselme
PRIMARY_E = 0.05  # olay seansı: seans içi ≥%5 yükseliş
SENSITIVITY_X = (0.02, 0.03, 0.05)
SENSITIVITY_E = (0.03, 0.05, 0.08)
SELECT_MIN_STRONG_ALERTS_CAL = 10
SELECT_MIN_STRONG_ALERTS_VAL = 5
SELECT_MIN_RECALL = 0.15
# Holdout geçme ölçütü — holdout çalıştırılmadan ÖNCE sabitlenmiştir (sonradan değiştirilmez).
HOLDOUT_CRITERIA = {"min_strong_alerts": 10, "precision_vs_base_rate": 2.0, "max_strong_fpr": 0.05,
                    "min_strong_recall": 0.25, "strong_precision_gt_watch": True}

FEATURE_VARIANTS = {
    "F0": {},
    "F1": {"baseline_quality_filter": True, "volatility_floor": "HYBRID_TICK", "range_floor": True,
           "relvol_mode": "EFFECTIVE"},
}
_GROUPS = {"rule_mode": "GROUPS"}
_PERSIST = {**_GROUPS, "confirm_k": 2, "confirm_n": 2}
CANDIDATES: dict[str, tuple[str, dict]] = {
    "C0_BASELINE": ("F0", {}),
    "C1_ROBUST_BASELINE": ("F1", {}),
    "C2_GROUP_EVIDENCE": ("F1", _GROUPS),
    "C3_PERSISTENCE": ("F1", _PERSIST),
    "C4_PERSIST_2OF3": ("F1", {**_GROUPS, "confirm_k": 2, "confirm_n": 3}),
    "C5_PERSIST_3": ("F1", {**_GROUPS, "confirm_k": 3, "confirm_n": 3}),
    "C6_STRICT_PRICE": ("F1", {**_PERSIST, "evidence_threshold": 0.75}),
    "C7_STRICT_SCORE": ("F1", {**_PERSIST, "watch_score": 50.0, "strong_score": 70.0}),
    "C8_UP_SESSION": ("F1", {**_PERSIST, "min_session_return_pct": 0.0}),
    "C9_STRICT_ALL": ("F1", {**_PERSIST, "evidence_threshold": 0.75, "watch_score": 50.0, "strong_score": 70.0,
                             "min_session_return_pct": 0.0}),
    "C10_STRONG_Z4": ("F1", {**_PERSIST, "strong_price_impulse": 1.0}),
}


def config_for(variant: str, overrides: dict | None = None, delay: int = 15) -> ma.MomentumAlertConfig:
    return ma.MomentumAlertConfig(**{**FEATURE_VARIANTS[variant], **(overrides or {}),
                                     "provider_delay_minutes": delay})


def config_hash(config: ma.MomentumAlertConfig) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()


def eval_times(day: date, delay: int) -> list[datetime]:
    t = datetime.combine(day, time(10, 0), tzinfo=ISTANBUL_TZ)
    stop = datetime.combine(day, time(18, 0), tzinfo=ISTANBUL_TZ) + timedelta(minutes=delay)
    out = []
    while t < stop:
        out.append(t)
        t += timedelta(minutes=5)
    return out


def session_dates(assets: list[str]) -> list[date]:
    days = set()
    for s in assets:
        days |= set(ds.complete_sessions(ds.load(s)))
    return sorted(days)


def _asset_features(args) -> list[dict]:
    symbol, variant, delay, days = args
    data = ds.load(symbol)
    config = config_for(variant, delay=delay)
    have = set(data.bars.index.date)
    rows = []
    for day in days:
        if day not in have:
            continue
        window = ds.window_for(data, day)
        for t in eval_times(day, delay):
            snap = compute_features(symbol, window, data.provenance, t, config, None)
            m = snap.metrics or {}
            rows.append({"symbol": symbol, "day": day, "t": t, "status": snap.status,
                         "components": snap.components, "persistent": snap.persistent, "data_gap": snap.data_gap,
                         "session_return_pct": m.get("session_return_pct"),
                         "raw_relative_volume": m.get("raw_relative_volume"), "price_z": m.get("price_z"),
                         "sigma_raw": m.get("sigma_raw"), "sigma_effective": m.get("sigma_effective"),
                         "range_ratio": m.get("range_ratio"), "raw_range_baseline": m.get("raw_range_baseline"),
                         "effective_range_baseline": m.get("effective_range_baseline"),
                         "last_close": m.get("last_close")})
    return rows


def features_path(variant: str, delay: int, tag: str = "universe"):
    return ds.RUNS / f"features_{tag}_{variant}_d{delay}.pkl"


def compute_all_features(assets, variant, delay, days, tag="universe", workers=7):
    started = clock.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for k, part in enumerate(pool.map(_asset_features, [(s, variant, delay, days) for s in assets]), 1):
            rows.extend(part)
            print(f"  {variant} d{delay}: {k}/{len(assets)} varlık, {clock.perf_counter() - started:.0f} sn",
                  flush=True)
    with features_path(variant, delay, tag).open("wb") as f:
        pickle.dump(rows, f)
    print(f"features {tag} {variant} d{delay}: {len(rows)} değerlendirme, {clock.perf_counter() - started:.0f} sn")
    return rows


def load_features(variant, delay, tag="universe"):
    with features_path(variant, delay, tag).open("rb") as f:
        return pickle.load(f)


def classify_rows(rows: list[dict], config: ma.MomentumAlertConfig) -> list[dict]:
    """Üretim `classify_raw` + `confirm_level` (ardışık değerlendirmeler aynı seans, 5 dk arayla)."""
    out = []
    history: dict[tuple, list[str]] = {}
    for r in sorted(rows, key=lambda r: (r["symbol"], r["t"])):
        snap = FeatureSnapshot(r["status"], None, {}, r["components"], {"session_return_pct": r["session_return_pct"]},
                               r["persistent"], r["data_gap"])
        raw = classify_raw(snap, config)[0]
        seq = history.setdefault((r["symbol"], r["day"]), [])
        seq.append(raw)
        padded = [ma.LEVEL_NONE] * max(0, config.confirm_n - len(seq)) + seq  # seans öncesi = piyasa kapalı = NONE
        final = confirm_level(padded, config) if config.confirm_n > 1 else raw
        out.append({**r, "raw_level": raw, "final_level": final})
    return out


_LABEL_CACHE: dict = {}
_BARS_CACHE: dict = {}


def attach_labels(rows: list[dict], days: set[date]) -> tuple[list[dict], dict]:
    sessions = {}
    by_key: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["day"] in days:
            by_key.setdefault((r["symbol"], r["day"]), []).append(r)
    labeled = []
    for (symbol, day), items in by_key.items():
        times = tuple(r["t"] for r in items)
        key = (symbol, day, times)
        if key not in _LABEL_CACHE:  # etiketler yapılandırmadan bağımsızdır: bir kez hesaplanır
            if symbol not in _BARS_CACHE:
                _BARS_CACHE[symbol] = ds.load(symbol).bars
            _LABEL_CACHE[key] = labels_for_session(_BARS_CACHE[symbol], day, list(times))
        outcome, labels = _LABEL_CACHE[key]
        sessions[(symbol, day)] = outcome
        labeled.extend({**r, "label": lab} for r, lab in zip(items, labels))
    labeled.sort(key=lambda r: (r["symbol"], r["t"]))
    return labeled, sessions


def evaluate_candidate(name, feature_rows_by_variant, days, delay=15, x=PRIMARY_X, e=PRIMARY_E, overrides=None):
    variant, cand = CANDIDATES[name]
    config = config_for(variant, {**cand, **(overrides or {})}, delay)
    rows = classify_rows([r for r in feature_rows_by_variant[variant] if r["day"] in days], config)
    labeled, sessions = attach_labels(rows, days)
    return {"name": name, "config_hash": config_hash(config),
            "watch": summarize(labeled, sessions, ma.LEVEL_WATCH, x, e),
            "strong": summarize(labeled, sessions, ma.LEVEL_STRONG, x, e),
            "base_rate": base_rate(labeled, x)}, labeled, sessions


def _brief(res):
    def one(m):
        return {k: m[k] for k in ("alert_sessions", "alert_day_ratio", "precision", "recall", "false_positive_rate",
                                  "missed_events", "alert_evaluations_per_session", "median_first_alert_time",
                                  "median_move_completed", "median_future_mfe_pct", "max_asset_share_of_alerts")}
    return {"name": res["name"], "base_rate": res["base_rate"], "watch": one(res["watch"]),
            "strong": one(res["strong"])}


def select_top(results: list[dict], min_alerts: int, k: int) -> list[str]:
    ok = [r for r in results if r["strong"]["alert_sessions"] >= min_alerts
          and (r["strong"]["recall"] or 0) >= SELECT_MIN_RECALL]
    ok.sort(key=lambda r: (-(r["strong"]["precision"] or 0), r["strong"]["false_positive_rate"] or 1))
    return [r["name"] for r in ok[:k]]


def write_json(name, payload):
    path = ds.RUNS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def read_json(name):
    return json.loads((ds.RUNS / name).read_text(encoding="utf-8"))


def splits():
    days = session_dates(list(ds.CALIBRATION_ASSETS))
    return days, ds.split_sessions(days)


def main(stage: str):
    ds.RUNS.mkdir(parents=True, exist_ok=True)
    assets = list(ds.CALIBRATION_ASSETS)
    assert ds.HOLDOUT_CASE not in assets
    if stage == "fetch":
        for s in assets + [ds.HOLDOUT_CASE]:
            d = ds.load(s)
            print(s, len(d.bars), d.bars.index[0], d.bars.index[-1], d.provenance.get("identity_check"))
        return
    all_days, split = splits()
    if stage == "split":
        print({k: (v[0], v[-1], len(v)) for k, v in split.items()}, "warmup", all_days[:ds.WARMUP_SESSIONS])
        return
    if stage == "quality":
        counts, stats = {}, []
        for s in assets + [ds.HOLDOUT_CASE]:
            data = ds.load(s)
            for day, g in data.bars.groupby(data.bars.index.date):
                if day not in all_days:
                    continue
                label, st = classify_session_quality(g.dropna(), DEFAULT_CONFIG.min_bars_per_prior_session)
                counts[label] = counts.get(label, 0) + 1
                stats.append({"symbol": s, "day": str(day), "label": label, **st})
        ktlev = [r for r in stats if r["symbol"] == ds.HOLDOUT_CASE and "2026-09-22" <= r["day"] <= "2026-09-30"]
        write_json("session_quality.json", {"counts": counts, "ktlev_sep22_30": ktlev, "all": stats})
        print(counts)
        for r in ktlev:
            print(r["day"], r["label"], {k: r[k] for k in ("unique_closes", "identical_ohlc_ratio", "range_pct")})
        normal = [r for r in stats if r["label"] == "NORMAL"]
        for key in ("range_pct", "identical_ohlc_ratio", "unique_closes", "close_changes", "zero_volume_ratio"):
            vals = np.array([r[key] for r in normal])
            print(f"NORMAL {key}: p1={np.percentile(vals, 1):.3f} p5={np.percentile(vals, 5):.3f} "
                  f"median={np.median(vals):.3f}")
        return
    if stage == "features":
        eval_days = split["calibration"] + split["validation"] + split["holdout"]
        for variant in FEATURE_VARIANTS:
            compute_all_features(assets, variant, 15, eval_days)
        return
    if stage == "equivalence":
        rng = random.Random(20261016)
        mismatches, checked = 0, 0
        for name in ("C0_BASELINE", "C3_PERSISTENCE", "C5_PERSIST_3", "C9_STRICT_ALL"):
            variant, cand = CANDIDATES[name]
            config = config_for(variant, cand)
            rows = [r for r in load_features(variant, 15) if r["day"] in set(split["calibration"])]
            classified = {(r["symbol"], r["t"]): r for r in classify_rows(rows, config)}
            for key in rng.sample(sorted(classified), 60):
                symbol, t = key
                data = ds.load(symbol)
                alert = evaluate(symbol, ds.window_for(data, t.date()), data.provenance, t, config, None)
                prod_level = alert.level if alert.status == ma.STATUS_OK else ma.LEVEL_NONE
                checked += 1
                if prod_level != classified[key]["final_level"]:
                    mismatches += 1
                    print("MISMATCH", name, symbol, t, prod_level, classified[key]["final_level"])
        print(f"equivalence: {checked} örnek, {mismatches} uyuşmazlık")
        write_json("equivalence.json", {"checked": checked, "mismatches": mismatches})
        return
    features = {v: load_features(v, 15) for v in FEATURE_VARIANTS}
    if stage == "calibrate":
        cal = set(split["calibration"])
        results = [evaluate_candidate(name, features, cal)[0] for name in CANDIDATES]
        relvols = np.array([r["raw_relative_volume"] for r in features["F1"] if r["day"] in cal
                            and r["raw_relative_volume"] is not None])
        relvol_dist = {f"p{p}": round(float(np.percentile(relvols, p)), 3) for p in (50, 90, 99, 99.9)}
        relvols0 = np.array([r["raw_relative_volume"] for r in features["F0"] if r["day"] in cal
                             and r["raw_relative_volume"] is not None])
        relvol_dist0 = {f"p{p}": round(float(np.percentile(relvols0, p)), 3) for p in (50, 90, 99, 99.9)}
        top = select_top(results, SELECT_MIN_STRONG_ALERTS_CAL, 3)
        write_json("calibration.json", {"split": {k: [str(v[0]), str(v[-1]), len(v)] for k, v in split.items()},
                                        "relvol_F1": relvol_dist, "relvol_F0": relvol_dist0,
                                        "results": [_brief(r) for r in results], "top": top})
        for r in results:
            print(json.dumps(_brief(r), ensure_ascii=False))
        print("relvol F0", relvol_dist0, "F1", relvol_dist, "TOP:", top)
        return
    if stage == "validate":
        cal = read_json("calibration.json")
        val = set(split["validation"])
        results = [evaluate_candidate(name, features, val)[0] for name in cal["top"]]
        chosen = select_top(results, SELECT_MIN_STRONG_ALERTS_VAL, 1)
        for r in results:
            print(json.dumps(_brief(r), ensure_ascii=False))
        if not chosen:
            write_json("final_candidate.json", {"name": None, "reason": "doğrulamada ölçütü sağlayan aday yok",
                                                "validation": [_brief(r) for r in results]})
            print("FINAL_CANDIDATE yok")
            return
        name = chosen[0]
        variant, cand = CANDIDATES[name]
        relvol_cap = max(cal["relvol_F1"]["p99"], DEFAULT_CONFIG.volume_ratio_full)  # bileşen 5x'te doyar
        config = config_for(variant, {**cand, "relvol_cap": round(relvol_cap, 1)})
        write_json("final_candidate.json", {"name": name, "frozen_at": str(datetime.now(ISTANBUL_TZ)),
                                            "config": json.loads(config.model_dump_json()),
                                            "sha256": config_hash(config),
                                            "validation": [_brief(r) for r in results]})
        print("FINAL_CANDIDATE:", name, config_hash(config))
        return
    if stage == "holdout":
        if (ds.RUNS / "holdout.json").exists():
            raise SystemExit("holdout zaten çalıştırıldı; yeniden çalıştırma/optimizasyon yasak")
        final = read_json("final_candidate.json")
        if not final.get("name"):
            raise SystemExit("dondurulmuş aday yok")
        config = ma.MomentumAlertConfig(**final["config"])
        assert config_hash(config) == final["sha256"], "dondurulmuş yapılandırma değişmiş"
        hold = set(split["holdout"])
        variant = CANDIDATES[final["name"]][0]
        rows = classify_rows([r for r in features[variant] if r["day"] in hold], config)
        labeled, sessions = attach_labels(rows, hold)
        res = {"name": final["name"], "sha256": final["sha256"], "base_rate": base_rate(labeled, PRIMARY_X)}
        for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG):
            res[lvl.lower()] = summarize(labeled, sessions, lvl, PRIMARY_X, PRIMARY_E)
        res["sensitivity"] = {f"{lab}_x{x}_e{e}": {lvl: {k: summarize(labeled, sessions, lvl, x, e, lab)[k]
                                                           for k in ("precision", "recall", "false_positive_rate")}
                                                     for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG)}
                              for lab in ("mfe_60", "mfe_close", "ret_close") for x in SENSITIVITY_X
                              for e in SENSITIVITY_E}
        s, w = res["strong"], res["watch"]
        checks = {"min_strong_alerts": s["alert_sessions"] >= HOLDOUT_CRITERIA["min_strong_alerts"],
                  "precision_vs_base_rate": (s["precision"] or 0) >= HOLDOUT_CRITERIA["precision_vs_base_rate"]
                  * (res["base_rate"] or 1),
                  "max_strong_fpr": (s["false_positive_rate"] or 1) <= HOLDOUT_CRITERIA["max_strong_fpr"],
                  "min_strong_recall": (s["recall"] or 0) >= HOLDOUT_CRITERIA["min_strong_recall"],
                  "strong_precision_gt_watch": (s["precision"] or 0) > (w["precision"] or 0)}
        res["criteria"], res["checks"] = HOLDOUT_CRITERIA, checks
        res["verdict"] = "HOLDOUT PASS" if all(checks.values()) else "HOLDOUT FAIL"
        # Karşılaştırma için aynı holdout'ta başlangıç (C0) — seçimde KULLANILMAZ, yalnız rapor
        c0, _, _ = evaluate_candidate("C0_BASELINE", features, hold)
        res["c0_on_holdout"] = _brief(c0)
        write_json("holdout.json", res)
        print(json.dumps({k: v for k, v in res.items() if k != "sensitivity"}, ensure_ascii=False, default=str)[:4000])
        return
    if stage == "ktlev":
        final = read_json("final_candidate.json")
        config = ma.MomentumAlertConfig(**final["config"])
        days = [d for d in all_days if date(2026, 10, 1) <= d <= date(2026, 10, 12)]
        data = ds.load(ds.HOLDOUT_CASE)
        report = {}
        for label, cfg in (("FINAL_d15", config), ("FINAL_d0", config.model_copy(update={"provider_delay_minutes": 0})),
                           ("C0_d15", DEFAULT_CONFIG)):
            delay = cfg.provider_delay_minutes
            per_day = {}
            for day in days:
                window = ds.window_for(data, day)
                bars_day = data.bars[data.bars.index.date == day]
                prev = data.bars[data.bars.index.date < day]["Close"].iloc[-1]
                firsts = {}
                for t in eval_times(day, delay):
                    a = evaluate(ds.HOLDOUT_CASE, window, data.provenance, t, cfg, None)
                    for lvl in (ma.LEVEL_WATCH, ma.LEVEL_STRONG):
                        if lvl not in firsts and a.level in (lvl, ma.LEVEL_STRONG) and \
                                (lvl == ma.LEVEL_WATCH or a.level == ma.LEVEL_STRONG):
                            price = a.metrics["last_close"]
                            firsts[lvl] = {"eval": t.strftime("%H:%M"),
                                           "bar_end": a.signal_as_of.astimezone(ISTANBUL_TZ).strftime("%H:%M"),
                                           "price": round(price, 2), "vs_prev_close_pct": round((price / prev - 1) * 100, 2),
                                           "total_move_done_pct": round((price - 6.62) / (8.80 - 6.62) * 100, 1),
                                           "score": a.momentum_score}
                per_day[str(day)] = {"prev_close": round(float(prev), 2),
                                     "day_close": round(float(bars_day["Close"].iloc[-1]), 2), **firsts}
            report[label] = per_day
        write_json("ktlev_case.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    raise SystemExit(f"bilinmeyen aşama: {stage}")


if __name__ == "__main__":
    main(sys.argv[1])
