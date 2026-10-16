from fastapi import APIRouter

from app.services.assets.asset_catalog import ASSET_CATALOG
from app.services.momentum import scanner

router = APIRouter(prefix="/momentum", tags=["momentum"])


@router.get("/scan")
def scan_momentum(include_all: bool = False):
    """Aktif varlık evreninde erken momentum taraması — salt-okunur; yazma/bildirim yok. Yatırım kararı değildir.
    `/{symbol}`'dan ÖNCE tanımlı olmalı."""
    assets, _source = ASSET_CATALOG.list_active()
    return scanner.scan([a.symbol for a in assets], include_all=include_all)


@router.get("/{symbol}")
def get_momentum(symbol: str):
    """Tek sembol için güncel erken momentum değerlendirmesi — salt-okunur. Yatırım kararı değildir."""
    symbol = symbol.upper()
    events = scanner.load_events([symbol], timeout=scanner.DEFAULT_SCAN_BUDGET_SECONDS)
    alert = scanner.evaluate_symbol(symbol, scanner.now_utc(),
                                    events=events.get(symbol) if events is not None else None)
    return alert.model_dump(mode="json")
