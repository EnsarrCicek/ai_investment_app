from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.engines.risk.engine import RiskEngine
from app.repositories.portfolio_ledger_repository import PortfolioLedgerRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.portfolio.pnl_calculator import calculate_pnl
from app.services.portfolio.sale_ledger import remaining_position

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/{symbol}")
def get_asset_risk(symbol: str):
    try:
        return RiskEngine().asset_risk(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/liquidity")
def get_asset_liquidity(symbol: str, quantity: float):
    try:
        return RiskEngine().asset_liquidity(symbol.upper(), quantity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/gap")
def get_asset_gap_risk(symbol: str):
    try:
        return RiskEngine().gap_risk(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/market")
def get_asset_market_risk(symbol: str):
    try:
        return RiskEngine().market_risk(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/portfolio/concentration")
def get_portfolio_concentration(user_id: str = Depends(get_current_user_id)):
    records = PortfolioRepository().list_for_user(user_id)
    sales_by_asset: dict[str, list] = {}
    for sale_id, sale in PortfolioLedgerRepository().sales_for_user(user_id):
        sales_by_asset.setdefault(sale.asset, []).append((sale_id, sale))
    lots_by_asset: dict[str, list] = {}
    for lot_id, position in records:
        lots_by_asset.setdefault(position.asset, []).append((lot_id, position))

    position_values: dict[str, float] = {}
    for asset, lots in lots_by_asset.items():
        sales = sales_by_asset.get(asset, [])
        # Kısmi satış uygulanmış varlıkta maruziyet yalnız kanonik KALAN adetten (bkz. sale_ledger). Satış yoksa
        # önceki lot bazlı hesap birebir; tamamen satılmış varlık yoğunlaşmaya girmez.
        remaining, sale_ids = remaining_position(user_id, asset, lots, sales)
        items = [remaining] if sale_ids else [p for _, p in lots]
        for position in items:
            if position is None:
                continue
            try:
                pnl = calculate_pnl(position)
            except ValueError:
                continue
            position_values[asset] = position_values.get(asset, 0.0) + pnl["current_value"]

    return RiskEngine().portfolio_concentration(position_values)


@router.get("/portfolio/correlation")
def get_portfolio_correlation(user_id: str = Depends(get_current_user_id)):
    records = PortfolioRepository().list_for_user(user_id)
    symbols = [position.asset for _position_id, position in records]
    try:
        return RiskEngine().portfolio_correlation(symbols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
