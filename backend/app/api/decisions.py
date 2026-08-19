from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id_optional
from app.engines.decision.engine import DecisionEngine
from app.engines.explanation.engine import ExplanationEngine
from app.repositories.ai_decision_repository import AIDecisionRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.notifications.fcm_sender import notify_if_new_opportunity, notify_if_strong_decision

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/{symbol}")
def get_decision(symbol: str, user_id: str | None = Depends(get_current_user_id_optional)):
    try:
        decision = DecisionEngine().decide_for_asset(symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if user_id:
        # AŞAMA 45: yalnızca kullanıcının PORTFÖYÜNDE olan varlıklar için
        # bildirim gönderilir. Dashboard artık BIST100'ün tamamını
        # sorguladığından (AŞAMA 43), "her sorgulanan varlık" eski davranışı
        # onlarca alakasız bildirime yol açardı (bkz. fcm_sender.py notu).
        holding = PortfolioRepository().get_position_for_asset(user_id, symbol.upper())
        if holding is not None:
            notify_if_strong_decision(user_id, decision, quantity_held=holding.quantity)
        else:
            # AŞAMA 48/19: elde tutulmayan varlıklar için yalnızca en yüksek
            # güvenilirlikli sinyalde ("STRONG_BULLISH_INITIATION") ve somut
            # bir miktar öneriyle bildirim gönderilir (bkz. fcm_sender.py).
            notify_if_new_opportunity(user_id, decision)

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
