from app.models.news_raw import NewsRawItem
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.firm_extraction import extract_analyst_firm
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider
from app.services.news.merge import merge_prioritizing_analyst_mentions
from app.services.news.yahoo_news_provider import YahooNewsProvider

# AŞAMA 61: kullanıcı isteği "güvenilir analistleri araştır, al mı diyorlar
# sat mı diyorlar" — genel "{sembol} hisse" araması çoğunlukla perakende/
# TradingView tarzı içerik döndürüyordu; bu ayrı sorgu banka/aracı kurum
# hedef fiyat ve tavsiye haberlerini (HSBC, BofA vb.) çok daha güvenilir
# şekilde yüzeye çıkarıyor (canlı test edildi).
ANALYST_QUERY_SUFFIX = "hedef fiyat OR tavsiye OR analist"


def fetch_and_store_news(symbol: str, limit: int = 10) -> list[NewsRawItem]:
    """Bir varlık için Yahoo + Google News + (daha önce eşleştirilmiş) Foreks
    haberlerini birleştirir, `news_raw`'a yazar, döner. Bu mantık AŞAMA 69'a
    kadar doğrudan `api/news.py::get_news` içindeydi; AŞAMA 70'teki günlük
    toplu analiz job'ı da AYNI mantığı kullanabilsin diye buraya çıkarıldı.
    """
    symbol = symbol.upper()
    items: list[NewsRawItem] = []
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

    # Foreks haberleri burada CANLI tekrar çekilmez (GET /news/foreks/latest
    # ya da günlük job zaten tüm piyasayı tarayıp news_raw'a yazıyor) — bu
    # sembole daha önce eşleştirilmiş Foreks kayıtları doğrudan Firestore'dan
    # okunup diğer kaynaklarla birlikte döndürülür.
    items += NewsRawRepository().get_recent(symbol, limit=limit)

    items = merge_prioritizing_analyst_mentions(items, limit)

    # AŞAMA 64: "kim demiş, ne demiş" — gerçek başlık/özet metninde bilinen
    # bir banka/aracı kurum adı geçiyorsa (uydurulmaz, yalnızca tespit edilir)
    # kullanıcıya gösterilir.
    for item in items:
        item.analyst_firm = extract_analyst_firm(f"{item.title} {item.summary}")

    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)
    return items
