from pydantic import BaseModel


class FundInvestmentSettingsUpdate(BaseModel):
    monthly_income: float | None = None
    monthly_budget: float


class FundPositionCreate(BaseModel):
    fund_code: str
    units: float
    avg_cost: float


class FundAllocateRequest(BaseModel):
    amount_tl: float
