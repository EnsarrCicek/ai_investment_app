"""EarlyMomentumAlertEngine — gün içi olağandışı yukarı yönlü momentum dedektörü (SAF fonksiyon).

AL/SAT/TUT üretmez; DecisionEngine, teknik skor, portföy veya limit kontrolüne girdi vermez. Ağ, Firestore ve saat
çağrısı YOKTUR: aynı bar listesi + aynı olay bağlamı + aynı `evaluated_at` → her zaman aynı sonuç.

Gelecek verisi sızıntısı yok:
* Yalnız `bar_başlangıcı + aralık <= evaluated_at − sağlayıcı_gecikmesi` olan barlar kullanılır (sağlayıcıda hâlâ
  oluşan bar ve değerlendirme anından sonraki barlar dışlanır).
* Olaylar yalnız `published_at <= evaluated_at` ve `available_at <= evaluated_at` ise görülür.
* Kırılım/aralık/oynaklık tabanları mevcut barı HARİÇ tutar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ, SESSION_CLOSE, SESSION_OPEN
from app.models import momentum_alert as ma
from app.services.market_data.trading_calendar import BIST_HALF_DAY_SESSIONS, expected_trading_sessions

# Takvim arefe (yarım gün) günlerini listeler ama kapanış saatini tanımlamaz; BIST pay piyasasında arefe günleri
# sürekli işlem 12:30'da biter (VARSAYIM, takvimde saat alanı olmadığı için burada belgelenir).
HALF_DAY_SESSION_CLOSE = time(12, 30)
MIN_BAR_SIGMA = 0.001  # tavan/taban kilitli günlerde MAD=0 olabilir; bar başına %0.1 alt sınır (sıfıra bölme yok)
VWAP_DISTANCE_FULL = 0.02


@dataclass(frozen=True)
class CatalystEvent:
    """Yakın tarihli olay bağlamı (ör. haber analizi). `available_at`: sistemin bu analizi ürettiği an."""

    published_at: datetime
    available_at: datetime
    sentiment: float  # -100..100
    confidence: float  # 0..1
    reliability: float | None = None  # 0..1, bilinmiyorsa None


DEFAULT_CONFIG = ma.MomentumAlertConfig()


def _clip(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _session_state(evaluated_at: datetime, delay: timedelta) -> tuple[str | None, str | None]:
    """(market_session, hata nedeni). Hata nedeni yalnız takvim desteklemediğinde."""
    local = evaluated_at.astimezone(ISTANBUL_TZ)
    day = local.date()
    sessions = expected_trading_sessions(day, day)
    if sessions is None:
        return None, "CALENDAR_UNSUPPORTED"
    if not sessions:
        return "CLOSED", None
    close = HALF_DAY_SESSION_CLOSE if day in BIST_HALF_DAY_SESSIONS.get(day.year, frozenset()) else SESSION_CLOSE
    open_at = datetime.combine(day, SESSION_OPEN, tzinfo=ISTANBUL_TZ)
    # Gecikmeli veri seans kapanışından sonra da o seansa aittir: kapanış + gecikmeye kadar canlı sayılır.
    close_at = datetime.combine(day, close, tzinfo=ISTANBUL_TZ) + delay
    return ("OPEN" if open_at <= local < close_at else "CLOSED"), None


def _prepare(bars: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    df = bars[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    idx = pd.DatetimeIndex(df.index)
    df.index = idx.tz_convert(ISTANBUL_TZ) if idx.tz is not None else idx.tz_localize(ISTANBUL_TZ)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    valid = ((df[["Open", "High", "Low", "Close"]] > 0).all(axis=1) & (df["High"] >= df[["Open", "Close"]].max(axis=1))
             & (df["Low"] <= df[["Open", "Close"]].min(axis=1)) & (df["Volume"] >= 0))
    df = df[valid]
    return df[df.index <= pd.Timestamp(cutoff).tz_convert(ISTANBUL_TZ)]


def _robust_sigma(prior: pd.DataFrame) -> float:
    rets = []
    for _, day in prior.groupby(prior.index.date):
        r = np.diff(np.log(day["Close"].to_numpy()))
        rets.extend(r.tolist())
    if not rets:
        return MIN_BAR_SIGMA
    arr = np.asarray(rets)
    mad = float(np.median(np.abs(arr - np.median(arr)))) * 1.4826
    return max(mad, float(np.std(arr)) if mad == 0 else mad, MIN_BAR_SIGMA)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
                     axis=1).max(axis=1)


def _raw_sigma(prior: pd.DataFrame) -> float:
    """Seans içi 5 dk log getirilerinin gürbüz (MAD) σ'sı; MAD 0 ise std; veri yoksa 0 (TABAN UYGULANMAZ)."""
    rets = []
    for _, day in prior.groupby(prior.index.date):
        rets.extend(np.diff(np.log(day["Close"].to_numpy())).tolist())
    if not rets:
        return 0.0
    arr = np.asarray(rets)
    mad = float(np.median(np.abs(arr - np.median(arr)))) * 1.4826
    return mad if mad > 0 else float(np.std(arr))


