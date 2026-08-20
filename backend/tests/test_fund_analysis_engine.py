from datetime import datetime, timedelta, timezone

import pytest

from app.engines.funds.analysis_engine import (
    MIN_INVESTOR_COUNT,
    MIN_PORTFOLIO_SIZE_TL,
    FundAnalysisEngine,
)


class _FakeSnapshotRepo:
    def __init__(self, snapshots: dict[str, list[dict]]):
        self._snapshots = snapshots

    def get_or_fetch(self, date, provider, kind="YAT"):
        return self._snapshots.get(date, [])


def _fund(code, price, name="TEST FONU", portfolio_size=10_000_000.0, investor_count=100):
    return {
        "fund_code": code,
        "fund_name": name,
        "price": price,
        "portfolio_size": portfolio_size,
        "investor_count": investor_count,
    }


def _date_str(offset_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).strftime("%Y-%m-%d")


def test_computes_returns_and_composite_score_when_all_horizons_present():
    snapshots = {
        _date_str(0): [_fund("AAA", price=110.0)],
        _date_str(30): [_fund("AAA", price=100.0)],
        _date_str(91): [_fund("AAA", price=90.0)],
        _date_str(182): [_fund("AAA", price=80.0)],
        _date_str(365): [_fund("AAA", price=50.0)],
    }
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo(snapshots))

    results = engine.analyze_all()

    assert len(results) == 1
    fund = results[0]
    assert fund.fund_code == "AAA"
    assert fund.return_1m_pct == pytest.approx(10.0)
    assert fund.return_3m_pct == pytest.approx(22.22, abs=0.01)
    assert fund.return_6m_pct == pytest.approx(37.5, abs=0.01)
    assert fund.return_1y_pct == pytest.approx(120.0, abs=0.01)
    assert fund.composite_score > 0


def test_renormalizes_when_a_horizon_is_missing_new_fund():
    snapshots = {
        _date_str(0): [_fund("NEW", price=105.0)],
        _date_str(30): [_fund("NEW", price=100.0)],
        # 3ay/6ay/1yıl için hiç veri yok — yeni kurulmuş fon
    }
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo(snapshots))

    results = engine.analyze_all()

    assert len(results) == 1
    fund = results[0]
    assert fund.return_1m_pct == pytest.approx(5.0)
    assert fund.return_3m_pct is None
    assert fund.return_6m_pct is None
    assert fund.return_1y_pct is None
    # Yalnızca 1 aylık ufuk mevcut olduğundan composite_score tam olarak ona eşit olmalı
    assert fund.composite_score == pytest.approx(5.0)


def test_excludes_funds_below_minimum_size_or_investor_thresholds():
    snapshots = {
        _date_str(0): [
            _fund("SMALL", price=100.0, portfolio_size=MIN_PORTFOLIO_SIZE_TL - 1),
            _fund("FEWINV", price=100.0, investor_count=MIN_INVESTOR_COUNT - 1),
            _fund("OK", price=100.0),
        ],
        _date_str(30): [
            _fund("SMALL", price=90.0, portfolio_size=MIN_PORTFOLIO_SIZE_TL - 1),
            _fund("FEWINV", price=90.0, investor_count=MIN_INVESTOR_COUNT - 1),
            _fund("OK", price=90.0),
        ],
    }
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo(snapshots))

    results = engine.analyze_all()

    assert [f.fund_code for f in results] == ["OK"]


def test_falls_back_to_nearby_date_when_exact_date_missing_weekend():
    # "Bugün" pazar (veri yok), en son işlem günü 2 gün önce
    snapshots = {
        _date_str(2): [_fund("AAA", price=100.0)],
        _date_str(32): [_fund("AAA", price=95.0)],
    }
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo(snapshots))

    results = engine.analyze_all()

    assert len(results) == 1
    assert results[0].as_of_date == _date_str(2)


def test_sorts_by_composite_score_descending():
    snapshots = {
        _date_str(0): [_fund("WINNER", price=150.0), _fund("LOSER", price=90.0)],
        _date_str(30): [_fund("WINNER", price=100.0), _fund("LOSER", price=100.0)],
    }
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo(snapshots))

    results = engine.analyze_all()

    assert [f.fund_code for f in results] == ["WINNER", "LOSER"]


def test_raises_when_no_recent_data_at_all():
    engine = FundAnalysisEngine(provider=object(), snapshot_repo=_FakeSnapshotRepo({}))

    with pytest.raises(ValueError):
        engine.analyze_all()
