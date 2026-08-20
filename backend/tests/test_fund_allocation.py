from datetime import datetime, timezone

import pytest

from app.models.fund_analysis import FundAnalysis
from app.services.funds.allocation import recommend_allocation


def _fund(code, score):
    return FundAnalysis(
        fund_code=code,
        fund_name=f"{code} FONU",
        price=100.0,
        portfolio_size=10_000_000.0,
        investor_count=100,
        composite_score=score,
        as_of_date="2026-08-20",
        generated_at=datetime.now(timezone.utc),
    )


def test_splits_budget_across_top_n_proportional_to_score():
    funds = [_fund("A", 30.0), _fund("B", 20.0), _fund("C", 10.0), _fund("D", 5.0)]

    allocation = recommend_allocation(funds, budget_tl=1000.0, top_n=3)

    assert [a["fund_code"] for a in allocation] == ["A", "B", "C"]
    assert sum(a["amount_tl"] for a in allocation) == pytest.approx(1000.0, abs=0.05)
    # daha yüksek skorlu fon daha büyük pay almalı
    assert allocation[0]["amount_tl"] > allocation[1]["amount_tl"] > allocation[2]["amount_tl"]


def test_handles_negative_scores_without_negative_amounts():
    funds = [_fund("A", -2.0), _fund("B", -10.0)]

    allocation = recommend_allocation(funds, budget_tl=500.0, top_n=2)

    assert all(a["amount_tl"] > 0 for a in allocation)
    assert sum(a["amount_tl"] for a in allocation) == pytest.approx(500.0, abs=0.05)
    assert allocation[0]["amount_tl"] > allocation[1]["amount_tl"]


def test_returns_empty_list_for_non_positive_budget():
    funds = [_fund("A", 10.0)]
    assert recommend_allocation(funds, budget_tl=0.0) == []
    assert recommend_allocation(funds, budget_tl=-100.0) == []


def test_returns_empty_list_when_no_funds():
    assert recommend_allocation([], budget_tl=1000.0) == []
