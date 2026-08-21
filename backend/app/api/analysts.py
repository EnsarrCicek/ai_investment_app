from fastapi import APIRouter

from app.services.analysts.consensus_cache_service import get_analyst_consensus

router = APIRouter(prefix="/analysts", tags=["analysts"])


@router.get("/{symbol}")
def get_analyst_consensus_endpoint(symbol: str):
    symbol = symbol.upper()
    return get_analyst_consensus(symbol)
