"""EarlyMomentumAlertEngine — sentetik senaryolar (A–M), saflık, seans ve sızıntı testleri. Ağ/Firestore yok."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import momentum_alert as ma
from app.services.market_data.trading_calendar import expected_trading_sessions
from app.services.momentum.early_momentum_engine import DEFAULT_CONFIG, CatalystEvent, evaluate

DAY = date(2026, 10, 7)  # Çarşamba, işlem günü
PRIOR = [d for d in expected_trading_sessions(date(2026, 9, 21), date(2026, 10, 6))][-7:]
PROV = {"identity_check": "MATCH", "source": "fake", "exchange": "IST", "currency": "TRY"}
DELAY = timedelta(minutes=DEFAULT_CONFIG.provider_delay_minutes)
STEP = timedelta(minutes=5)


def session(day, start_price, returns, volumes=None, seed=0):
    """`returns` her bar için kapanış getirisi; açılış önceki kapanış. 10:00'dan başlayan 5 dk barlar."""
    rng = np.random.RandomState(seed)
    rows, idx, price = [], [], start_price
    t = datetime.combine(day, time(10, 0), tzinfo=ISTANBUL_TZ)
    for j, r in enumerate(returns):
        o = price
        c = o * (1 + r)
        wiggle = abs(rng.normal(0, 0.0005))
        rows.append({"Open": o, "High": max(o, c) * (1 + wiggle), "Low": min(o, c) * (1 - wiggle), "Close": c,
                     "Volume": (volumes[j] if volumes is not None else 1000.0)})
        idx.append(t)
        t += STEP
        price = c
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def noise(n, seed, scale=0.001):
    return list(np.random.RandomState(seed).normal(0, scale, n))


def history(prior_daily_drift=0.0, prior_sessions=PRIOR, price=100.0):
    frames = []
    for k, d in enumerate(prior_sessions):
        rets = [r + prior_daily_drift / 96 for r in noise(96, seed=k)]
        frame = session(d, price, rets, seed=k)
        frames.append(frame)
        price = float(frame["Close"].iloc[-1])
    return frames, price


def build(today_returns, today_volumes=None, prior_daily_drift=0.0, prior_sessions=PRIOR):
    frames, price = history(prior_daily_drift, prior_sessions)
    today = session(DAY, price, today_returns, today_volumes, seed=99)
    return pd.concat(frames + [today])


def eval_at_end(bars, events=None, provenance=PROV, extra=timedelta(0), config=DEFAULT_CONFIG):
    last_start = bars[bars.index.date == DAY].index[-1]
    t = last_start.to_pydatetime() + STEP + DELAY + extra
    return evaluate("TEST", bars, provenance, t, config, events), t


FLAT = noise(40, seed=50)


# --- A–M ---------------------------------------------------------------------------------------------------------

def test_A_flat_market_none():
    r, _ = eval_at_end(build(FLAT))
    assert r.status == ma.STATUS_OK and r.level == ma.LEVEL_NONE and not r.detected


def test_B_price_spike_normal_volume_not_strong():
    r, _ = eval_at_end(build(FLAT + [0.015, 0.015, 0.015]))
    assert r.status == ma.STATUS_OK and r.level in (ma.LEVEL_NONE, ma.LEVEL_WATCH)
    assert r.components["price_impulse"] == 1.0


def test_C_volume_spike_flat_price_not_strong():
    r, _ = eval_at_end(build(FLAT + [0.0002, -0.0002, 0.0001], [1000.0] * 40 + [9000.0] * 3))
    assert r.level == ma.LEVEL_NONE and r.components["volume_anomaly"] >= 0.5


def test_D_price_volume_breakout_strong():
    r, _ = eval_at_end(build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4))
    assert r.level == ma.LEVEL_STRONG and r.detected
    assert r.components["breakout"] > 0 and r.components["volume_anomaly"] >= 0.5
    assert r.metrics["return_15m_pct"] > 2 and r.momentum_score >= DEFAULT_CONFIG.strong_score
    assert any("Kırılım" in reason for reason in r.reasons)


def test_E_reversal_with_price_and_volume_alerts():
    r, _ = eval_at_end(build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [6000.0] * 4,
                             prior_daily_drift=-0.05))
    assert r.detected and r.components["reversal"] > 0
    assert r.metrics["prior_drawdown_pct"] >= 15


