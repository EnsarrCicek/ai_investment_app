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


def test_asset_liquidity_days_to_liquidate(fake_provider):
    provider = fake_provider(history_df=pd.DataFrame({"Volume": [1000.0] * 10}))
    result = RiskEngine(provider=provider).asset_liquidity("TEST", quantity=2000.0)
    assert result["avg_daily_volume"] == 1000.0
    assert result["days_to_liquidate"] == 2.0


def test_asset_liquidity_raises_when_no_volume(fake_provider):
    provider = fake_provider(history_df=pd.DataFrame({"Volume": []}))
    with pytest.raises(ValueError):
        RiskEngine(provider=provider).asset_liquidity("TEST", quantity=100.0)


def test_gap_risk_detects_overnight_jump(fake_provider):
    df = pd.DataFrame({"Open": [100.0, 105.0, 106.0], "Close": [100.0, 104.0, 106.5]})
    # gap[1] = (105-100)/100*100 = %5; gap[2] = (106-104)/104*100 ≈ %1.92
    provider = fake_provider(history_df=df)
    result = RiskEngine(provider=provider).gap_risk("TEST")
    assert result["max_gap_pct"] == pytest.approx(5.0, rel=1e-3)


class _MultiSymbolProvider:
    """market_risk/portfolio_correlation gibi birden fazla sembol isteyen
    metotlar için sembole göre farklı geçmiş veri döndüren sahte provider."""

    def __init__(self, history_by_symbol: dict[str, pd.DataFrame]):
        self._history_by_symbol = history_by_symbol

    def get_history(self, symbol: str, period: str = "6mo"):
        return self._history_by_symbol[symbol]

    def get_latest(self, symbol: str):
        raise NotImplementedError


def test_market_risk_beta_one_when_asset_tracks_benchmark_perfectly():
    closes = [100, 102, 101, 105, 103, 108, 107, 110, 106, 112] * 3
    df = pd.DataFrame({"Close": closes})
    provider = _MultiSymbolProvider({"TEST": df, "XU100": df})

    result = RiskEngine(provider=provider).market_risk("TEST", benchmark="XU100")

    assert result["beta"] == pytest.approx(1.0, rel=1e-6)
    assert result["correlation_with_market"] == pytest.approx(1.0, rel=1e-6)


def test_market_risk_negative_when_inversely_related():
    up = [100.0, 105.0, 103.0, 110.0, 108.0, 115.0]
    down = [100.0, 95.0, 97.0, 90.0, 92.0, 85.0]
    provider = _MultiSymbolProvider(
        {"TEST": pd.DataFrame({"Close": up}), "XU100": pd.DataFrame({"Close": down})}
    )

    result = RiskEngine(provider=provider).market_risk("TEST", benchmark="XU100")

    assert result["correlation_with_market"] < 0
    assert result["beta"] < 0


def test_portfolio_correlation_perfectly_correlated_assets():
    closes = [100, 102, 101, 105, 103, 108, 107, 110, 106, 112] * 3
    df = pd.DataFrame({"Close": closes})
    provider = _MultiSymbolProvider({"A": df, "B": df})

    result = RiskEngine(provider=provider).portfolio_correlation(["A", "B"])

    assert result["average_correlation"] == pytest.approx(1.0, rel=1e-6)
    assert result["correlation_matrix"]["A"]["B"] == pytest.approx(1.0, rel=1e-6)


def test_portfolio_correlation_requires_at_least_two_distinct_assets():
    with pytest.raises(ValueError):
        RiskEngine().portfolio_correlation(["ONLY_ONE"])
