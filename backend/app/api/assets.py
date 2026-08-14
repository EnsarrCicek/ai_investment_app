from fastapi import APIRouter, HTTPException

from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
def list_assets():
    return AssetRepository().list_active()


@router.get("/{symbol}", response_model=Asset)
def get_asset(symbol: str):
    asset = AssetRepository().get_by_symbol(symbol.upper())
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")
    return asset