def bist_tick_size(price: float) -> float:
    """BIST pay piyasası fiyat adımı (fiyat aralığına göre)."""
    for upper, tick in ((20, 0.01), (50, 0.02), (100, 0.05), (250, 0.10), (500, 0.25), (1000, 0.50), (2500, 1.00)):
        if price < upper:
            return tick
    return 2.50


# Seans kalitesi (araştırma sınıflandırması; KTLEV'e özel değildir)
SESSION_NORMAL = "NORMAL"
SESSION_LOW_INFORMATION = "LOW_INFORMATION"
SESSION_LOCKED = "LOCKED_OR_DEGENERATE"
LOCKED_IDENTICAL_OHLC_RATIO = 0.8  # barların ≥%80'inde O=H=L=C → tavan/taban kilidi veya işlem yok
LOCKED_MAX_UNIQUE_CLOSES = 2
LOCKED_MAX_RANGE_PCT = 0.1  # gün içi en yüksek-en düşük farkı < %0.1
LOW_INFO_ZERO_VOLUME_RATIO = 0.5
LOW_INFO_MIN_CLOSE_CHANGES = 10


def classify_session_quality(day: pd.DataFrame, min_bars: int) -> tuple[str, dict]:
    """Tek seansın tabanlarda kullanılabilirliği: NORMAL | LOW_INFORMATION | LOCKED_OR_DEGENERATE."""
    o, h, low, c, v = (day[k].to_numpy() for k in ("Open", "High", "Low", "Close", "Volume"))
    n = len(day)
    stats = {"bars": n, "unique_closes": int(len(np.unique(c))) if n else 0,
             "close_changes": int(np.count_nonzero(np.diff(c))) if n > 1 else 0,
             "range_pct": float((h.max() - low.min()) / np.mean(c) * 100) if n else 0.0,
             "zero_volume_ratio": float(np.mean(v <= 0)) if n else 1.0,
             "identical_ohlc_ratio": float(np.mean((o == h) & (h == low) & (low == c))) if n else 1.0}
    if n and (stats["identical_ohlc_ratio"] >= LOCKED_IDENTICAL_OHLC_RATIO
              or stats["unique_closes"] <= LOCKED_MAX_UNIQUE_CLOSES or stats["range_pct"] < LOCKED_MAX_RANGE_PCT):
        return SESSION_LOCKED, stats
    if (n < min_bars or stats["zero_volume_ratio"] >= LOW_INFO_ZERO_VOLUME_RATIO
            or stats["close_changes"] < LOW_INFO_MIN_CLOSE_CHANGES):
        return SESSION_LOW_INFORMATION, stats
    return SESSION_NORMAL, stats


