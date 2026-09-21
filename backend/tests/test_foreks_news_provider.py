import requests

from app.models.asset import Asset
from app.services.news import foreks_news_provider as provider_module
from app.services.news.foreks_news_provider import ForeksNewsProvider

_RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>{title1}</title>
  <link>https://www.foreks.com/haber/detay/thyao-haberi-24-08-26?haber_id=abc123&amp;lang=tr&amp;category=PICNEWS</link>
  <pubDate>Mon, 24 Aug 2026 12:00:00 +0000</pubDate>
  <description><![CDATA[<p>THYAO hisseleri icin analistler hedef fiyati yukseltti.</p>]]></description>
</item>
<item>
  <title>{title2}</title>
  <link>https://www.foreks.com/haber/detay/thyao-haberi-tekrar-24-08-26?haber_id=def456&amp;lang=tr&amp;category=PICNEWS</link>
  <pubDate>Mon, 24 Aug 2026 11:00:00 +0000</pubDate>
  <description><![CDATA[<p>THYAO hisseleri icin analistler hedef fiyati yukseltti.</p>]]></description>
</item>
<item>
  <title>Fed faiz kararini acikladi</title>
  <link>https://www.foreks.com/haber/detay/fed-faiz-24-08-26?haber_id=fed789a&amp;lang=tr&amp;category=PICNEWS</link>
  <pubDate>Mon, 24 Aug 2026 10:00:00 +0000</pubDate>
  <description><![CDATA[<p>Bilinen bir BIST sembolu gecmiyor.</p>]]></description>
</item>
<item>
  <title>Tarihi olmayan haber</title>
  <link>https://www.foreks.com/haber/detay/tarihsiz-24-08-26?haber_id=jkl012&amp;lang=tr&amp;category=PICNEWS</link>
  <description>pubDate eksik, atlanmalı</description>
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


class _FakeAssetRepo:
    def list_active(self):
        return [
            Asset(symbol="THYAO", name="Türk Hava Yolları", market="BIST", asset_type="STOCK", currency="TRY"),
            Asset(symbol="GARAN", name="Garanti BBVA", market="BIST", asset_type="STOCK", currency="TRY"),
        ]


def _patch_requests(monkeypatch, response):
    monkeypatch.setattr(provider_module.requests, "get", lambda *_a, **_kw: response)


def _provider():
    return ForeksNewsProvider(asset_repo=_FakeAssetRepo(), config_repo=_FakeConfigRepo())


def test_detects_related_bist_asset_from_ticker_mention(monkeypatch):
    rss = _RSS_TEMPLATE.format(
        title1="THYAO'da hedef fiyat yukseltildi", title2="Tamamen farkli bir THYAO baslik metni burada"
    )
    _patch_requests(monkeypatch, _FakeResponse(rss.encode("utf-8")))

    items = _provider().get_market_news(limit=10)

    thyao_items = [i for i in items if "THYAO" in i.related_assets]
    assert len(thyao_items) == 2  # başlıkları yeterince farklı, ikisi de tutulur
    item = next(i for i in thyao_items if i.external_id == "foreks:abc123")
    assert item.source == "foreks"
    assert item.publisher == "Foreks"
    assert item.source_reliability == 0.80  # FINANCIAL_MEDIA
    assert "analistler hedef fiyati yukseltti" in item.summary


def test_fixed_publisher_is_a_known_category_not_a_fake_fallback(monkeypatch):
    """HATA 15C SON DÜZELTME: Foreks'in sabit PUBLISHER'ı ("Foreks") gerçekten
    bilinen bir kategoriye (FINANCIAL_MEDIA) eşleşir -- bu, eşleşmeyen bir
    yayıncı için icat edilmiş bir OTHER_MEDIA fallback DEĞİL, gerçek
    sınıflandırma bilgisidir. Foreks sağlayıcısı kendi başına eski
    OTHER_MEDIA=0.60 fallback'ını yeniden üretemez."""
    from app.services.news.source_reliability import classify_publisher

    assert classify_publisher(provider_module.PUBLISHER) == "FINANCIAL_MEDIA"

    rss = _RSS_TEMPLATE.format(title1="THYAO'da hedef fiyat yukseltildi", title2="Baska bir THYAO haberi")
    _patch_requests(monkeypatch, _FakeResponse(rss.encode("utf-8")))

    items = _provider().get_market_news(limit=10)

    assert all(i.source_reliability == 0.80 for i in items)
    assert all(i.source_reliability is not None for i in items)


def test_skips_items_with_no_known_bist_asset_mentioned(monkeypatch):
    rss = _RSS_TEMPLATE.format(title1="THYAO'da hedef fiyat yukseltildi", title2="Baska bir THYAO haberi")
    _patch_requests(monkeypatch, _FakeResponse(rss.encode("utf-8")))

    items = _provider().get_market_news(limit=10)

    assert all("Fed faiz kararini acikladi" != i.title for i in items)


def test_skips_items_missing_pub_date(monkeypatch):
    rss = _RSS_TEMPLATE.format(title1="THYAO'da hedef fiyat yukseltildi", title2="Baska bir THYAO haberi")
    _patch_requests(monkeypatch, _FakeResponse(rss.encode("utf-8")))

    items = _provider().get_market_news(limit=10)

    assert all("Tarihi olmayan haber" != i.title for i in items)


def test_near_duplicate_titles_for_same_asset_are_deduplicated(monkeypatch):
    rss = _RSS_TEMPLATE.format(
        title1="THYAO hisseleri icin hedef fiyat yukseltildi aciklamasi geldi",
        title2="THYAO hisseleri icin hedef fiyat yukseltildi aciklamasi geldi bugun",
    )
    _patch_requests(monkeypatch, _FakeResponse(rss.encode("utf-8")))

    items = _provider().get_market_news(limit=10)

    assert len([i for i in items if "THYAO" in i.related_assets]) == 1


def test_returns_empty_list_on_request_failure(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(provider_module.requests, "get", _raise)

    items = _provider().get_market_news(limit=10)

    assert items == []


def test_returns_empty_list_on_malformed_xml(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(b"not xml"))

    items = _provider().get_market_news(limit=10)

    assert items == []
