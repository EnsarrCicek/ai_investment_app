from fastapi import APIRouter, HTTPException

from app.engines.backtest.engine import BacktestEngine
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.backtest.walk_forward import WalkForwardOptimizer

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.get("/{symbol}")
def run_backtest(symbol: str, period: str = "2y"):
    try:
        return BacktestEngine().run(symbol.upper(), period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/compare-strategies")
def compare_strategies(symbol: str, period: str = "2y"):
    """AŞAMA 57: "Strateji Laboratuvarı" — beş adlandırılmış ağırlık ön ayarını
    (bkz. strategy_presets.py) aynı sembol/dönem üzerinde çalıştırıp getiriye
    göre sıralanmış bir karşılaştırma döner. Çok sembollü toplu tarama Flutter
    tarafında bu endpoint'in sembol başına çağrılmasıyla yapılır (Dashboard'daki
    10'arlı batch deseniyle aynı, bkz. dashboard_screen.dart).
    """
    try:
        return BacktestEngine().compare_strategies(symbol.upper(), STRATEGY_PRESETS, period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/walk-forward")
def run_walk_forward(symbol: str, period: str = "3y"):
    try:
        return WalkForwardOptimizer().run(symbol.upper(), period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
