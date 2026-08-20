"""Haber kaynaklarını birleştirme yardımcıları — AŞAMA 61.

Analist hedef fiyat/tavsiye haberleri genelde sayıca az ama sıradan
piyasa haberlerinden daha değerlidir — bu yüzden salt tarihe göre
sıralayıp kesmek yerine, analist etiketli olanlar önce garanti edilir,
kalan yer en yeni diğer haberlerle doldurulur.
"""

from app.models.news_raw import NewsRawItem


def merge_prioritizing_analyst_mentions(items: list[NewsRawItem], limit: int) -> list[NewsRawItem]:
    by_id: dict[str, NewsRawItem] = {}
    for item in items:
        existing = by_id.get(item.external_id)
        if existing is not None and existing.is_analyst_mention and not item.is_analyst_mention:
            continue  # daha önce analist etiketiyle eklenmişse, etiketsiz kopya onu ezmesin
        by_id[item.external_id] = item

    all_items = sorted(by_id.values(), key=lambda i: i.published_at, reverse=True)
    analyst_only = [i for i in all_items if i.is_analyst_mention][:limit]
    remaining_slots = limit - len(analyst_only)
    other_items = [i for i in all_items if not i.is_analyst_mention][:remaining_slots]

    return sorted(analyst_only + other_items, key=lambda i: i.published_at, reverse=True)
