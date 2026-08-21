from datetime import datetime

from pydantic import BaseModel


class AnalystConsensus(BaseModel):
    symbol: str
    as_of: datetime
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0
    total_analysts: int = 0
    consensus_score: float | None = None
    consensus_label: str = "VERI_YOK"
    price_target_current: float | None = None
    price_target_high: float | None = None
    price_target_low: float | None = None
    price_target_mean: float | None = None
    price_target_median: float | None = None
    upside_pct: float | None = None
    trend: list[dict] = []
    source: str = "yahoo_finance"
