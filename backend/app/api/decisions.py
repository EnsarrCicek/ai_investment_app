from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id_optional
from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.services.notifications.fcm_sender import notify_if_strong_decision

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/{symbol}")
def get_decision(symbol: str, user_id: str | None = Depends(get_current_user_id_optional)):
    try:
        decision = DecisionEngine().decide_for_asset(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if user_id:
        notify_if_strong_decision(user_id, decision)

    return decision


@router.get("/{symbol}/history")
def get_decision_history(symbol: str, limit: int = 20):
    return AIDecisionRepository().list_for_asset(symbol.upper(), limit=limit)


@router.get("/{symbol}/explanation")
def get_decision_explanation(symbol: str):
    try:
        return ExplanationEngine().explain(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
