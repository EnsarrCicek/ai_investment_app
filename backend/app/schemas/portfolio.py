from datetime import datetime

from pydantic import BaseModel


class PortfolioPositionCreate(BaseModel):
    asset: str
    buy_price: float
    buy_date: datetime
    quantity: float
