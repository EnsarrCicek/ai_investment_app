from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.portfolio_position import PortfolioPosition
from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import PortfolioPositionCreate
from app.services.portfolio.pnl_calculator import calculate_pnl

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("/positions")
def create_position(payload: PortfolioPositionCreate):
    position = PortfolioPosition(
        **payload.model_dump(), created_at=datetime.now(timezone.utc)
    )
    position_id = PortfolioRepository().add(position)
    return {"id": position_id, **position.model_dump()}


@router.get("/positions")
def list_positions(user_id: str):
    records = PortfolioRepository().list_for_user(user_id)

    lots_by_asset: dict[str, list[PortfolioPosition]] = {}
    for _, position in records:
        lots_by_asset.setdefault(position.asset, []).append(position)

    results = []
    total_invested = 0.0
    total_current = 0.0
    for asset in sorted(lots_by_asset):
        lots = lots_by_asset[asset]
        quantity = sum(lot.quantity for lot in lots)
        avg_buy_price = round(sum(lot.quantity * lot.buy_price for lot in lots) / quantity, 2)
        merged = PortfolioPosition(
            user_id=user_id,
            asset=asset,
            buy_price=avg_buy_price,
            buy_date=lots[0].buy_date,
            quantity=quantity,
            created_at=datetime.now(timezone.utc),
        )
        try:
            pnl = calculate_pnl(merged)
        except ValueError as exc:
            results.append(
                {"asset": asset, "quantity": quantity, "buy_price": avg_buy_price, "lot_count": len(lots), "error": str(exc)}
            )
            continue
        total_invested += pnl["invested_amount"]
        total_current += pnl["current_value"]
        results.append(
            {"asset": asset, "quantity": quantity, "buy_price": avg_buy_price, "lot_count": len(lots), **pnl}
        )

    total_pnl = round(total_current - total_invested, 2)
    total_return_pct = round((total_pnl / total_invested) * 100, 2) if total_invested else 0.0

    return {
        "positions": results,
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_current_value": round(total_current, 2),
            "total_profit_loss": total_pnl,
            "total_return_percent": total_return_pct,
        },
    }


@router.delete("/positions/{asset}")
def delete_position(asset: str, user_id: str):
    PortfolioRepository().delete_for_asset(user_id, asset)
    return {"deleted_asset": asset}
