from datetime import datetime

from pydantic import BaseModel


class PortfolioPositionCreate(BaseModel):
    asset: str
    buy_price: float
    buy_date: datetime
    quantity: float


class PortfolioPositionUpdate(BaseModel):
    buy_price: float
    buy_date: datetime
    quantity: float


class PortfolioPositionClose(BaseModel):
    """"Sattım" akışı için — AŞAMA 47. sell_date verilmezse şimdi kullanılır."""

    sell_price: float
    sell_date: datetime | None = None
