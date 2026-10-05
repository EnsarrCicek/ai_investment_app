from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


CURRENCY_PATTERN = r"^[A-Z]{3}$"


class PortfolioPositionCreate(BaseModel):
    asset: str
    buy_price: float
    buy_date: datetime
    quantity: float
    # `buy_price`'ın para birimi (ISO 4217). İstemci yalnız doğrulanmış kaynaktan biliyorsa gönderir; yoksa None.
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)


class PortfolioPositionUpdate(BaseModel):
    buy_price: float
    buy_date: datetime
    quantity: float
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)


class PortfolioPositionClose(BaseModel):
    """"Sattım" akışı için — AŞAMA 47. sell_date verilmezse şimdi kullanılır."""

    sell_price: float
    sell_date: datetime | None = None


class PositionLimitCheckRequest(BaseModel):
    """Kullanıcı sınırı kontrolü — yalnız sınır yüzdeleri ve istemcinin sınırı kaydettiği pozisyon sürümü.
    Fiyat, maliyet veya "doğrulandı" bayrağı kabul edilmez (fazla alan 422)."""

    model_config = ConfigDict(extra="forbid")

    position_version: str
    profit_target_pct: float | None = None
    max_loss_pct: float | None = None
