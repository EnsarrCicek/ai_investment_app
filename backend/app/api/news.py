from fastapi import APIRouter

from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider
from app.services.news.merge import merge_prioritizing_analyst_mentions
from app.services.news.yahoo_news_provider import YahooNewsProvider

router = APIRouter(prefix="/news", tags=["news"])

# AŞAMA 61: kullanıcı isteği "güvenilir analistleri araştır, al mı diyorlar
# sat mı diyorlar" — genel "{sembol} hisse" araması çoğunlukla perakende/
# TradingView tarzı içerik döndürüyordu; bu ayrı sorgu banka/aracı kurum
# hedef fiyat ve tavsiye haberlerini (HSBC, BofA vb.) çok daha güvenilir
# şekilde yüzeye çıkarıyor (canlı test edildi).
ANALYST_QUERY_SUFFIX = "hedef fiyat OR tavsiye OR analist"


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

    analyst_items = GoogleNewsRssProvider().get_latest_news(symbol, limit=limit, query_suffix=ANALYST_QUERY_SUFFIX)
    for item in analyst_items:
        item.is_analyst_mention = True
    items += analyst_items

    items = merge_prioritizing_analyst_mentions(items, limit)

    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)
    return items
