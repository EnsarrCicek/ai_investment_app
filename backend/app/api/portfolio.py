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
    results = []
    total_invested = 0.0
    total_current = 0.0
    for position_id, position in records:
        try:
            pnl = calculate_pnl(position)
        except ValueError as exc:
            results.append({"id": position_id, **position.model_dump(), "error": str(exc)})
            continue
        total_invested += pnl["invested_amount"]
        total_current += pnl["current_value"]
        results.append({"id": position_id, **position.model_dump(), **pnl})

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


@router.delete("/positions/{position_id}")
def delete_position(position_id: str):
    PortfolioRepository().delete(position_id)
    return {"deleted": position_id}
