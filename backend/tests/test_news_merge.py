from datetime import datetime, timedelta, timezone

from app.models.news_raw import NewsRawItem
from app.services.news.merge import merge_prioritizing_analyst_mentions

_NOW = datetime.now(timezone.utc)


def _item(external_id, days_ago, is_analyst_mention=False, title="Başlık"):
    return NewsRawItem(
        external_id=external_id,
        title=title,
        summary="",
        url="https://example.com",
        publisher="Test",
        source="test",
        source_reliability=0.8,
        related_assets=["THYAO"],
        published_at=_NOW - timedelta(days=days_ago),
        received_at=_NOW,
        is_analyst_mention=is_analyst_mention,
    )


def test_guarantees_analyst_items_are_not_crowded_out_by_newer_general_news():
    general = [_item(f"g{i}", days_ago=i) for i in range(5)]  # çok yeni genel haberler
    analyst = [_item("a1", days_ago=20, is_analyst_mention=True)]  # eski ama analist

    result = merge_prioritizing_analyst_mentions(general + analyst, limit=5)

    assert any(i.external_id == "a1" for i in result)


def test_deduplicates_same_external_id_keeping_analyst_tag():
    general_copy = _item("dup", days_ago=1, is_analyst_mention=False)
    analyst_copy = _item("dup", days_ago=1, is_analyst_mention=True)

    result = merge_prioritizing_analyst_mentions([general_copy, analyst_copy], limit=10)

    assert len(result) == 1
    assert result[0].is_analyst_mention is True


def test_result_is_sorted_by_published_at_descending():
    items = [_item("a", days_ago=5), _item("b", days_ago=1), _item("c", days_ago=3)]

    result = merge_prioritizing_analyst_mentions(items, limit=10)

    assert [i.external_id for i in result] == ["b", "c", "a"]


def test_respects_limit():
    items = [_item(f"x{i}", days_ago=i) for i in range(10)]

    result = merge_prioritizing_analyst_mentions(items, limit=3)

    assert len(result) == 3
