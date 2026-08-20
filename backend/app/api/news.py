from fastapi import APIRouter

from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider
from app.services.news.yahoo_news_provider import YahooNewsProvider

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/{symbol}")
def get_news(symbol: str, limit: int = 10):
    symbol = symbol.upper()
    items = []
    try:
        items += YahooNewsProvider().get_latest_news(symbol, limit=limit)
    except Exception:
        # Yahoo Finance ara sıra geçici hata verebiliyor; Google News ile devam edilir.
        pass
    items += GoogleNewsRssProvider().get_latest_news(symbol, limit=limit)

    items.sort(key=lambda item: item.published_at, reverse=True)
    items = items[:limit]

    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)
    return items
