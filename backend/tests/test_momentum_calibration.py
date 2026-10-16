"""Momentum kalibrasyonu — sağlamlaştırılmış tabanlar, grup kuralı, ardışık doğrulama, metrikler, bölme ve holdout
koruması. Gerçek ağ/Firestore yok (sentetik barlar)."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.research.momentum_calibration import dataset as ds
from app.research.momentum_calibration import experiment as ex
from app.research.momentum_calibration.labels import label_at, session_outcome
from app.research.momentum_calibration.metrics import first_alerts, summarize
from app.services.momentum.early_momentum_engine import (DEFAULT_CONFIG, FeatureSnapshot, bist_tick_size,
                                                         classify_raw, classify_session_quality, compute_features,
                                                         confirm_level, evaluate)
from tests.test_momentum_engine import DAY, DELAY, FLAT, PRIOR, PROV, STEP, build, session

ROBUST = ma.MomentumAlertConfig(**ex.FEATURE_VARIANTS["F1"])
SPIKE = FLAT + [0.01, 0.01, 0.01, 0.012]
SPIKE_VOL = [1000.0] * 40 + [8000.0] * 4


def locked_day(d, price, volume=500.0):
    idx = pd.DatetimeIndex([datetime.combine(d, time(10, 0), tzinfo=ISTANBUL_TZ) + STEP * k for k in range(96)])
    return pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price, "Volume": volume}, index=idx)


def end_time(bars):
    return bars[bars.index.date == DAY].index[-1].to_pydatetime() + STEP + DELAY


# --- seans kalitesi -----------------------------------------------------------------------------------------------

def test_locked_session_classification():
    label, stats = classify_session_quality(locked_day(PRIOR[0], 10.0), 20)
    assert label == "LOCKED_OR_DEGENERATE" and stats["unique_closes"] == 1 and stats["identical_ohlc_ratio"] == 1.0
    normal = session(PRIOR[0], 100.0, FLAT * 2)
    assert classify_session_quality(normal, 20)[0] == "NORMAL"
    quiet = normal.copy()
    quiet["Volume"] = 0.0
    assert classify_session_quality(quiet, 20)[0] == "LOW_INFORMATION"
    assert classify_session_quality(normal.iloc[:10], 20)[0] == "LOW_INFORMATION"


# --- tabanlar ------------------------------------------------------------------------------------------------------

def locked_history_then(today_returns, today_vol):
    frames, price = [], 100.0
    for d in PRIOR:
        price *= 0.9
        frames.append(locked_day(d, price))
    return pd.concat(frames + [session(DAY, price, today_returns, today_vol)])


def test_minimum_quality_baseline_sample_fails_closed():
    bars = locked_history_then(SPIKE, SPIKE_VOL)
    snap = compute_features("T", bars, PROV, end_time(bars), ROBUST, None)
    assert snap.status == ma.STATUS_OK and snap.metrics["baseline_sessions"] == 0
    assert snap.metrics["excluded_locked_sessions"] == len(PRIOR)
    for key in ("price_impulse", "volume_anomaly", "range_expansion", "breakout"):
        assert snap.components[key] is None  # sahte güçlü kanıt yok
    assert evaluate("T", bars, PROV, end_time(bars), ROBUST, None).level == ma.LEVEL_NONE
    # Eski (C0) davranış aynı veride tabanı bozuk olduğu için alarm verirdi
    assert evaluate("T", bars, PROV, end_time(bars), DEFAULT_CONFIG, None).detected


def test_volatility_floor_tick_and_raw_vs_effective():
    bars = build(SPIKE, SPIKE_VOL)
    snap = compute_features("T", bars, PROV, end_time(bars), ROBUST, None)
    c = snap.metrics["last_close"]
    assert snap.metrics["sigma_effective"] >= bist_tick_size(c) / c - 1e-9
    assert snap.metrics["sigma_effective"] >= snap.metrics["sigma_raw"]
    assert bist_tick_size(1.5) == 0.01 and bist_tick_size(75) == 0.05 and bist_tick_size(3000) == 2.5


def sparse_day(d, price):
    """Barların %60'ında fiyat değişmiyor (medyan gerçek aralık 0) ama kilitli değil: 1 fiyat adımı oynuyor."""
    rows, idx = [], []
    tick = bist_tick_size(price)
    prev = price
    for k in range(96):  # 10 barda 4 hareketli bar (+1 adım, geri, −1 adım, geri): medyan gerçek aralık 0
        p = price + tick * (k % 10 == 0) - tick * (k % 10 == 5)
        rows.append({"Open": prev, "High": max(prev, p), "Low": min(prev, p), "Close": p, "Volume": 1000.0})
        prev = p
        idx.append(datetime.combine(d, time(10, 0), tzinfo=ISTANBUL_TZ) + STEP * k)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def test_range_floor_prevents_degenerate_full_strength():
    """Medyan gerçek aralık 0: tabansız ölçüm bileşeni 1.0'a (tam güç) iter; efektif taban sonlu oran verir."""
    frames = [sparse_day(d, 50.0) for d in PRIOR]
    assert classify_session_quality(frames[0], 20)[0] == "NORMAL"
    early = sparse_day(DAY, 50.0).iloc[:39]
    jump_t = early.index[-1] + STEP
    # ılımlı 2 fiyat adımlık bar: tabansız ölçüm bunu "tam güç" sayar, efektif taban saymaz
    jump = pd.DataFrame([{"Open": 50.0, "High": 50.1, "Low": 50.0, "Close": 50.1, "Volume": 1000.0}],
                        index=pd.DatetimeIndex([jump_t]))
    bars = pd.concat(frames + [early, jump])
    plain = compute_features("T", bars, PROV, end_time(bars), ROBUST.model_copy(update={"range_floor": False}), None)
    floored = compute_features("T", bars, PROV, end_time(bars), ROBUST, None)
    assert plain.metrics["raw_range_baseline"] == 0.0 and plain.components["range_expansion"] == 1.0
    assert floored.metrics["effective_range_baseline"] > 0 and floored.metrics["range_ratio"] is not None
    assert floored.components["range_expansion"] < 1.0


