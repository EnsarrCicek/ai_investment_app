from fastapi import APIRouter, HTTPException

from app.engines.backtest.engine import BacktestEngine
from app.engines.backtest.walk_forward import WalkForwardOptimizer

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.get("/{symbol}")
def run_backtest(symbol: str, period: str = "2y"):
    try:
        return BacktestEngine().run(symbol.upper(), period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/walk-forward")
def run_walk_forward(symbol: str, period: str = "3y"):
    try:
        return WalkForwardOptimizer().run(symbol.upper(), period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
