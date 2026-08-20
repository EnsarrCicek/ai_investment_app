from datetime import datetime, timezone

import yfinance as yf

from app.models.news_raw import NewsRawItem
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.news.base import NewsProvider
from app.services.news.source_reliability import DEFAULT_SOURCE_RELIABILITY, classify_publisher


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
            category = classify_publisher(publisher)
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
