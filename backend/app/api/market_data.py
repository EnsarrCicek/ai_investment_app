from fastapi import APIRouter, HTTPException

from app.models.market_data import Quote
from app.services.market_data.bist_provider import BistProvider
from app.services.market_data.changes import compute_period_changes

router = APIRouter(prefix="/market-data", tags=["market-data"])

_ALLOWED_INTERVALS = {"5m", "15m", "30m", "1h", "1d", "1wk", "1mo", "3mo"}


@router.get("/{symbol}/quote", response_model=Quote)
def get_quote(symbol: str):
    try:
        return BistProvider().get_quote(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/history")
def get_history(symbol: str, period: str = "3mo", interval: str = "1d"):
    if interval not in _ALLOWED_INTERVALS:
        raise HTTPException(status_code=422, detail=f"Desteklenmeyen interval: {interval}")
    try:
        df = BistProvider().get_history(symbol.upper(), period=period, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return [
        {
            "timestamp": ts.isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for ts, row in df.iterrows()
    ]


@router.get("/{symbol}/changes")
def get_changes(symbol: str):
    try:
        df = BistProvider().get_history(symbol.upper(), period="2y", interval="1d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return compute_period_changes(df)