def test_F_stale_data():
    r, _ = eval_at_end(build(FLAT), extra=timedelta(minutes=40))
    assert r.status == ma.STATUS_STALE_DATA and r.level is None and r.momentum_score is None


def test_G_insufficient_prior_sessions():
    r, _ = eval_at_end(build(FLAT + [0.02] * 4, [1000.0] * 40 + [9000.0] * 4, prior_sessions=PRIOR[-2:]))
    assert r.status == ma.STATUS_INSUFFICIENT_DATA and r.level is None and r.momentum_score is None


@pytest.mark.parametrize("identity", ["UNVERIFIED", None])
def test_H_identity_unverified_fails_closed(identity):
    bars = build(FLAT + [0.01] * 4, [1000.0] * 40 + [8000.0] * 4)
    r, _ = eval_at_end(bars, provenance={**PROV, "identity_check": identity})
    assert r.status == ma.STATUS_IDENTITY_UNVERIFIED and r.momentum_score is None and not r.detected


def event(published_at, sentiment=90.0, available_at=None):
    return CatalystEvent(published_at=published_at, available_at=available_at or published_at,
                         sentiment=sentiment, confidence=0.9, reliability=0.9)


def test_I_strong_news_without_price_move_no_alert():
    bars = build(FLAT)
    _, t = eval_at_end(bars)
    r, _ = eval_at_end(bars, events=[event(t - timedelta(hours=2))])
    assert r.level == ma.LEVEL_NONE and r.components["event_catalyst"] > 0
    base, _ = eval_at_end(bars, events=[])
    assert r.momentum_score == base.momentum_score  # piyasa kanıtı yokken katalizör skora katılmaz


def test_J_catalyst_amplifies_only_with_market_evidence():
    bars = build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4)
    _, t = eval_at_end(bars)
    with_news, _ = eval_at_end(bars, events=[event(t - timedelta(hours=3))])
    without, _ = eval_at_end(bars, events=[])
    assert with_news.momentum_score > without.momentum_score and with_news.detected
    assert without.components["event_catalyst"] == 0.0
    unknown, _ = eval_at_end(bars, events=None)
    assert unknown.components["event_catalyst"] is None  # bilinmiyor ≠ yok


def test_K_single_bar_spike_not_strong():
    r, _ = eval_at_end(build(FLAT + [0.03, 0.0, 0.0], [1000.0] * 40 + [8000.0, 1000.0, 1000.0]))
    assert r.level != ma.LEVEL_STRONG


def test_K_data_gap_not_strong():
    bars = build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4)
    today = bars[bars.index.date == DAY]
    gapped = bars.drop(today.index[30:38])  # seans içinde 40 dk veri yok
    r, _ = eval_at_end(gapped)
    assert r.metrics["data_gap"] is True and r.level != ma.LEVEL_STRONG


def test_K_invalid_bar_is_ignored_not_alerting():
    bars = build(FLAT)
    bad = bars.copy()
    last = bad[bad.index.date == DAY].index[-2]
    bad.loc[last, "Close"] = bad.loc[last, "High"] * 1.5  # kapanış en yüksekten büyük: geçersiz bar
    r, _ = eval_at_end(bad)
    assert r.status == ma.STATUS_OK and r.level == ma.LEVEL_NONE


def test_L_future_bars_do_not_change_result():
    bars = build(FLAT + [0.002] * 3)
    r, t = eval_at_end(bars)
    last = bars.index[-1]
    future = pd.DataFrame([{"Open": 100, "High": 200, "Low": 100, "Close": 190, "Volume": 1e7}] * 6,
                          index=pd.DatetimeIndex([last + STEP * (k + 1) for k in range(6)]))
    r2 = evaluate("TEST", pd.concat([bars, future]), PROV, t, DEFAULT_CONFIG, None)
    assert r.model_dump() == r2.model_dump()


