from fastapi import APIRouter, HTTPException, Response

from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository
from app.services.assets.asset_catalog import ASSET_CATALOG

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[Asset])
def list_assets(response: Response):
    # Kısa TTL'li süreç içi önbellek; yalnız yerel LAN modunda kota hatasında seed listesi (bkz. asset_catalog).
    assets, source = ASSET_CATALOG.list_active()
    response.headers["X-Asset-Source"] = source
    return assets


@router.get("/{symbol}", response_model=Asset)
def get_asset(symbol: str):
    asset = AssetRepository().get_by_symbol(symbol.upper())
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")
    return asset
