from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.models.portfolio_position import PortfolioPosition
from app.models.portfolio_transaction import PortfolioTransaction
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.portfolio_transaction_repository import PortfolioTransactionRepository
from app.schemas.portfolio import PortfolioPositionClose, PortfolioPositionCreate, PortfolioPositionUpdate
from app.services.portfolio.pnl_calculator import calculate_pnl, calculate_realized_pnl

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("/positions")
def create_position(payload: PortfolioPositionCreate, user_id: str = Depends(get_current_user_id)):
    position = PortfolioPosition(
        user_id=user_id, **payload.model_dump(), created_at=datetime.now(timezone.utc)
    )
    position_id = PortfolioRepository().add(position)
    return {"id": position_id, **position.model_dump()}


@router.get("/positions")
def list_positions(user_id: str = Depends(get_current_user_id)):
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


@router.put("/positions/{asset}")
def update_position(asset: str, payload: PortfolioPositionUpdate, user_id: str = Depends(get_current_user_id)):
    position = PortfolioPosition(
        user_id=user_id, asset=asset, **payload.model_dump(), created_at=datetime.now(timezone.utc)
    )
    position_id = PortfolioRepository().replace_for_asset(user_id, asset, position)
    return {"id": position_id, **position.model_dump()}


@router.delete("/positions/{asset}")
def delete_position(asset: str, user_id: str = Depends(get_current_user_id)):
    PortfolioRepository().delete_for_asset(user_id, asset)
    return {"deleted_asset": asset}


@router.post("/positions/{asset}/close")
def close_position(asset: str, payload: PortfolioPositionClose, user_id: str = Depends(get_current_user_id)):
    """AŞAMA 47: "sattım" akışı — eskiden DELETE tüm geçmişi sessizce
    kaybediyordu. Artık satış fiyatı isteniyor, gerçekleşen kâr/zarar
    hesaplanıp immutable bir PortfolioTransaction olarak kaydediliyor,
    sonra pozisyon lotları silinir.
    """
    portfolio_repo = PortfolioRepository()
    position = portfolio_repo.get_position_for_asset(user_id, asset)
    if position is None:
        raise HTTPException(status_code=404, detail=f"'{asset}' için açık bir pozisyon bulunamadı")

    pnl = calculate_realized_pnl(position.quantity, position.buy_price, payload.sell_price)
    now = datetime.now(timezone.utc)
    transaction = PortfolioTransaction(
        user_id=user_id,
        asset=asset,
        quantity=position.quantity,
        buy_price=position.buy_price,
        buy_date=position.buy_date,
        sell_price=payload.sell_price,
        sell_date=payload.sell_date or now,
        realized_pnl=pnl["realized_pnl"],
        realized_pnl_percent=pnl["realized_pnl_percent"],
        created_at=now,
    )
    PortfolioTransactionRepository().add(transaction)
    portfolio_repo.delete_for_asset(user_id, asset)
    return transaction


@router.get("/history")
def get_history(user_id: str = Depends(get_current_user_id)):
    transactions = PortfolioTransactionRepository().list_for_user(user_id)
    total_realized_pnl = round(sum(t.realized_pnl for t in transactions), 2)
    return {
        "transactions": transactions,
        "total_realized_pnl": total_realized_pnl,
    }