@dataclass(frozen=True)
class FeatureSnapshot:
    """Bir değerlendirme anının öznitelikleri (eşikten bağımsız). `status != OK` ise bileşen yoktur."""

    status: str
    reason: str | None
    base: dict
    components: dict | None = None
    metrics: dict | None = None
    persistent: bool = False
    data_gap: bool = False


def compute_features(asset: str, bars: pd.DataFrame, provenance: dict, evaluated_at: datetime,
                     config: ma.MomentumAlertConfig = DEFAULT_CONFIG,
                     events: list[CatalystEvent] | None = None) -> FeatureSnapshot:
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at saat dilimi içermeli")
    interval = timedelta(minutes=config.interval_minutes)
    delay = timedelta(minutes=config.provider_delay_minutes)
    base: dict = {}

    def fail(status: str, reason: str | None) -> FeatureSnapshot:
        return FeatureSnapshot(status, reason, dict(base))

    if provenance.get("identity_check") != "MATCH":
        return fail(ma.STATUS_IDENTITY_UNVERIFIED, "Sağlayıcı sembol/borsa/para birimi kimliği doğrulanamadı.")
    session, calendar_error = _session_state(evaluated_at, delay)
    if calendar_error:
        return fail(ma.STATUS_ERROR, calendar_error)
    if session != "OPEN":
        base["market_session"] = session
        return fail(ma.STATUS_MARKET_CLOSED, "Piyasa kapalı: son bar canlı momentum olarak yorumlanmaz.")
    base["market_session"] = session

    # Yalnız tamamlanmış ve değerlendirme anında (gecikme dahil) erişilebilir barlar.
    df = _prepare(bars, evaluated_at - delay - interval)
    if df.empty:
        return fail(ma.STATUS_INSUFFICIENT_DATA, "Kullanılabilir tamamlanmış bar yok.")
    last_end = df.index[-1].to_pydatetime() + interval
    age = (evaluated_at - last_end).total_seconds()
    base["data_age_seconds"] = round(age, 1)
    base["signal_as_of"] = last_end
    today = evaluated_at.astimezone(ISTANBUL_TZ).date()
    tolerance = (delay + interval * config.freshness_slack_intervals).total_seconds()
    if df.index[-1].date() != today or age > tolerance:
        return fail(ma.STATUS_STALE_DATA, f"Son tamamlanmış bar {int(age // 60)} dk eski (tolerans "
                                          f"{int(tolerance // 60)} dk: sağlayıcı gecikmesi + "
                                          f"{config.freshness_slack_intervals} bar).")

    session_df = df[df.index.date == today]
    prior = df[df.index.date < today]
    prior_sessions = [d for d, g in prior.groupby(prior.index.date) if len(g) >= config.min_bars_per_prior_session]
    if len(session_df) < config.min_session_bars or len(prior_sessions) < config.min_prior_sessions:
        return fail(ma.STATUS_INSUFFICIENT_DATA,
                    f"Yetersiz bar: bu seans {len(session_df)} (en az {config.min_session_bars}), önceki tam "
                    f"seans {len(prior_sessions)} (en az {config.min_prior_sessions}).")
    prior = prior[np.isin(prior.index.date, prior_sessions)]
    df = pd.concat([prior, session_df])
    close = df["Close"].to_numpy()
    i = len(df) - 1
    c = close[i]
    metrics: dict = {"last_close": float(c)}
    metrics["session_return_pct"] = round((c / float(prior["Close"].iloc[-1]) - 1) * 100, 3)

    # --- taban seansları (kalite filtresi açıksa kilitli/düşük bilgili seanslar çıkarılır) ---
    if config.baseline_quality_filter:
        labels = {d: classify_session_quality(g, config.min_bars_per_prior_session)[0]
                  for d, g in prior.groupby(prior.index.date)}
        quality_days = [d for d, label in labels.items() if label == SESSION_NORMAL]
        metrics["baseline_sessions"] = len(quality_days)
        metrics["excluded_locked_sessions"] = sum(label == SESSION_LOCKED for label in labels.values())
        metrics["excluded_low_info_sessions"] = sum(label == SESSION_LOW_INFORMATION for label in labels.values())
        baseline_prior = prior[np.isin(prior.index.date, quality_days)]
        baseline_ok = len(quality_days) >= config.min_quality_sessions
    else:
        baseline_prior, baseline_ok = prior, True
        quality_days = None

    # --- fiyat ivmesi (oynaklığa göre normalize) ---
    if config.volatility_floor == "HYBRID_TICK":
        sigma_raw = _raw_sigma(baseline_prior)
        sigma = max(sigma_raw, bist_tick_size(c) / c)
    else:
        sigma_raw = _raw_sigma(baseline_prior)
        sigma = _robust_sigma(baseline_prior)
    metrics["sigma_raw"] = round(sigma_raw, 6)
    metrics["sigma_effective"] = round(sigma, 6)
    zs = []
    for minutes in config.return_windows_minutes:
        k = minutes // config.interval_minutes
        key = f"return_{minutes}m_pct"
        if i - k < 0:
            metrics[key] = None
            continue
        metrics[key] = round((c / close[i - k] - 1) * 100, 3)
        zs.append(math.log(c / close[i - k]) / (sigma * math.sqrt(k)))
    price_z = max(zs) if zs and baseline_ok else None
    metrics["price_z"] = round(price_z, 3) if price_z is not None else None
    price_impulse = _clip(price_z / config.price_z_full) if price_z is not None else None

    # --- hacim anomalisi (aynı saat dilimi tabanı; yetmezse kayan taban) ---
    w = min(config.volume_window_bars, len(session_df))
    recent = session_df.iloc[-w:]
    recent_volume = float(recent["Volume"].sum())
    slots = [ts.time() for ts in recent.index]
    effective_mode = config.relvol_mode == "EFFECTIVE"
    same_time = []
    for _, day in baseline_prior.groupby(baseline_prior.index.date):
        by_time = {ts.time(): v for ts, v in zip(day.index, day["Volume"])}
        if all(s in by_time for s in slots):
            total = sum(by_time[s] for s in slots)
            if not effective_mode or total > 0:  # efektif modda sıfır hacimli taban örnekleri dışlanır
                same_time.append(total)
    if len(same_time) >= config.min_prior_sessions:
        baseline, metrics["volume_baseline"] = float(np.median(same_time)), "SAME_TIME_OF_DAY"
    else:
        rolling = baseline_prior["Volume"].rolling(w).sum().dropna()
        if effective_mode:
            rolling = rolling[rolling > 0]
        baseline, metrics["volume_baseline"] = (float(np.median(rolling)) if len(rolling) else 0.0), "ROLLING"
    metrics["volume_baseline_samples"] = len(same_time)
    if recent["Volume"].iloc[-1] <= 0 or baseline <= 0 or not baseline_ok:
        raw_relvol, relative_volume, volume_anomaly = None, None, None  # hacim kanıtı yok (uydurma 0 değil)
    else:
        raw_relvol = recent_volume / baseline
        relative_volume = min(raw_relvol, config.relvol_cap) if config.relvol_cap else raw_relvol
        volume_anomaly = _clip(math.log(relative_volume) / math.log(config.volume_ratio_full)) \
            if relative_volume > 1 else 0.0
    metrics["raw_relative_volume"] = round(raw_relvol, 3) if raw_relvol is not None else None
    metrics["relative_volume"] = round(relative_volume, 3) if relative_volume is not None else None

    # --- kırılım (mevcut bar HARİÇ önceki N bar) ve aralık genişlemesi ---
    tr = _true_range(df).to_numpy()
    if quality_days is not None:  # taban barları: kaliteli seanslar + bugünün önceki barları
        eligible = np.flatnonzero(np.isin(df.index.date, quality_days + [today]))
    else:
        eligible = np.arange(len(df))
    prev_eligible = eligible[(eligible < i) & (eligible >= 1)]
    lookback = df.iloc[max(0, i - config.breakout_lookback_bars):i]
    prior_high = float(lookback["High"].max())
    atr_window = (tr[max(1, i - config.atr_bars):i] if quality_days is None
                  else tr[prev_eligible[-config.atr_bars:]])
    atr_raw = float(np.mean(atr_window)) if len(atr_window) else 0.0
    atr = max(atr_raw, sigma * c) if config.range_floor else atr_raw
    breakout_distance = c / prior_high - 1
    metrics["breakout_distance_pct"] = round(breakout_distance * 100, 3)
    if not baseline_ok:
        breakout = None
    elif c <= prior_high:
        breakout = 0.0
    else:
        breakout = _clip((c - prior_high) / atr) if atr > 0 else 1.0
    metrics["breakout_atr"] = round((c - prior_high) / atr, 3) if atr > 0 else None

    tr_base = (tr[max(1, i - config.range_lookback_bars):i] if quality_days is None
               else tr[prev_eligible[-config.range_lookback_bars:]])
    median_tr = float(np.median(tr_base)) if len(tr_base) else 0.0
    metrics["raw_range_baseline"] = round(median_tr, 6)
    effective_tr = max(median_tr, sigma * c) if config.range_floor else median_tr
    metrics["effective_range_baseline"] = round(effective_tr, 6)
    if not baseline_ok:
        range_ratio, range_expansion = None, None
    elif effective_tr > 0:
        range_ratio = tr[i] / effective_tr
        range_expansion = _clip((range_ratio - 1) / (config.range_ratio_full - 1))
    else:
        range_ratio = None
        range_expansion = 1.0 if tr[i] > 0 else 0.0
    metrics["range_ratio"] = round(range_ratio, 3) if range_ratio is not None else None

    # --- dönüş (önceki seans kapanışlarında düşüş, ardından toparlanma) ---
    session_closes = prior.groupby(prior.index.date)["Close"].last().to_numpy()[-config.reversal_sessions:]
    reversal = None
    if len(session_closes) >= config.min_prior_sessions:
        peak_pos = int(np.argmax(session_closes))
        trough = float(np.min(session_closes[peak_pos:]))
        drawdown = 1 - trough / float(session_closes[peak_pos])
        rebound = c / trough - 1
        metrics["prior_drawdown_pct"] = round(drawdown * 100, 3)
        metrics["rebound_from_low_pct"] = round(rebound * 100, 3)
        reversal = (_clip(drawdown / config.reversal_drawdown_full) * _clip(rebound / config.reversal_rebound_full)
                    if drawdown >= config.reversal_min_drawdown and rebound > 0 else 0.0)

    # --- VWAP (seans) ---
    vol = session_df["Volume"].to_numpy()
    vwap_comp = None
    if vol.sum() > 0:
        typical = ((session_df["High"] + session_df["Low"] + session_df["Close"]) / 3).to_numpy()
        cum_vwap = np.cumsum(typical * vol) / np.where(np.cumsum(vol) > 0, np.cumsum(vol), np.nan)
        vwap = float(cum_vwap[-1])
        distance = c / vwap - 1
        metrics["distance_from_vwap_pct"] = round(distance * 100, 3)
        below_before = bool(np.any(session_df["Close"].to_numpy()[:-1] < cum_vwap[:-1]))
        metrics["vwap_reclaim"] = bool(distance > 0 and below_before)
        vwap_comp = _clip(distance / VWAP_DISTANCE_FULL) if distance > 0 else 0.0
    else:
        metrics["distance_from_vwap_pct"] = None
        metrics["vwap_reclaim"] = None

    # --- katalizör bağlamı (yalnız değerlendirme anında yayınlanmış VE mevcut olanlar) ---
    catalyst = None
    if events is not None:
        window_start = evaluated_at - timedelta(hours=config.catalyst_max_age_hours)
        visible = [e for e in events if e.published_at <= evaluated_at and e.available_at <= evaluated_at
                   and e.published_at >= window_start and e.sentiment > 0]
        catalyst = max((_clip(e.sentiment / 100 * e.confidence * (e.reliability if e.reliability is not None else 1.0))
                        for e in visible), default=0.0)
        metrics["catalyst_events"] = len(visible)

    components = {"price_impulse": price_impulse, "volume_anomaly": volume_anomaly, "breakout": breakout,
                  "range_expansion": range_expansion, "reversal": reversal, "vwap": vwap_comp,
                  "event_catalyst": catalyst}
    # Tek bar sıçraması: hareket ardışık iki 15 dk penceresinde de sürmeli.
    k3 = config.volume_window_bars
    persistent = i - k3 - 1 >= 0 and close[i] > close[i - k3] and close[i - 1] > close[i - 1 - k3]
    # Birimden bağımsız (pandas zaman çözünürlüğü ns olmayabilir)
    gaps = pd.Series(session_df.index).diff().dt.total_seconds().to_numpy()[1:]
    data_gap = bool(np.any(gaps > config.max_session_gap_intervals * interval.total_seconds()))
    metrics.update(persistent_move=persistent, data_gap=data_gap)
    return FeatureSnapshot(ma.STATUS_OK, None, base, components, metrics, persistent, data_gap)


