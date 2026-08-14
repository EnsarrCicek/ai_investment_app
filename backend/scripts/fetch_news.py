"""Seed edilmiş varlıklar için gerçek haber çeker ve Firestore'a (news_raw) yazar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.asset_repository import AssetRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.yahoo_news_provider import YahooNewsProvider

if __name__ == "__main__":
    assets = AssetRepository().list_active()
    provider = YahooNewsProvider()
    repo = NewsRawRepository()

    for asset in assets:
        items = provider.get_latest_news(asset.symbol, limit=5)
        for item in items:
            repo.upsert(item)
        print(f"{asset.symbol}: {len(items)} haber yazıldı")
        if items:
            print(f"  Örnek: [{items[0].publisher} / güvenilirlik={items[0].source_reliability}] {items[0].title}")
