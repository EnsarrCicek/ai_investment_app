from fastapi import APIRouter, HTTPException

from app.engines.risk.engine import RiskEngine
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.portfolio.pnl_calculator import calculate_pnl

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/{symbol}")
def get_asset_risk(symbol: str):
    try:
        return RiskEngine().asset_risk(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolio/concentration")
def get_portfolio_concentration(user_id: str):
    records = PortfolioRepository().list_for_user(user_id)
    position_values: dict[str, float] = {}
    for _position_id, position in records:
        try:
            pnl = calculate_pnl(position)
        except ValueError:
            continue
        position_values[position.asset] = position_values.get(position.asset, 0.0) + pnl["current_value"]

    return RiskEngine().portfolio_concentration(position_values)