def test_relative_volume_raw_vs_effective_and_zero_baseline_protection():
    frames, price = [], 100.0
    for k, d in enumerate(PRIOR):
        vol = [0.0] * 96 if k < 3 else [1000.0] * 96  # ilk 3 seans sıfır hacimli (tabanı çökertir)
        frames.append(session(d, price, [((-1) ** j) * 0.001 for j in range(96)], vol, seed=k))
    today = session(DAY, price, SPIKE, SPIKE_VOL)
    bars = pd.concat(frames + [today])
    eff = compute_features("T", bars, PROV, end_time(bars), ROBUST.model_copy(update={"relvol_cap": 6.0}), None)
    assert eff.metrics["raw_relative_volume"] == pytest.approx(8.0, rel=0.01)  # sıfır örnekler dışlandı
    assert eff.metrics["relative_volume"] == 6.0  # skor katkısı tavanda doyar
    raw = compute_features("T", bars, PROV, end_time(bars), DEFAULT_CONFIG, None)
    assert raw.metrics["relative_volume"] == raw.metrics["raw_relative_volume"]


# --- kural ve doğrulama -----------------------------------------------------------------------------------------

def snap(components, persistent=True, session_return=1.0):
    base = {"price_impulse": 0.0, "volume_anomaly": 0.0, "breakout": 0.0, "range_expansion": 0.0, "reversal": 0.0,
            "vwap": 0.0, "event_catalyst": None}
    return FeatureSnapshot(ma.STATUS_OK, None, {}, {**base, **components}, {"session_return_pct": session_return},
                           persistent, False)


GROUPS = ma.MomentumAlertConfig(rule_mode="GROUPS")


def test_feature_groups_require_independent_evidence():
    # hacim + kırılım, fiyat ivmesi yok → alarm yok
    assert classify_raw(snap({"volume_anomaly": 1.0, "breakout": 1.0, "range_expansion": 1.0}), GROUPS)[0] == "NONE"
    # fiyat + aralık (aynı fiyat olayı) + hacim yok → en fazla WATCH (katılım grubu yok)
    lvl = classify_raw(snap({"price_impulse": 1.0, "range_expansion": 1.0, "breakout": 1.0, "vwap": 1.0}), GROUPS)[0]
    assert lvl == "WATCH"
    # fiyat yapısı + katılım + kalıcılık → STRONG
    assert classify_raw(snap({"price_impulse": 1.0, "volume_anomaly": 1.0, "breakout": 1.0, "vwap": 1.0,
                              "range_expansion": 0.5}), GROUPS)[0] == "STRONG"
    # aynı kanıt, kalıcılık yok → WATCH
    assert classify_raw(snap({"price_impulse": 1.0, "volume_anomaly": 1.0, "breakout": 1.0, "vwap": 1.0,
                              "range_expansion": 0.5}, persistent=False), GROUPS)[0] == "WATCH"


