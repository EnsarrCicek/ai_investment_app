"""MARKET-RISK-1 erken risk modeli — zaman sızıntısı ve veri sözleşmesi testleri (ağ yok)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.research.market_risk_shadow.early_risk_model import compute_features, target_window_end
from app.services.market_data.trading_calendar import expected_trading_sessions

CAL = expected_trading_sessions(date(2024, 6, 3), date(2025, 2, 28))


def _series(values, sessions):
    return pd.Series(list(values), index=list(sessions))


def test_future_prices_do_not_change_features_at_t():
    t = date(2024, 11, 29)
    sessions = CAL
    base = [100.0 + i * 0.3 + (i % 7) for i in range(len(sessions))]
    asset, index = _series(base, sessions), _series([1000.0 + i for i in range(len(sessions))], sessions)
    before, _ = compute_features(asset, index, t)
    future = asset.copy()
    future[[d for d in sessions if d > t]] = 1.0
    after, _ = compute_features(future, index, t)
    assert before == after and before is not None


def test_training_targets_never_reach_the_evaluation_period():
    eval_start = date(2025, 1, 2)
    late = [d for d in CAL if d.year == 2024][-10:]
    assert all(target_window_end(t, CAL) >= eval_start for t in late)
    ok = [d for d in CAL if d.year == 2024][-11]
    assert target_window_end(ok, CAL) < eval_start


def test_missing_session_in_window_is_not_valid_input():
    t = date(2024, 11, 29)
    asset = _series([100.0] * len(CAL), CAL).drop(date(2024, 11, 20))
    features, why = compute_features(asset, _series([1000.0] * len(CAL), CAL), t)
    assert features is None and why == "ASSET_MISSING_EXPECTED_SESSIONS"
    index = _series([1000.0] * len(CAL), CAL).drop(t)
    features, why = compute_features(_series([100.0] * len(CAL), CAL), index, t)
    assert features is None and why.startswith("INDEX_")


def test_scaler_is_learned_only_from_training_rows():
    pytest.importorskip("sklearn")
    from app.research.market_risk_shadow.early_risk_model import fit_model

    rng = np.random.default_rng(0)
    train_x, train_y = rng.normal(0, 1, (200, 6)), np.array([0, 1] * 100)
    model, _ = fit_model(train_x, train_y)
    eval_x = rng.normal(5, 3, (50, 6))
    model.predict_proba(eval_x)
    assert np.allclose(model.named_steps["scaler"].mean_, train_x.mean(axis=0))
    assert np.allclose(model.named_steps["scaler"].scale_, train_x.std(axis=0))
