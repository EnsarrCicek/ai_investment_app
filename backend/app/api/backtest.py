from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.engines.backtest.engine import BacktestEngine
from app.engines.backtest.strategy_presets import STRATEGY_PRESETS
from app.engines.backtest.walk_forward import WalkForwardOptimizer
from app.models.strategy_lab_run import StrategyLabRun
from app.repositories.strategy_lab_run_repository import StrategyLabRunRepository
from app.schemas.backtest import StrategyLabRunCreate

router = APIRouter(prefix="/backtest", tags=["backtest"])


# NOT: /lab-runs sabit-yol uç noktaları /{symbol}'DEN ÖNCE tanımlanmalı —
# aksi halde FastAPI "lab-runs"ı bir sembol koduymuş gibi /{symbol}'e
# düşürürdü (bkz. AŞAMA 60'ta funds.py'de aynı desen).


@router.post("/lab-runs")
def create_lab_run(payload: StrategyLabRunCreate, user_id: str = Depends(get_current_user_id)):
    """AŞAMA 62: kullanıcı isteği "her test yaptığımızda veri tutsun" —
    Strateji Laboratuvarı'ndaki her tarama kalıcı olarak kaydedilir; sonuçlar
    Flutter tarafında (sembol başına batch ile) zaten hesaplanmış olarak gelir.
    """
    winner = payload.results[0].preset if payload.results else None
    run = StrategyLabRun(
        user_id=user_id, **payload.model_dump(), winner_preset=winner, created_at=datetime.now(timezone.utc)
    )
    run_id = StrategyLabRunRepository().add(run)
    return {"id": run_id, **run.model_dump()}


@router.get("/lab-runs")
def list_lab_runs(user_id: str = Depends(get_current_user_id)):
    return StrategyLabRunRepository().list_for_user(user_id)


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
