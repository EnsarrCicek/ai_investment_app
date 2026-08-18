from fastapi import APIRouter, HTTPException

from app.engines.event_intelligence.engine import EventIntelligenceEngine
from app.repositories.news_analysis_repository import NewsAnalysisRepository

router = APIRouter(prefix="/news", tags=["news"])


@router.post("/{symbol}/analyze")
def analyze_news(symbol: str, limit: int = 5):
    try:
        return EventIntelligenceEngine().analyze_recent_for_asset(symbol.upper(), limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/analysis")
def get_news_analysis(symbol: str, limit: int = 20):
    """Daha önce üretilmiş NewsAnalysis kayıtlarını okur — YENİ bir OpenAI
    çağrısı yapmaz (maliyet kararı: analiz yalnızca POST /analyze ile
    istendiğinde tetiklenir, bkz. DecisionEngine ile aynı ilke)."""
    return NewsAnalysisRepository().list_for_asset(symbol.upper(), limit=limit)
