import pandas as pd
import pytest

from app.engines.risk.engine import RiskEngine


def test_portfolio_concentration_single_asset_is_max():
    result = RiskEngine().portfolio_concentration({"THYAO": 1000.0})
    assert result["herfindahl_index"] == 1.0
    assert result["weights_pct"] == {"THYAO": 100.0}


def test_portfolio_concentration_equal_split_is_diversified():
    result = RiskEngine().portfolio_concentration({"A": 500.0, "B": 500.0})
    assert result["herfindahl_index"] == pytest.approx(0.5, rel=1e-3)
    assert result["weights_pct"]["A"] == 50.0
    assert result["weights_pct"]["B"] == 50.0


def test_portfolio_concentration_empty_portfolio_is_zero():
    result = RiskEngine().portfolio_concentration({})
    assert result["herfindahl_index"] == 0.0
    assert result["weights_pct"] == {}


def test_asset_risk_uses_injected_provider(fake_provider):
    closes = [100, 102, 101, 105, 103, 108, 107, 110, 106, 112] * 3
    provider = fake_provider(history_df=pd.DataFrame({"Close": closes}))

    result = RiskEngine(provider=provider).asset_risk("TEST")

    assert result["asset"] == "TEST"
    assert isinstance(result["volatility_annualized_pct"], float)
    assert result["max_drawdown_pct"] <= 0
