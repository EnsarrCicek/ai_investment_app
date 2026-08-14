from datetime import datetime, timezone

import yfinance as yf

from app.models.news_raw import NewsRawItem
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.news.base import NewsProvider

# Ana doküman bölüm 7: kaynak güvenilirlik ağırlıkları system_config'ten okunur, hard-code değildir.
DEFAULT_SOURCE_RELIABILITY = {
    "OFFICIAL_INSTITUTION": 1.00,
    "KAP": 1.00,
    "CENTRAL_BANK": 0.98,
    "GOVERNMENT": 0.95,
    "NEWS_AGENCY": 0.90,
    "FINANCIAL_MEDIA": 0.80,
    "OTHER_MEDIA": 0.60,
    "SOCIAL_MEDIA": 0.30,
}

# Yayıncı adından bölüm 7'deki kategoriye eşleme (ağırlığın kendisi değil, hangi kategoriye
# girdiğinin sınıflandırması — sayısal değerler her zaman system_config'ten gelir).
_PUBLISHER_CATEGORY = {
    "reuters": "NEWS_AGENCY",
    "associated press": "NEWS_AGENCY",
    "bloomberg": "FINANCIAL_MEDIA",
    "mt newswires": "FINANCIAL_MEDIA",
    "motley fool": "FINANCIAL_MEDIA",
    "investor's business daily": "FINANCIAL_MEDIA",
    "barrons": "FINANCIAL_MEDIA",
}


def _classify_publisher(publisher: str) -> str:
    name = publisher.lower()
    for key, category in _PUBLISHER_CATEGORY.items():
        if key in name:
            return category
    return "OTHER_MEDIA"


class YahooNewsProvider(NewsProvider):
    """Yahoo Finance (yfinance Ticker.news) tabanlı haber adaptörü."""

    SOURCE = "yahoo_finance"

    def __init__(self, config_repo: SystemConfigRepository | None = None):
        self._config_repo = config_repo or SystemConfigRepository()

    def get_latest_news(self, symbol: str, limit: int = 10) -> list[NewsRawItem]:
        weights = self._config_repo.get("source_reliability", DEFAULT_SOURCE_RELIABILITY)
        ticker = yf.Ticker(f"{symbol}.IS")
        raw_items = ticker.news or []

        received_at = datetime.now(timezone.utc)
        items: list[NewsRawItem] = []
        for raw in raw_items[:limit]:
            content = raw.get("content", {})
            publisher = content.get("provider", {}).get("displayName", "Unknown")
            category = _classify_publisher(publisher)
            url = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", "")
            pub_date = content.get("pubDate") or content.get("displayTime")

            items.append(
                NewsRawItem(
                    external_id=raw.get("id", ""),
                    title=content.get("title", ""),
                    summary=content.get("summary", ""),
                    url=url,
                    publisher=publisher,
                    source=self.SOURCE,
                    source_reliability=weights.get(category, weights["OTHER_MEDIA"]),
                    related_assets=[symbol],
                    published_at=datetime.fromisoformat(pub_date.replace("Z", "+00:00")),
                    received_at=received_at,
                )
            )
        return items