_LEVEL_RANK = {ma.LEVEL_NONE: 0, ma.LEVEL_WATCH: 1, ma.LEVEL_STRONG: 2}


def classify_raw(snapshot: FeatureSnapshot, config: ma.MomentumAlertConfig = DEFAULT_CONFIG
                 ) -> tuple[str, float | None, list[str]]:
    """(tek değerlendirme düzeyi, skor, kanıtlar). Eşik/kural yalnız burada uygulanır."""
    if snapshot.status != ma.STATUS_OK:
        return ma.LEVEL_NONE, None, []
    comps = snapshot.components
    thr = config.evidence_threshold
    price_impulse = comps["price_impulse"]
    price_ok = price_impulse is not None and price_impulse >= thr
    weights = config.weights
    # Katalizör gösterilir ama piyasa (fiyat) kanıtı olmadan skora katılmaz: haber tek başına alarm üretemez.
    scored = {k: v for k, v in comps.items() if not (k == "event_catalyst" and not price_ok)}
    score = 100 * sum(weights[k] * (v or 0.0) for k, v in scored.items()) / sum(weights.values())
    evidence = [k for k in ("price_impulse", "volume_anomaly", "breakout", "range_expansion", "reversal")
                if comps[k] is not None and comps[k] >= thr]
    if config.min_session_return_pct is not None and \
            snapshot.metrics["session_return_pct"] < config.min_session_return_pct:
        return ma.LEVEL_NONE, score, evidence

    level = ma.LEVEL_NONE
    if config.rule_mode == "GROUPS":
        participation = "volume_anomaly" in evidence
        structure = any(comps[k] is not None and comps[k] >= thr for k in ("breakout", "range_expansion", "vwap"))
        if price_ok and (participation or structure) and score >= config.watch_score:
            level = ma.LEVEL_WATCH
            if (price_impulse >= config.strong_price_impulse and participation and structure
                    and score >= config.strong_score and snapshot.persistent and not snapshot.data_gap):
                level = ma.LEVEL_STRONG
    elif price_ok and len(evidence) >= 2 and score >= config.watch_score:
        level = ma.LEVEL_WATCH
        if (price_impulse >= config.strong_price_impulse and "volume_anomaly" in evidence
                and ("breakout" in evidence or "range_expansion" in evidence)
                and len(evidence) >= config.strong_min_evidence and score >= config.strong_score
                and snapshot.persistent and not snapshot.data_gap):
            level = ma.LEVEL_STRONG
    return level, score, evidence


