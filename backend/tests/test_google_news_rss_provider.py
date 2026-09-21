import requests

from app.services.news import google_news_rss_provider as provider_module
from app.services.news.google_news_rss_provider import GoogleNewsRssProvider

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>THYAO teknik analiz - Mynet Finans</title>
  <link>https://news.google.com/rss/articles/abc123</link>
  <guid isPermaLink="false">abc123</guid>
  <pubDate>Wed, 19 Aug 2026 15:52:00 GMT</pubDate>
  <description>&lt;a href="..."&gt;THYAO teknik analiz&lt;/a&gt;</description>
  <source url="https://finans.mynet.com">Mynet Finans</source>
</item>
<item>
  <title>THYAO Sermaye Artırımı Bildirimi - KAP</title>
  <link>https://news.google.com/rss/articles/def456</link>
  <guid isPermaLink="false">def456</guid>
  <pubDate>Tue, 18 Aug 2026 10:00:00 GMT</pubDate>
  <description>...</description>
  <source url="https://kap.org.tr">KAP</source>
</item>
<item>
  <title>Tarihi olmayan haber</title>
  <link>https://news.google.com/rss/articles/ghi789</link>
  <guid isPermaLink="false">ghi789</guid>
  <description>pubDate eksik, atlanmalı</description>
  <source url="https://example.com">Example</source>
</item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeConfigRepo:
    def get(self, _key, default):
        return default


def _patch_requests(monkeypatch, response):
    monkeypatch.setattr(provider_module.requests, "get", lambda *_a, **_kw: response)


def test_parses_items_and_skips_entries_missing_pub_date(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(_SAMPLE_RSS.encode("utf-8")))

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=10)

    assert len(items) == 2
    assert items[0].external_id == "google_news:abc123"
    assert items[0].publisher == "Mynet Finans"
    assert items[0].related_assets == ["THYAO"]
    assert items[0].source == "google_news_rss"
    assert items[0].source_reliability == 0.80


def test_kap_publisher_gets_highest_reliability_weight(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(_SAMPLE_RSS.encode("utf-8")))

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=10)

    kap_item = next(item for item in items if item.publisher == "KAP")
    assert kap_item.source_reliability == 1.00


_UNMAPPED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>THYAO ile ilgili bir haber</title>
  <link>https://news.google.com/rss/articles/xyz999</link>
  <guid isPermaLink="false">xyz999</guid>
  <pubDate>Wed, 19 Aug 2026 15:52:00 GMT</pubDate>
  <description>...</description>
  <source url="https://completely-unmapped-outlet.example">Completely Unmapped Outlet</source>
</item>
</channel></rss>"""


def test_unmapped_publisher_does_not_become_fake_other_media(monkeypatch):
    """HATA 15C SON DÜZELTME: eşleşmeyen bir yayıncı artık icat edilmiş bir
    OTHER_MEDIA=0.60 değeri DEĞİL, `None` üretmeli."""
    _patch_requests(monkeypatch, _FakeResponse(_UNMAPPED_RSS.encode("utf-8")))

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=10)

    assert len(items) == 1
    assert items[0].source_reliability is None
    assert items[0].source_reliability != 0.60


def test_respects_limit(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(_SAMPLE_RSS.encode("utf-8")))

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=1)

    assert len(items) == 1


def test_returns_empty_list_on_request_failure(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(provider_module.requests, "get", _raise)

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=10)

    assert items == []


def test_returns_empty_list_on_malformed_xml(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(b"not xml"))

    items = GoogleNewsRssProvider(config_repo=_FakeConfigRepo()).get_latest_news("THYAO", limit=10)

    assert items == []
