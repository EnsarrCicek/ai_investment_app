from fastapi import APIRouter, HTTPException

from app.engines.event_intelligence.engine import EventIntelligenceEngine

router = APIRouter(prefix="/news", tags=["news"])


@router.post("/{symbol}/analyze")
def analyze_news(symbol: str, limit: int = 5):
    try:
        return EventIntelligenceEngine().analyze_recent_for_asset(symbol.upper(), limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
