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


class Quote(BaseModel):
    """Anlık fiyat özeti. `timestamp`, verinin gerçekte hangi ana ait olduğunu
    gösterir — sağlayıcı (Yahoo Finance) hafif gecikmeli olabilir, bu asla
    gizlenmez (bkz. BistProvider.get_quote)."""

    asset_id: str
    timestamp: datetime
    last_price: float
    previous_close: float
    change: float
    change_percent: float | None
    open: float
    high: float
    low: float
    volume: int
    source: str
