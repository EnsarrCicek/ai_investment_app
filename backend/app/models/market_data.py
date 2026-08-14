from datetime import datetime

from pydantic import BaseModel


class MarketData(BaseModel):
    asset_id: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
