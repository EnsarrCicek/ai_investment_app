from datetime import datetime

from pydantic import BaseModel


class FundInvestmentSettings(BaseModel):
    user_id: str
    monthly_income: float | None = None
    monthly_budget: float
    updated_at: datetime