def confirm_level(raw_levels: list[str], config: ma.MomentumAlertConfig = DEFAULT_CONFIG) -> str:
    """`raw_levels`: eskiden yeniye, son eleman şimdiki değerlendirme. Son `confirm_n` değerlendirmenin en az
    `confirm_k`'si düzeye ulaşmalı VE şimdiki değerlendirme de o düzeyde olmalı (sönmüş harekete alarm yok)."""
    window = raw_levels[-config.confirm_n:]
    current = _LEVEL_RANK[raw_levels[-1]]
    for level in (ma.LEVEL_STRONG, ma.LEVEL_WATCH):
        rank = _LEVEL_RANK[level]
        if current >= rank and sum(_LEVEL_RANK[x] >= rank for x in window) >= config.confirm_k:
            return level
    return ma.LEVEL_NONE


def evaluate(asset: str, bars: pd.DataFrame, provenance: dict, evaluated_at: datetime,
             config: ma.MomentumAlertConfig = DEFAULT_CONFIG,
             events: list[CatalystEvent] | None = None) -> ma.MomentumAlert:
    snapshot = compute_features(asset, bars, provenance, evaluated_at, config, events)
    base = {"asset": asset.upper(), "evaluated_at": evaluated_at, "interval": f"{config.interval_minutes}m",
            "source": provenance.get("source"), "identity_check": provenance.get("identity_check"), **snapshot.base}
    if snapshot.status != ma.STATUS_OK:
        return ma.MomentumAlert(status=snapshot.status, reason=snapshot.reason, **base)
    level, score, evidence = classify_raw(snapshot, config)
    raw_now = level
    if config.confirm_n > 1:  # önceki değerlendirme anları aynı veriyle (gelecek barı görmeden) yeniden hesaplanır
        interval = timedelta(minutes=config.interval_minutes)
        history = [classify_raw(compute_features(asset, bars, provenance, evaluated_at - interval * j, config,
                                                 events), config)[0] for j in range(config.confirm_n - 1, 0, -1)]
        level = confirm_level(history + [raw_now], config)

    comps, metrics = snapshot.components, snapshot.metrics
    thr = config.evidence_threshold
    price_ok = comps["price_impulse"] is not None and comps["price_impulse"] >= thr
    labels = {"price_impulse": f"Hızlanan fiyat hareketi ({metrics['price_z']}σ)",
              "volume_anomaly": f"Hacim anomalisi ({metrics['relative_volume']}x)",
              "breakout": f"Kırılım tespit edildi (önceki {config.breakout_lookback_bars} barın tepesi aşıldı)",
              "range_expansion": f"Aralık genişlemesi ({metrics['range_ratio']}x)",
              "reversal": "Önceki düşüşten güçlü dönüş"}
    reasons = [labels[k] for k in evidence]
    if metrics.get("vwap_reclaim"):
        reasons.append("Fiyat VWAP üstüne geri geçti")
    if comps["event_catalyst"]:
        reasons.append("Yakın tarihli olumlu olay bağlamı (yalnız bağlam)" if price_ok
                       else "Olumlu olay var ama fiyat kanıtı yok: alarm üretmez")
    if raw_now == ma.LEVEL_WATCH and price_ok and not snapshot.persistent:
        reasons.append("Hareket tek bar sıçraması olabilir: güçlü düzeye çıkarılmadı")
    if snapshot.data_gap:
        reasons.append("Seans içinde veri boşluğu var: güçlü düzeye çıkarılmadı")
    if _LEVEL_RANK[level] < _LEVEL_RANK[raw_now]:
        reasons.append("Hareket henüz ardışık değerlendirmelerde doğrulanmadı")

    return ma.MomentumAlert(status=ma.STATUS_OK, detected=level != ma.LEVEL_NONE, level=level,
                            momentum_score=round(score, 2),
                            components={k: (round(v, 4) if v is not None else None) for k, v in comps.items()},
                            metrics=metrics, reasons=reasons, **base)
