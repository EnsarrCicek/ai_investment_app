"""Erken momentum — genişletilmiş (Round 2) öznitelikler. SAF fonksiyonlar; ağ/Firestore/saat çağrısı YOK.

Üretim varsayılanına BAĞLI DEĞİLDİR: tarayıcı/API bu modülü kullanmaz (Round 2 araştırması; production audit ayrı).

Nedensellik (lookahead yok): `bar_features` her satırı yalnız o bara KADARKİ bugünkü barlar, önceki seanslar ve
zaman damgası aynı/öncesi olan benchmark barlarıyla hesaplar. Bu yüzden tam gün üzerinde hesaplanan k. satır, veri
k. barda kesilmiş olsaydı hesaplanacak satırla birebir aynıdır (test edilir). Üretim yolu (`extended_snapshot`)
aynı fonksiyonun son satırıdır — araştırma ve üretim aynı matematiği kullanır.

Ölçekten bağımsızlık: getiriler log, eğimler ve ivme bar başına σ birimindedir (σ = Round 1 HYBRID_TICK tabanı:
kaliteli önceki seansların gürbüz bar σ'sı ile 1 fiyat adımı/fiyat'ın büyüğü).

Eksik veri: yetersiz geçmişte değer `None` (uydurma 0 YOK); her öznitelik `FeatureValue(value, confidence,
samples)` olarak taşınır.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.services.momentum.early_momentum_engine import (SESSION_LOCKED, SESSION_NORMAL, _prepare, _raw_sigma,
                                                         bist_tick_size, classify_session_quality)


class ExtendedFeatureConfig(BaseModel):
    """RESEARCH DEFAULTS (Round 2). Pencereler 5 dk bar sayısıdır."""

    model_config = ConfigDict(frozen=True)

    interval_minutes: int = 5
    provider_delay_minutes: int = 15
    window_sessions: int = 15  # canlı tarayıcı penceresi (bugün dahil)
    min_bars_per_prior_session: int = 20
    min_quality_sessions: int = 3
    full_confidence_sessions: int = 10  # bu kadar kaliteli taban seansında güven 1.0
    locked_lookback_sessions: int = 5
    locked_regime_min: int = 2  # son 5 seansın ≥2'si kilitliyse RECENT_LOCKED_REGIME
    locked_fallback_confidence: float = 0.3
    return_windows: tuple[int, ...] = (1, 3, 6, 12)  # 5/15/30/60 dk
    slope_windows: tuple[int, ...] = (3, 6, 12)  # 15/30/60 dk
    accel_short_bars: int = 3  # son 15 dk eğimi
    accel_long_bars: int = 12  # ondan önceki 60 dk eğimi
    breakout_lookback_bars: int = 48
    atr_bars: int = 14
    range_lookback_bars: int = 48
    touch_atr: float = 0.25  # önceki tepeye bu kadar ATR yakın barlar "dokunuş"
    breakout_volume_confirm: float = 1.5
    vwap_slope_bars: int = 6
    reversal_sessions: int = 10
    min_slot_samples: int = 3  # aynı saat dilimi hacim tabanı için en az örnek
    min_bench_rv_bars: int = 6


EXT_DEFAULT = ExtendedFeatureConfig()

# Öznitelik → (gereken örnek sayısı) — güven = taban güveni × min(1, örnek/gereken)
_REQUIRED = {**{f"ret_z_{k}": k for k in (1, 3, 6, 12)}, **{f"rel_ret_z_{k}": k for k in (1, 3, 6, 12)},
             **{f"slope_{k}": k for k in (3, 6, 12)}, "accel": 12, "rel_accel": 12, "vol_accel": 6,
             "relvol_3": 3, "vwap_slope": 6}


@dataclass(frozen=True)
class FeatureValue:
    value: float | bool | None
    confidence: float
    samples: int


@dataclass
class Baseline:
    """Önceki seanslardan (bugün HARİÇ) türetilen tabanlar."""

    sigma_raw: float | None
    confidence: float
    quality_sessions: int
    recent_locked_sessions: int
    recent_locked_regime: bool
    prev_close: float | None
    prev_high: float | None
    prev_low: float | None
    session_closes: np.ndarray
    slot_volume: dict = field(default_factory=dict)  # saat → medyan pozitif hacim (kaliteli seanslar)
    hist_high: np.ndarray = field(default_factory=lambda: np.empty(0))  # kırılım için tüm önceki barlar
    hist_tr: np.ndarray = field(default_factory=lambda: np.empty(0))  # ATR/aralık tabanı için kaliteli barlar
    hist_last_close: float | None = None


def _true_range_arr(high, low, close, first_prev):
    prev = np.concatenate([[first_prev], close[:-1]]) if len(close) else close
    return np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)]) if len(close) else close


def build_baseline(prior: pd.DataFrame, cfg: ExtendedFeatureConfig = EXT_DEFAULT) -> Baseline:
    days = [(d, g) for d, g in prior.groupby(prior.index.date) if len(g) >= cfg.min_bars_per_prior_session]
    days = days[-(cfg.window_sessions - 1):]
    if not days:
        return Baseline(None, 0.0, 0, 0, False, None, None, None, np.empty(0))
    labels = [classify_session_quality(g, cfg.min_bars_per_prior_session)[0] for _, g in days]
    normal = [g for (_, g), lab in zip(days, labels) if lab == SESSION_NORMAL]
    recent_locked = sum(lab == SESSION_LOCKED for lab in labels[-cfg.locked_lookback_sessions:])
    regime = recent_locked >= cfg.locked_regime_min
    if len(normal) >= cfg.min_quality_sessions:
        sigma = _raw_sigma(pd.concat(normal))
        conf = min(1.0, len(normal) / cfg.full_confidence_sessions)
    elif regime:  # kilit rejimi: taban zayıf ama kör değil — kilitsiz seanslar (varsa) + fiyat adımı tabanı
        unlocked = [g for (_, g), lab in zip(days, labels) if lab != SESSION_LOCKED]
        sigma = _raw_sigma(pd.concat(unlocked)) if unlocked else 0.0
        conf = cfg.locked_fallback_confidence
    else:
        sigma, conf = None, 0.0
    slot = {}
    for g in normal:
        for ts, v in zip(g.index, g["Volume"].to_numpy()):
            if v > 0:
                slot.setdefault(ts.time(), []).append(float(v))
    slot_volume = {t: float(np.median(v)) for t, v in slot.items() if len(v) >= cfg.min_slot_samples}
    all_prior = pd.concat([g for _, g in days])
    if normal:
        q = pd.concat(normal)
        hist_tr = _true_range_arr(q["High"].to_numpy(), q["Low"].to_numpy(), q["Close"].to_numpy(),
                                  float(q["Open"].iloc[0]))
    else:
        hist_tr = np.empty(0)
    last = days[-1][1]
    return Baseline(sigma, conf, len(normal), recent_locked, regime, float(last["Close"].iloc[-1]),
                    float(last["High"].max()), float(last["Low"].min()),
                    np.array([float(g["Close"].iloc[-1]) for _, g in days[-cfg.reversal_sessions:]]),
                    slot_volume, all_prior["High"].to_numpy(), hist_tr, float(all_prior["Close"].iloc[-1]))


def _slope(y: np.ndarray) -> float | None:
    n = len(y)
    if n < 3 or not np.all(np.isfinite(y)):
        return None
    x = np.arange(n, dtype=float)
    x -= x.mean()
    return float(np.dot(x, y - y.mean()) / np.dot(x, x))


def bench_sigma(prior: pd.DataFrame, cfg: ExtendedFeatureConfig = EXT_DEFAULT) -> float | None:
    days = [g for _, g in prior.groupby(prior.index.date) if len(g) >= cfg.min_bars_per_prior_session]
    days = days[-(cfg.window_sessions - 1):]
    if len(days) < cfg.min_quality_sessions:
        return None
    s = _raw_sigma(pd.concat(days))
    return s if s > 0 else None


def bar_features(day: pd.DataFrame, base: Baseline, bench_day: pd.DataFrame | None = None,
                 bench_prev_close: float | None = None, bench_sigma_raw: float | None = None,
                 cfg: ExtendedFeatureConfig = EXT_DEFAULT) -> pd.DataFrame:
    """Bugünün her barı için öznitelikler (satır i yalnız ≤ i barlarına dayanır)."""
    n = len(day)
    o, h, lo, c, v = (day[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "Volume"))
    rows: list[dict] = []
    if n == 0 or base.prev_close is None:
        return pd.DataFrame(rows, index=day.index[:0])
    L = np.log(np.concatenate([[base.prev_close], c]))  # L[0] = önceki kapanış (çapa), L[i+1] = bar i
    # benchmark: yalnız AYNI bar başlangıcına sahip bar (asof/ileri doldurma YOK)
    if bench_day is not None and bench_prev_close:
        bmap = dict(zip(bench_day.index, bench_day["Close"].to_numpy(dtype=float)))
        bc = np.array([bmap.get(ts, np.nan) for ts in day.index])
        B = np.log(np.concatenate([[bench_prev_close], bc]))
        bench_times = bench_day.index
        bench_closes = bench_day["Close"].to_numpy(dtype=float)
    else:
        B, bench_times, bench_closes = None, None, None
    R = L - B if B is not None else None
    tr = _true_range_arr(h, lo, c, base.prev_close)
    tr_all = np.concatenate([base.hist_tr, tr])
    hi_all = np.concatenate([base.hist_high, h])
    P, Pq = len(base.hist_high), len(base.hist_tr)
    slots = [ts.time() for ts in day.index]
    slot_base = np.array([base.slot_volume.get(t, np.nan) for t in slots])
    typical = (h + lo + c) / 3
    cum_pv, cum_v = np.cumsum(typical * v), np.cumsum(v)
    vwap = np.where(cum_v > 0, cum_pv / np.where(cum_v > 0, cum_v, 1), np.nan)
    sess_low = np.minimum.accumulate(lo)
    ph_hist = np.full(n, np.nan)
    above_hist = np.zeros(n, dtype=bool)

    def ret(series, i, k):
        j = max(0, i + 1 - k)
        a, b = series[i + 1], series[j]
        return (a - b, i + 1 - j) if np.isfinite(a) and np.isfinite(b) else (None, 0)

    def slope_win(series, end, k):  # end: L indeksi (dahil); son k bar → k+1 nokta
        start = max(0, end - k)
        return _slope(series[start:end + 1]), end - start

    for i in range(n):
        sig = None
        if base.sigma_raw is not None:
            sig = max(base.sigma_raw, bist_tick_size(c[i]) / c[i])
        row: dict = {"n_bars": i + 1, "baseline_confidence": base.confidence,
                     "baseline_sessions": base.quality_sessions, "recent_locked_sessions": base.recent_locked_sessions,
                     "recent_locked_regime": base.recent_locked_regime, "sigma": sig,
                     "session_ret_pct": (c[i] / base.prev_close - 1) * 100}
        for k in cfg.return_windows:
            r, kk = ret(L, i, k)
            row[f"ret_z_{k}"] = r / (sig * math.sqrt(kk)) if (r is not None and sig) else None
            row[f"ret_z_{k}__n"] = kk
            if R is not None:
                rr, rk = ret(R, i, k)
                row[f"rel_ret_z_{k}"] = rr / (sig * math.sqrt(rk)) if (rr is not None and sig) else None
                row[f"rel_ret_z_{k}__n"] = rk
            else:
                row[f"rel_ret_z_{k}"], row[f"rel_ret_z_{k}__n"] = None, 0
        zs = [row[f"ret_z_{k}"] for k in (3, 6, 12) if row[f"ret_z_{k}"] is not None]
        row["price_z_ext"] = max(zs) if zs else None
        row["session_ret_z"] = (L[i + 1] - L[0]) / (sig * math.sqrt(i + 1)) if sig else None
        for k in cfg.slope_windows:
            s, kk = slope_win(L, i + 1, k)
            row[f"slope_{k}"] = s / sig if (s is not None and sig) else None
            row[f"slope_{k}__n"] = kk

        def accel_of(series, end):
            short, _ = slope_win(series, end, cfg.accel_short_bars)
            long_end = end - cfg.accel_short_bars
            if long_end < 2:
                return None, 0
            long, kk = slope_win(series, long_end, cfg.accel_long_bars)
            if short is None or long is None or not sig:
                return None, kk
            return (short - long) / sig, kk

        row["accel"], row["accel__n"] = accel_of(L, i + 1)
        if R is not None:
            row["rel_accel"], row["rel_accel__n"] = accel_of(R, i + 1)
        else:
            row["rel_accel"], row["rel_accel__n"] = None, 0
        # ivme sürekliliği: son 3 değerlendirmede ivme > 0 sayısı ve 15 dk eğimin iyileşme sayısı
        acc_hist = [accel_of(L, j + 1)[0] for j in range(max(0, i - 2), i + 1)]
        row["accel_pos_3"] = sum(a is not None and a > 0 for a in acc_hist)
        s3 = [slope_win(L, j + 1, 3)[0] for j in range(max(0, i - 3), i + 1)]
        row["slope_improving_3"] = sum(a is not None and b is not None and b > a for a, b in zip(s3, s3[1:]))
        # gap ve gap sonrası devam
        row["gap_pct"] = (o[0] / base.prev_close - 1) * 100
        row["gap_follow_z"] = math.log(c[i] / o[0]) / (sig * math.sqrt(i + 1)) if sig else None
        # hacim (aynı saat dilimi tabanı; sıfıra yakın payda → None)
        row["relvol_1"] = v[i] / slot_base[i] if (np.isfinite(slot_base[i]) and slot_base[i] > 0 and v[i] > 0) \
            else None
        w = slice(max(0, i - 2), i + 1)
        b3 = slot_base[w]
        row["relvol_3"] = (float(v[w].sum() / b3.sum()) if np.all(np.isfinite(b3)) and b3.sum() > 0 and v[i] > 0
                           else None)
        row["relvol_3__n"] = i + 1 - max(0, i - 2)
        prev_rv = rows[i - 3]["relvol_3"] if i >= 3 else None
        row["vol_accel"] = (math.log(row["relvol_3"] / prev_rv) if (row["relvol_3"] and prev_rv) else None)
        row["vol_accel__n"] = min(i + 1, 6)
        # kırılım kalitesi (önceki N bar, mevcut bar HARİÇ)
        p = P + i
        lb = hi_all[max(0, p - cfg.breakout_lookback_bars):p]
        q = Pq + i
        atr_w = tr_all[max(0, q - cfg.atr_bars):q]
        tr_w = tr_all[max(0, q - cfg.range_lookback_bars):q]
        floor = sig * c[i] if sig else 0.0
        atr = max(float(np.mean(atr_w)) if len(atr_w) else 0.0, floor)
        tr_base = max(float(np.median(tr_w)) if len(tr_w) else 0.0, floor)
        if len(lb):
            ph = float(lb.max())
            ph_hist[i] = ph
            above_hist[i] = c[i] > ph
            row["breakout_dist_atr"] = (c[i] - ph) / atr if atr > 0 else None
            row["breakout_touches"] = int(np.sum(lb >= ph - cfg.touch_atr * atr)) if atr > 0 else None
            age = 0
            for j in range(i, -1, -1):
                if not above_hist[j]:
                    break
                age += 1
            row["breakout_age"] = age
        else:
            row["breakout_dist_atr"], row["breakout_touches"], row["breakout_age"] = None, None, None
        row["breakout_vol_confirm"] = (bool(above_hist[i] and row["relvol_3"] >= cfg.breakout_volume_confirm)
                                       if row["relvol_3"] is not None else None)
        row["range_ratio"] = tr[i] / tr_base if tr_base > 0 else None
        # VWAP yapısı
        if np.isfinite(vwap[i]):
            row["vwap_dist_pct"] = (c[i] / vwap[i] - 1) * 100
            valid = np.isfinite(vwap[:i + 1])
            row["vwap_time_above"] = float(np.mean(c[:i + 1][valid] > vwap[:i + 1][valid]))
            row["vwap_reclaim"] = bool(c[i] > vwap[i] and np.any(c[:i][valid[:i]] < vwap[:i][valid[:i]]))
            k = cfg.vwap_slope_bars
            row["vwap_slope"] = (math.log(vwap[i] / vwap[i - k]) / (k * sig)
                                 if (i >= k and np.isfinite(vwap[i - k]) and sig) else None)
        else:
            row["vwap_dist_pct"], row["vwap_time_above"], row["vwap_reclaim"], row["vwap_slope"] = (None,) * 4
        # dönüş kalitesi (önceki seans kapanışları; bugün yalnız ≤ i)
        sc = base.session_closes
        if len(sc) >= 3:
            pk = int(np.argmax(sc))
            tpos = pk + int(np.argmin(sc[pk:]))
            trough = float(sc[tpos])
            row["prior_drawdown_pct"] = (1 - trough / float(sc[pk])) * 100
            row["base_sessions"] = len(sc) - 1 - tpos
            row["rebound_pct"] = (c[i] / trough - 1) * 100
        else:
            row["prior_drawdown_pct"], row["base_sessions"], row["rebound_pct"] = None, None, None
        row["higher_low"] = bool(sess_low[i] > base.prev_low) if base.prev_low is not None else None
        row["reclaim_prev_high"] = bool(c[i] > base.prev_high) if base.prev_high is not None else None
        # benchmark gerçekleşen oynaklık oranı (rejim bağlamı) — yalnız bu bara kadarki benchmark barları
        if bench_times is not None and bench_sigma_raw:
            bmask = bench_times <= day.index[i]
            br = np.diff(np.log(bench_closes[bmask]))
            row["bench_rv_ratio"] = (float(np.std(br)) / bench_sigma_raw if len(br) >= cfg.min_bench_rv_bars
                                     else None)
        else:
            row["bench_rv_ratio"] = None
        rows.append(row)
    return pd.DataFrame(rows, index=day.index)


def split_window(bars: pd.DataFrame, cutoff: datetime, today) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _prepare(bars, cutoff)
    return df[df.index.date == today], df[df.index.date < today]


def to_feature_values(row: pd.Series) -> dict[str, FeatureValue]:
    conf0 = float(row["baseline_confidence"])
    out = {}
    for name, val in row.items():
        if name.endswith("__n"):
            continue
        val = None if (val is None or (isinstance(val, float) and math.isnan(val))) else val
        need = _REQUIRED.get(name)
        samples = int(row.get(f"{name}__n", row["n_bars"])) if need else int(row["n_bars"])
        conf = 0.0 if val is None else conf0 * (min(1.0, samples / need) if need else 1.0)
        out[name] = FeatureValue(val, round(conf, 3), samples)
    return out


def extended_snapshot(bars: pd.DataFrame, evaluated_at: datetime, cfg: ExtendedFeatureConfig = EXT_DEFAULT,
                      benchmark_bars: pd.DataFrame | None = None) -> dict[str, FeatureValue] | None:
    """Üretim yolu: değerlendirme anında erişilebilir (gecikme dahil) barlarla son barın öznitelikleri."""
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at saat dilimi içermeli")
    cutoff = evaluated_at - timedelta(minutes=cfg.provider_delay_minutes + cfg.interval_minutes)
    today = evaluated_at.astimezone(ISTANBUL_TZ).date()
    day, prior = split_window(bars, cutoff, today)
    if day.empty:
        return None
    base = build_baseline(prior, cfg)
    bench_day = bench_prev = bench_sig = None
    if benchmark_bars is not None and not benchmark_bars.empty:
        bday, bprior = split_window(benchmark_bars, cutoff, today)
        if not bprior.empty:
            bench_day, bench_prev, bench_sig = bday, float(bprior["Close"].iloc[-1]), bench_sigma(bprior, cfg)
    feats = bar_features(day, base, bench_day, bench_prev, bench_sig, cfg)
    return to_feature_values(feats.iloc[-1]) if len(feats) else None
