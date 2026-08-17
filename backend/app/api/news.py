from fastapi import APIRouter

from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.yahoo_news_provider import YahooNewsProvider

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/{symbol}")
def get_news(symbol: str, limit: int = 10):
    items = YahooNewsProvider().get_latest_news(symbol.upper(), limit=limit)
    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)
    return items
