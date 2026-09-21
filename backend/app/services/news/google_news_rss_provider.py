from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from app.models.news_raw import NewsRawItem
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.news.base import NewsProvider
from app.services.news.source_reliability import DEFAULT_SOURCE_RELIABILITY, classify_publisher

RSS_URL = "https://news.google.com/rss/search"
REQUEST_TIMEOUT_SECONDS = 10


class GoogleNewsRssProvider(NewsProvider):
    """Google News RSS arama sonuçları üzerinden Türkçe finans haberi adaptörü.

    Yahoo Finance'in BIST sembolleri için haber kapsamı çok kısıtlı (birçok
    sembolde 0-1 haber) — bu sağlayıcı Türkçe finans medyasını (Bloomberght,
    Mynet Finans, Foreks, KAP bildirimlerini yansıtan haberler vb.) ekleyerek
    kapsamı genişletir. Google'ın RSS feed telif metni bu feed'i "kişisel,
    ticari olmayan kullanım için kişisel bir feed reader içinde" kullanımla
    sınırlıyor; bu bilinerek, tek kullanıcılı/kişisel bu uygulama için kabul
    edilmiştir (bkz. KURULUM_GUNLUGU.md).
    """

    SOURCE = "google_news_rss"

    def __init__(self, config_repo: SystemConfigRepository | None = None):
        self._config_repo = config_repo or SystemConfigRepository()

    def get_latest_news(self, symbol: str, limit: int = 10, query_suffix: str = "hisse") -> list[NewsRawItem]:
        """`query_suffix`: aranan varlık türünü ayırt etmek için ("hisse" hisse
        senedi haberleri için varsayılan; fon haberleri AŞAMA 60'ta "fon" ile
        arıyor — bkz. app/api/funds.py get_fund_news).
        """
        weights = self._config_repo.get("source_reliability", DEFAULT_SOURCE_RELIABILITY)
        query = quote(f"{symbol} {query_suffix}")
        url = f"{RSS_URL}?q={query}&hl=tr&gl=TR&ceid=TR:tr"

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (requests.RequestException, ElementTree.ParseError):
            return []

        received_at = datetime.now(timezone.utc)
        items: list[NewsRawItem] = []
        for entry in root.findall(".//item")[:limit]:
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            guid = (entry.findtext("guid") or "").strip()
            pub_date_text = entry.findtext("pubDate")
            source_el = entry.find("source")
            raw_publisher = source_el.text.strip() if source_el is not None and source_el.text else None
            publisher = raw_publisher or "Unknown"

            if not title or not guid or not pub_date_text:
                continue
            try:
                published_at = parsedate_to_datetime(pub_date_text)
            except (TypeError, ValueError):
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)

            category = classify_publisher(raw_publisher)
            items.append(
                NewsRawItem(
                    external_id=f"google_news:{guid}",
                    title=title,
                    summary="",
                    url=link,
                    publisher=publisher,
                    source=self.SOURCE,
                    source_reliability=weights.get(category) if category is not None else None,
                    related_assets=[symbol],
                    published_at=published_at,
                    received_at=received_at,
                )
            )
        return items
