from fastapi import APIRouter, HTTPException

from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/{symbol}")
def get_decision(symbol: str):
    try:
        return DecisionEngine().decide_for_asset(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/explanation")
def get_decision_explanation(symbol: str):
    try:
        return ExplanationEngine().explain(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
