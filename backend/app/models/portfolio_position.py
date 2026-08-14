from datetime import datetime

from pydantic import BaseModel


class PortfolioPosition(BaseModel):
    user_id: str
    asset: str
    buy_price: float
    buy_date: datetime
    quantity: float
    created_at: datetime
