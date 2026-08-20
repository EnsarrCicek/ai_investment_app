from datetime import datetime

from pydantic import BaseModel


class FundAnalysis(BaseModel):
    fund_code: str
    fund_name: str
    price: float
    portfolio_size: float
    investor_count: int
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    return_6m_pct: float | None = None
    return_1y_pct: float | None = None
    composite_score: float
    risk_level: str | None = None
    equity_exposure_pct: float | None = None
    safe_exposure_pct: float | None = None
    explanation: str = ""
    as_of_date: str
    generated_at: datetime
