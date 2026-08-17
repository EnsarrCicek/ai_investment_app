from fastapi import APIRouter, HTTPException

from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.repositories.ai_decision_repository import AIDecisionRepository

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/{symbol}")
def get_decision(symbol: str):
    try:
        return DecisionEngine().decide_for_asset(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/history")
def get_decision_history(symbol: str, limit: int = 20):
    return AIDecisionRepository().list_for_asset(symbol.upper(), limit=limit)


@router.get("/{symbol}/explanation")
def get_decision_explanation(symbol: str):
    try:
        return ExplanationEngine().explain(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