def test_min_session_return_gate():
    cfg = GROUPS.model_copy(update={"min_session_return_pct": 0.0})
    strong = {"price_impulse": 1.0, "volume_anomaly": 1.0, "breakout": 1.0, "vwap": 1.0, "range_expansion": 0.5}
    assert classify_raw(snap(strong, session_return=-3.0), cfg)[0] == "NONE"
    assert classify_raw(snap(strong, session_return=0.5), cfg)[0] == "STRONG"


@pytest.mark.parametrize("seq,k,n,expected", [
    (["NONE", "STRONG"], 2, 2, "NONE"),
    (["STRONG", "STRONG"], 2, 2, "STRONG"),
    (["WATCH", "STRONG"], 2, 2, "WATCH"),
    (["STRONG", "NONE", "STRONG"], 2, 3, "STRONG"),
    (["STRONG", "STRONG", "NONE"], 2, 3, "NONE"),  # sönmüş harekete alarm yok
])
def test_persistence_confirmation(seq, k, n, expected):
    assert confirm_level(seq, ma.MomentumAlertConfig(confirm_k=k, confirm_n=n)) == expected


def test_production_confirmation_matches_research_sequence():
    bars = build(SPIKE, SPIKE_VOL)
    t = end_time(bars)
    cfg = ROBUST.model_copy(update={"rule_mode": "GROUPS", "confirm_k": 2, "confirm_n": 2})
    rows = []
    for j in (1, 0):
        s = compute_features("T", bars, PROV, t - STEP * j, cfg, None)
        rows.append({"symbol": "T", "day": DAY, "t": t - STEP * j, "status": s.status, "components": s.components,
                     "persistent": s.persistent, "data_gap": s.data_gap,
                     "session_return_pct": (s.metrics or {}).get("session_return_pct")})
    research = ex.classify_rows(rows, cfg)[-1]["final_level"]
    assert evaluate("T", bars, PROV, t, cfg, None).level == research


def test_default_config_behaviour_unchanged_by_new_options():
    assert DEFAULT_CONFIG.rule_mode == "COMPONENT_COUNT" and DEFAULT_CONFIG.confirm_n == 1
    assert not DEFAULT_CONFIG.baseline_quality_filter and DEFAULT_CONFIG.relvol_mode == "RAW"


# --- metrikler, bölme, holdout koruması -------------------------------------------------------------------------

def test_session_first_alert_counting_and_labels():
    day = session(DAY, 100.0, [0.0] * 20 + [0.01] * 10 + [0.0] * 10)
    times = [datetime.combine(DAY, time(10, 0), tzinfo=ISTANBUL_TZ) + STEP * k for k in range(40)]
    labels = [label_at(day, t) for t in times]
    outcome = session_outcome(day)
    rows = [{"symbol": "A", "day": DAY, "t": t, "status": "OK", "final_level": ("STRONG" if k >= 22 else "NONE"),
             "label": lab} for k, (t, lab) in enumerate(zip(times, labels))]
    firsts = first_alerts(rows, "STRONG")
    assert len(firsts) == 1 and firsts[("A", DAY)]["t"] == times[22]  # 18 alarm değerlendirmesi, 1 seans alarmı
    m = summarize(rows, {("A", DAY): outcome}, "STRONG", 0.03, 0.05)
    assert m["alert_sessions"] == 1 and m["alert_evaluations_per_session"] == 18
    assert labels[22].entry == pytest.approx(day["Open"].iloc[22]) and labels[39].mfe_60 is not None


def test_vectorized_session_labels_match_reference():
    from app.research.momentum_calibration.labels import labels_for_session

    day = session(DAY, 100.0, list(np.random.RandomState(3).normal(0, 0.004, 96)))
    times = [datetime.combine(DAY, time(10, 0), tzinfo=ISTANBUL_TZ) + STEP * k + timedelta(minutes=2 * (k % 2))
             for k in range(0, 100)]
    _, fast = labels_for_session(day, DAY, times)
    for t, f in zip(times, fast):
        ref = label_at(day, t)
        for field in ("entry", "mfe_60", "mfe_close", "ret_close", "low_before"):
            a, b = getattr(f, field), getattr(ref, field)
            assert (a is None and b is None) or a == pytest.approx(b), (t, field)


