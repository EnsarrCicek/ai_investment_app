from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.engines.journal.outcome_evaluator import dominant_factor, evaluate_decision
from app.models.ai_decision import AIDecision

_NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _decision(decision="BUY", created_days_ago=40, technical_score=50.0, news_score=None, macro_score=None,
              technical_weight=0.5, news_weight=0.3, macro_weight=0.2):
    return AIDecision(
        asset="THYAO",
        created_at=_NOW.replace(day=_NOW.day) - pd.Timedelta(days=created_days_ago),
        technical_score=technical_score,
        news_score=news_score,
        macro_score=macro_score,
        technical_weight=technical_weight,
        news_weight=news_weight,
        macro_weight=macro_weight,
        final_score=45.0,
        decision=decision,
        confidence=70.0,
        decision_engine_version="1.0.0",
    )


def _close_series(prices: dict[str, float]) -> pd.Series:
    return pd.Series({date.fromisoformat(d): v for d, v in prices.items()})


def test_buy_decision_correct_when_price_rose():
    decision = _decision(decision="BUY", created_days_ago=40)
    history = _close_series({
        (_NOW - pd.Timedelta(days=40)).date().isoformat(): 100.0,
        (_NOW - pd.Timedelta(days=33)).date().isoformat(): 110.0,  # +7 gün ufku
        (_NOW - pd.Timedelta(days=10)).date().isoformat(): 130.0,  # +30 gün ufku
    })

    outcomes = evaluate_decision(decision, history, now=_NOW)

    assert outcomes[7]["status"] == "DOGRU"
    assert outcomes[7]["realized_return_pct"] == pytest.approx(10.0)
    assert outcomes[30]["status"] == "DOGRU"
    assert outcomes[30]["realized_return_pct"] == pytest.approx(30.0)


def test_sell_decision_wrong_when_price_rose():
    decision = _decision(decision="SELL", created_days_ago=40)
    history = _close_series({
        (_NOW - pd.Timedelta(days=40)).date().isoformat(): 100.0,
        (_NOW - pd.Timedelta(days=33)).date().isoformat(): 110.0,
    })

    outcomes = evaluate_decision(decision, history, horizons_days=[7], now=_NOW)

    assert outcomes[7]["status"] == "YANLIS"


def test_pending_when_horizon_has_not_passed_yet():
    decision = _decision(decision="BUY", created_days_ago=3)
    history = _close_series({(_NOW - pd.Timedelta(days=3)).date().isoformat(): 100.0})

    outcomes = evaluate_decision(decision, history, horizons_days=[7, 30], now=_NOW)

    assert outcomes[7]["status"] == "BEKLEMEDE"
    assert outcomes[30]["status"] == "BEKLEMEDE"


def test_hold_decision_is_neutral_not_scored():
    decision = _decision(decision="HOLD", created_days_ago=40)
    history = _close_series({
        (_NOW - pd.Timedelta(days=40)).date().isoformat(): 100.0,
        (_NOW - pd.Timedelta(days=33)).date().isoformat(): 90.0,
    })

    outcomes = evaluate_decision(decision, history, horizons_days=[7], now=_NOW)

    assert outcomes[7]["status"] == "NOTR"
    assert "realized_return_pct" in outcomes[7]


def test_missing_price_data_reported_as_veri_yok():
    decision = _decision(decision="BUY", created_days_ago=40)
    history = _close_series({})

    outcomes = evaluate_decision(decision, history, horizons_days=[7], now=_NOW)

    assert outcomes[7]["status"] == "VERI_YOK"


def test_dominant_factor_picks_highest_weighted_contribution():
    decision = _decision(technical_score=10.0, news_score=80.0, macro_score=5.0,
                          technical_weight=0.5, news_weight=0.3, macro_weight=0.2)

    assert dominant_factor(decision) == "news"


def test_dominant_factor_none_when_no_scores_available():
    decision = _decision(technical_score=None, news_score=None, macro_score=None)

    assert dominant_factor(decision) is None
