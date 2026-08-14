from app.models.portfolio_position import PortfolioPosition
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider


def calculate_pnl(position: PortfolioPosition, provider: MarketDataProvider | None = None) -> dict:
    provider = provider or BistProvider()
    current_price = provider.get_latest(position.asset).close

    invested_amount = round(position.quantity * position.buy_price, 2)
    current_value = round(position.quantity * current_price, 2)
    profit_loss = round(current_value - invested_amount, 2)
    return_percent = round((profit_loss / invested_amount) * 100, 2) if invested_amount else 0.0

    return {
        "current_price": current_price,
        "invested_amount": invested_amount,
        "current_value": current_value,
        "profit_loss": profit_loss,
        "return_percent": return_percent,
    }