def test_chronological_split_no_overlap():
    days = [date(2026, 7, 27) + timedelta(days=k) for k in range(40)]
    split = ds.split_sessions(days)
    assert split["calibration"][-1] < split["validation"][0] <= split["validation"][-1] < split["holdout"][0]
    assert days[:ds.WARMUP_SESSIONS] == sorted(set(days) - set(sum(split.values(), [])))


def test_ktlev_excluded_from_calibration_assets():
    assert ds.HOLDOUT_CASE == "KTLEV" and "KTLEV" not in ds.CALIBRATION_ASSETS
    assert len(ds.CALIBRATION_ASSETS) >= 30 and len(set(ds.CALIBRATION_ASSETS)) == len(ds.CALIBRATION_ASSETS)


def test_labels_only_for_requested_days(monkeypatch):
    """Seçim aşaması holdout günlerini etiketlemez: `attach_labels` yalnız verilen günleri işler."""
    rows = [{"symbol": "A", "day": d, "t": datetime.combine(d, time(11, 0), tzinfo=ISTANBUL_TZ), "status": "OK",
             "final_level": "NONE"} for d in (date(2026, 9, 1), date(2026, 10, 1))]
    bars = pd.concat([session(d, 100.0, FLAT) for d in (date(2026, 9, 1), date(2026, 10, 1))])
    monkeypatch.setattr(ds, "load", lambda s: ds.AssetData(s, bars, PROV, datetime(2026, 10, 2)))
    labeled, sessions = ex.attach_labels(rows, {date(2026, 9, 1)})
    assert set(k[1] for k in sessions) == {date(2026, 9, 1)} and len(labeled) == 1


def test_holdout_runs_once_and_requires_frozen_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "RUNS", tmp_path)
    monkeypatch.setattr(ex, "splits", lambda: ([], {"calibration": [], "validation": [], "holdout": []}))
    monkeypatch.setattr(ex, "load_features", lambda v, d, tag="universe": [])
    (tmp_path / "holdout.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="zaten"):
        ex.main("holdout")
    (tmp_path / "holdout.json").unlink()
    cfg = ex.config_for("F1", {"rule_mode": "GROUPS"})
    ex.write_json("final_candidate.json", {"name": "C2_GROUP_EVIDENCE", "config": cfg.model_dump(mode="json"),
                                           "sha256": "bozuk"})
    with pytest.raises(AssertionError, match="değişmiş"):
        ex.main("holdout")


def test_config_hash_stable_and_sensitive():
    a, b = ex.config_for("F1", {"rule_mode": "GROUPS"}), ex.config_for("F1", {"rule_mode": "GROUPS"})
    assert ex.config_hash(a) == ex.config_hash(b)
    assert ex.config_hash(a) != ex.config_hash(a.model_copy(update={"watch_score": 41.0}))


def test_research_classification_deterministic():
    bars = build(SPIKE, SPIKE_VOL)
    t = end_time(bars)
    rows = []
    for j in range(4, -1, -1):
        s = compute_features("T", bars, PROV, t - STEP * j, ROBUST, None)
        rows.append({"symbol": "T", "day": DAY, "t": t - STEP * j, "status": s.status, "components": s.components,
                     "persistent": s.persistent, "data_gap": s.data_gap,
                     "session_return_pct": (s.metrics or {}).get("session_return_pct")})
    cfg = ex.config_for("F1", ex.CANDIDATES["C3_PERSISTENCE"][1])
    assert ex.classify_rows(rows, cfg) == ex.classify_rows(list(rows), cfg)


def test_research_features_ignore_future_bars():
    bars = build(SPIKE, SPIKE_VOL)
    t = end_time(bars)
    future = pd.DataFrame([{"Open": 1, "High": 500, "Low": 1, "Close": 400, "Volume": 1e9}] * 5,
                          index=pd.DatetimeIndex([bars.index[-1] + STEP * (k + 1) for k in range(5)]))
    a = compute_features("T", bars, PROV, t, ROBUST, None)
    b = compute_features("T", pd.concat([bars, future]), PROV, t, ROBUST, None)
    assert a.components == b.components and a.metrics == b.metrics
