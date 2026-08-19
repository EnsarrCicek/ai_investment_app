from datetime import datetime, timezone

from app.models.portfolio_position import PortfolioPosition
from app.services.portfolio.pnl_calculator import calculate_pnl, calculate_realized_pnl


def _position(buy_price: float, quantity: float) -> PortfolioPosition:
    now = datetime.now(timezone.utc)
    return PortfolioPosition(
        user_id="u1", asset="TEST", buy_price=buy_price, quantity=quantity, buy_date=now, created_at=now
    )


def test_calculate_pnl_profit(fake_provider):
    position = _position(buy_price=100.0, quantity=10)
    result = calculate_pnl(position, provider=fake_provider(close_price=120.0))
    assert result["invested_amount"] == 1000.0
    assert result["current_value"] == 1200.0
    assert result["profit_loss"] == 200.0
    assert result["return_percent"] == 20.0


def test_calculate_pnl_loss(fake_provider):
    position = _position(buy_price=100.0, quantity=10)
    result = calculate_pnl(position, provider=fake_provider(close_price=80.0))
    assert result["profit_loss"] == -200.0
    assert result["return_percent"] == -20.0


def test_calculate_pnl_zero_invested_returns_zero_percent(fake_provider):
    position = _position(buy_price=0.0, quantity=10)
    result = calculate_pnl(position, provider=fake_provider(close_price=50.0))
    assert result["return_percent"] == 0.0


def test_calculate_realized_pnl_profit():
    result = calculate_realized_pnl(quantity=10, buy_price=100.0, sell_price=120.0)
    assert result["realized_pnl"] == 200.0
    assert result["realized_pnl_percent"] == 20.0


def test_calculate_realized_pnl_loss():
    result = calculate_realized_pnl(quantity=10, buy_price=100.0, sell_price=90.0)
    assert result["realized_pnl"] == -100.0
    assert result["realized_pnl_percent"] == -10.0


def test_calculate_realized_pnl_zero_invested_returns_zero_percent():
    result = calculate_realized_pnl(quantity=10, buy_price=0.0, sell_price=50.0)
    assert result["realized_pnl_percent"] == 0.0
