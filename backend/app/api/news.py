from fastapi import APIRouter

from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.foreks_news_provider import ForeksNewsProvider
from app.services.news.news_aggregator import fetch_and_store_news

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/foreks/latest")
def get_foreks_market_news(limit: int = 100):
    """Foreks'in resmi RSS akışından genel piyasa haberlerini çeker, bilinen
    BIST varlıklarına değinenleri tespit edip news_raw'a yazar (aynı haber_id
    tekrar üst üste yazılır, birikmez — bkz. NewsRawRepository.upsert).
    Herhangi bir OpenAI çağrısı YAPMAZ (maliyetsiz) — analiz, mevcut
    POST /news/{symbol}/analyze akışıyla, ilgili varlık ekranı açıldığında
    ayrıca tetiklenir.
    """
    items = ForeksNewsProvider().get_market_news(limit=limit)
    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)
    return items

@router.get("/{symbol}")
def get_news(symbol: str, limit: int = 10):
    return fetch_and_store_news(symbol.upper(), limit=limit)
