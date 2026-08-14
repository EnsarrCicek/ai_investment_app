from pydantic import BaseModel


class Asset(BaseModel):
    symbol: str
    name: str
    market: str
    asset_type: str
    currency: str
    active: bool = True
