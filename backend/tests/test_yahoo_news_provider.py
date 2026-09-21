"""HATA 15C SON DÜZELTME: YahooNewsProvider, eşleşmeyen/eksik bir yayıncı
için icat edilmiş bir OTHER_MEDIA=0.60 değeri ÜRETMEMELİ -- bkz.
source_reliability.py::classify_publisher (artık eşleşmeyince `None` döner).
"""

from datetime import datetime, timezone

from app.services.news import yahoo_news_provider as provider_module
from app.services.news.yahoo_news_provider import YahooNewsProvider


class _FakeConfigRepo:
    def get(self, _key, default):
        return default


class _FakeTicker:
    def __init__(self, items):
        self.news = items

    def __call__(self, *_a, **_kw):
        return self


def _raw_item(item_id, publisher, title="Başlık"):
    return {
        "id": item_id,
        "content": {
            "title": title,
            "summary": "özet",
            "provider": {"displayName": publisher} if publisher is not None else {},
            "canonicalUrl": {"url": f"https://example.com/{item_id}"},
            "pubDate": "2026-08-24T12:00:00Z",
        },
    }


def _patch_ticker(monkeypatch, news_items):
    fake = _FakeTicker(news_items)
    monkeypatch.setattr(provider_module.yf, "Ticker", lambda *_a, **_kw: fake)


def _provider():
    return YahooNewsProvider(config_repo=_FakeConfigRepo())


def test_known_publisher_gets_configured_reliability(monkeypatch):
    _patch_ticker(monkeypatch, [_raw_item("1", "Reuters")])

    items = _provider().get_latest_news("THYAO")

    assert items[0].publisher == "Reuters"
    assert items[0].source_reliability == 0.90  # NEWS_AGENCY


def test_unmapped_publisher_does_not_become_fake_other_media(monkeypatch):
    _patch_ticker(monkeypatch, [_raw_item("1", "Completely Unmapped Publisher")])

    items = _provider().get_latest_news("THYAO")

    assert items[0].source_reliability is None
    assert items[0].source_reliability != 0.60


def test_missing_publisher_does_not_become_fake_other_media(monkeypatch):
    _patch_ticker(monkeypatch, [_raw_item("1", None)])

    items = _provider().get_latest_news("THYAO")

    assert items[0].publisher == "Unknown"
    assert items[0].source_reliability is None
