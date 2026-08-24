"""Foreks'in resmi RSS akışından genel piyasa haberlerini çekip, bilinen BIST
varlıklarına değinenleri news_raw'a yazar. Projede zamanlayıcı (cron/scheduler)
YOK (bkz. KURULUM_GUNLUGU AŞAMA 32) — bu script GET /news/foreks/latest ile
aynı işi yapar, manuel/periyodik olarak çalıştırılmak üzere (fetch_news.py ile
aynı desen)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.news_raw_repository import NewsRawRepository
from app.services.news.foreks_news_provider import ForeksNewsProvider

if __name__ == "__main__":
    items = ForeksNewsProvider().get_market_news(limit=100)
    repo = NewsRawRepository()
    for item in items:
        repo.upsert(item)

    print(f"Toplam {len(items)} Foreks haberi (BIST varlığına değinen) yazıldı.")
    for item in items:
        print(f"  [{', '.join(item.related_assets)}] {item.title}")
