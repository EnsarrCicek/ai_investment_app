from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.models.portfolio_position import PortfolioPosition, merged_currency
from app.repositories.portfolio_ledger_repository import PortfolioLedgerRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.portfolio_transaction_repository import PortfolioTransactionRepository
from app.schemas.portfolio import (
    PortfolioPositionClose,
    PortfolioPositionCreate,
    PortfolioPositionUpdate,
    PositionLimitCheckRequest,
    PositionSaleRequest,
)
from app.services.market_data.bist_provenance_provider import ProvenanceBistProvider
from app.services.portfolio import position_review
from app.services.portfolio.limit_check import check_limits, position_version
from app.services.portfolio.pnl_calculator import calculate_pnl
from app.services.portfolio.sale_ledger import SaleError, ledger_totals, plan_sale

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
    sales_by_asset: dict[str, list] = {}
    for sale_id, sale in PortfolioLedgerRepository().sales_for_user(user_id):
        sales_by_asset.setdefault(sale.asset, []).append((sale_id, sale))

    lots_by_asset: dict[str, list[PortfolioPosition]] = {}
    records_by_asset: dict[str, list[tuple[str, PortfolioPosition]]] = {}
    for lot_id, position in records:
        lots_by_asset.setdefault(position.asset, []).append(position)
        records_by_asset.setdefault(position.asset, []).append((lot_id, position))

    results = []
    total_invested = 0.0
    total_current = 0.0
    for asset in sorted(lots_by_asset):
        lots = lots_by_asset[asset]
        currency = merged_currency(lots)  # kayıtlı alış fiyatının birimi; güncel fiyatınkiyle karıştırılmaz
        rem_qty, rem_cost, sale_ids = ledger_totals(records_by_asset[asset], sales_by_asset.get(asset, []))
        version = position_version(records_by_asset[asset], sale_ids)
        if sale_ids:  # kısmi satış uygulanmış: kalan adet/maliyet defterden (tam hassasiyet), gösterim yuvarlaması aynı
            if rem_qty <= 0:
                continue
            quantity = float(rem_qty)
            avg_buy_price = round(float(rem_cost / rem_qty), 2)
        else:  # satış yok: önceki davranış birebir
            quantity = sum(lot.quantity for lot in lots)
            avg_buy_price = round(sum(lot.quantity * lot.buy_price for lot in lots) / quantity, 2)
        merged = PortfolioPosition(
            user_id=user_id,
            asset=asset,
            buy_price=avg_buy_price,
            buy_date=lots[0].buy_date,
            quantity=quantity,
            created_at=datetime.now(timezone.utc),
            currency=currency,
        )
        try:
            pnl = calculate_pnl(merged)
        except ValueError as exc:
            results.append(
                {"asset": asset, "quantity": quantity, "buy_price": avg_buy_price, "lot_count": len(lots),
                 "position_version": version, "currency": currency, "error": str(exc)}
            )
            continue
        total_invested += pnl["invested_amount"]
        total_current += pnl["current_value"]
        results.append(
            {"asset": asset, "quantity": quantity, "buy_price": avg_buy_price, "lot_count": len(lots),
             "position_version": version, "currency": currency, **pnl}
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


@router.post("/positions/{asset}/limit-check")
def limit_check(asset: str, payload: PositionLimitCheckRequest, user_id: str = Depends(get_current_user_id)):
    """Kullanıcı tanımlı kâr/zarar sınırının ELLE kontrolü — salt-okunur. Karar motoru çağrılmaz, bildirim
    gönderilmez, hiçbir kayıt yazılmaz (bkz. `app/services/portfolio/limit_check.py`)."""
    limits = {"profit_target_pct": payload.profit_target_pct, "max_loss_pct": payload.max_loss_pct}
    try:
        return check_limits(user_id, asset, payload.position_version, limits, PortfolioRepository(), ProvenanceBistProvider(),
                            ledger_repo=PortfolioLedgerRepository())
    except position_review.InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/positions/{asset}")
def update_position(asset: str, payload: PortfolioPositionUpdate, user_id: str = Depends(get_current_user_id)):
    repo = PortfolioRepository()
    data = payload.model_dump()
    # `currency` istekte HİÇ yoksa mevcut (birleşik) kayıtlı birim korunur; açıkça gönderildiyse (null dahil)
    # istek niyeti uygulanır. Hiçbir birim varsayılmaz.
    if "currency" not in payload.model_fields_set:
        existing = repo.get_position_for_asset(user_id, asset)
        data["currency"] = existing.currency if existing is not None else None
    position = PortfolioPosition(user_id=user_id, asset=asset, **data, created_at=datetime.now(timezone.utc))
    position_id = repo.replace_for_asset(user_id, asset, position)
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
    # İstek sözleşmesi aynı; muhasebe artık `/sell` ile ortak çekirdekten (kalan adedin TAMAMI, sürüm kontrolü yok —
    # eski istemciler sürüm göndermiyor), tek Firestore işleminde kayıt + lot silme.
    return _execute_sale(user_id, asset, quantity=None, sell_price=payload.sell_price, sell_date=payload.sell_date,
                         expected_version=None, request_currency=None)


def _execute_sale(user_id: str, asset: str, *, quantity, sell_price, sell_date, expected_version, request_currency):
    now = datetime.now(timezone.utc)

    def plan(lots, sales):
        return plan_sale(user_id, asset, lots, sales, quantity=quantity, sell_price=sell_price, sell_date=sell_date,
                         expected_version=expected_version, request_currency=request_currency, now=now)

    try:
        _, sale_plan = PortfolioLedgerRepository().execute_sale(user_id, asset, plan)
    except SaleError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    return sale_plan.transaction


@router.post("/positions/{asset}/sell")
def sell_position(asset: str, payload: PositionSaleRequest, user_id: str = Depends(get_current_user_id)):
    """Kısmi/tam satış — ağırlıklı ortalama maliyet, açık adet ve pozisyon sürümüyle (bayat ekran: 409
    POSITION_CHANGED). Alış lotları değiştirilmez; satış değişmez bir kayıttır; kalan adet tamamen satılırsa lotlar
    silinir. Kurumsal işlem doğrulaması olmadığından `basis_verified=false` (satış yine kaydedilir)."""
    return _execute_sale(user_id, asset, quantity=payload.quantity, sell_price=payload.sell_price,
                         sell_date=payload.sell_date, expected_version=payload.position_version,
                         request_currency=payload.currency)


@router.get("/history")
def get_history(user_id: str = Depends(get_current_user_id)):
    transactions = PortfolioTransactionRepository().list_for_user(user_id)
    total_realized_pnl = round(sum(t.realized_pnl for t in transactions), 2)
    return {
        "transactions": transactions,
        "total_realized_pnl": total_realized_pnl,
    }
