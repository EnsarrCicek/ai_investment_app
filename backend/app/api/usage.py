from fastapi import APIRouter

from app.core.config import EVENT_INTELLIGENCE_BUDGET_USD
from app.engines.event_intelligence.usage import summarize
from app.repositories.token_usage_repository import TokenUsageRepository

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("")
def get_usage():
    logs = TokenUsageRepository().list_all()
    return summarize(logs, budget_usd=EVENT_INTELLIGENCE_BUDGET_USD)