def test_L_in_progress_provider_bar_is_excluded():
    """Gecikme penceresi içindeki (sağlayıcıda hâlâ oluşan) bar kullanılmaz."""
    bars = build(FLAT)
    _, t = eval_at_end(bars)
    partial = pd.DataFrame([{"Open": 100, "High": 150, "Low": 100, "Close": 150, "Volume": 1e7}],
                           index=pd.DatetimeIndex([bars.index[-1] + STEP]))
    assert evaluate("TEST", pd.concat([bars, partial]), PROV, t, DEFAULT_CONFIG, None).level == ma.LEVEL_NONE


def test_M_future_news_not_used():
    bars = build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4)
    _, t = eval_at_end(bars)
    published_later = event(t + timedelta(minutes=1))
    analysed_later = event(t - timedelta(hours=1), available_at=t + timedelta(minutes=5))
    r = evaluate("TEST", bars, PROV, t, DEFAULT_CONFIG, [published_later, analysed_later])
    assert r.components["event_catalyst"] == 0.0 and r.metrics["catalyst_events"] == 0


# --- saflık, seans, sözleşme ------------------------------------------------------------------------------------

def test_pure_same_input_same_output():
    bars = build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4)
    _, t = eval_at_end(bars)
    a = evaluate("TEST", bars, PROV, t, DEFAULT_CONFIG, [event(t - timedelta(hours=1))])
    b = evaluate("TEST", bars.copy(), dict(PROV), t, DEFAULT_CONFIG, [event(t - timedelta(hours=1))])
    assert a.model_dump() == b.model_dump()


@pytest.mark.parametrize("when", [
    datetime(2026, 10, 10, 12, 0, tzinfo=ISTANBUL_TZ),  # Cumartesi
    datetime(2026, 10, 29, 12, 0, tzinfo=ISTANBUL_TZ),  # Cumhuriyet Bayramı (tam kapanış)
    datetime(2026, 10, 28, 14, 0, tzinfo=ISTANBUL_TZ),  # arefe (yarım gün) öğleden sonra
    datetime(2026, 10, 7, 9, 30, tzinfo=ISTANBUL_TZ),  # açılış öncesi
    datetime(2026, 10, 7, 18, 30, tzinfo=ISTANBUL_TZ),  # kapanış + gecikme sonrası
])
def test_market_closed_never_alerts(when):
    r = evaluate("TEST", build(FLAT + [0.02] * 4, [1000.0] * 40 + [9000.0] * 4), PROV, when, DEFAULT_CONFIG, None)
    assert r.status == ma.STATUS_MARKET_CLOSED and not r.detected and r.momentum_score is None


def test_unsupported_calendar_year_is_error():
    r = evaluate("TEST", build(FLAT), PROV, datetime(2027, 3, 3, 12, 0, tzinfo=ISTANBUL_TZ), DEFAULT_CONFIG, None)
    assert r.status == ma.STATUS_ERROR and r.reason == "CALENDAR_UNSUPPORTED"


def test_contract_terms_and_disclaimer():
    r, _ = eval_at_end(build(FLAT + [0.01, 0.01, 0.01, 0.012], [1000.0] * 40 + [8000.0] * 4))
    dumped = r.model_dump_json()
    for forbidden in ('"BUY"', '"SELL"', '"HOLD"', "STRONG_BUY", "KESİN"):
        assert forbidden not in dumped
    assert r.disclaimer == ma.DISCLAIMER and set(r.components) == set(ma.COMPONENTS)
    assert sum(DEFAULT_CONFIG.weights.values()) == pytest.approx(1.0)


def test_limit_locked_prior_days_do_not_divide_by_zero():
    """Tavan/taban kilitli (O=H=L=C) önceki günler: oynaklık/aralık tabanı 0 olsa da çökmez."""
    frames, price = [], 100.0
    for d in PRIOR:
        price *= 0.9
        idx = pd.DatetimeIndex([datetime.combine(d, time(10, 0), tzinfo=ISTANBUL_TZ) + STEP * k for k in range(96)])
        frames.append(pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price, "Volume": 500.0},
                                   index=idx))
    today = session(DAY, price, FLAT + [0.02, 0.02, 0.02, 0.02], [500.0] * 40 + [20000.0] * 4)
    r, _ = eval_at_end(pd.concat(frames + [today]))
    assert r.status == ma.STATUS_OK and r.detected and r.components["reversal"] > 0
