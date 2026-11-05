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


_CURRENT_ITEM = """<item>
  <title>{title}</title>
  <link>{link}</link>
  <guid>{guid}</guid>
  <pubDate>{pub}</pubDate>
  <description><![CDATA[<img alt="x" src="https://news.example/img.jpg"/><p>{desc}</p>]]></description>
</item>"""


def _feed(*items: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>' + "".join(items)
            + "</channel></rss>").encode("utf-8")


def _current(i: int, title: str, desc: str = "", pub: str = "Wed, 04 Nov 2026 07:56:58 +0000") -> str:
    oid = f"6aeae54a95131d72027d{i:04x}"
    url = f"https://www.foreks.com/haber/detay/{oid}/PICNEWS/tr/slug-{i}"
    return _CURRENT_ITEM.format(title=title, link=url, guid=url, pub=pub, desc=desc)


def test_item_id_precedence_and_deterministic_fallback():
    assert provider_module._item_id("https://x/haber/detay/s?haber_id=abc123&lang=tr", "") == "abc123"
    cur = "https://www.foreks.com/haber/detay/6aeae54a95131d72027d620e/PICNEWS/tr/petrol"
    assert provider_module._item_id(cur, cur) == "6aeae54a95131d72027d620e"
    both = "https://www.foreks.com/haber/detay/6aeae54a95131d72027d620e/PICNEWS?haber_id=abc123"
    assert provider_module._item_id(both, "") == "abc123"  # eski biçim önce
    a = provider_module._item_id("https://www.foreks.com/x/y", "g-1")
    assert a == provider_module._item_id("https://www.foreks.com/x/y", "g-1") and a.startswith("guid-")
    assert a != provider_module._item_id("https://www.foreks.com/x/y", "g-2")
    assert "/" not in a  # Firestore doküman kimliği güvenli
    assert provider_module._item_id("https://www.foreks.com/haber/detay/kisa-slug/x", "").startswith("guid-")


def test_current_link_format_is_parsed(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(_feed(_current(1, "GARAN yeni kredi paketi", "GARAN"))))

    items = _provider().get_market_news(limit=10)

    assert [(i.external_id, i.related_assets) for i in items] == [("foreks:6aeae54a95131d72027d0001", ["GARAN"])]
    assert items[0].url.startswith("https://www.foreks.com/haber/detay/6aeae54a95131d72027d0001/")
    assert items[0].published_at.isoformat() == "2026-11-04T07:56:58+00:00"  # pubDate aynen


def test_current_feed_of_100_items_does_not_collapse_to_zero(monkeypatch):
    feed = [_current(k, f"Genel piyasa haberi numara {k} benzersiz baslik {k * 7}") for k in range(97)]
    feed += [_current(100, "THYAO yolcu sayısını açıkladı"), _current(101, "Bankacılıkta GARAN öne çıktı"),
             _current(102, "Enerji hisseleri", "Gün içinde THYAO ve GARAN ayrıştı")]
    _patch_requests(monkeypatch, _FakeResponse(_feed(*feed)))

    items = _provider().get_market_news(limit=100)

    assert len(items) == 3  # sembolsüz 97 öğe üretim kuralıyla atlanır; haber_id yokluğu tek başına sıfıra düşürmez
    assert {tuple(i.related_assets) for i in items} == {("THYAO",), ("GARAN",), ("THYAO", "GARAN")}


def test_same_underlying_id_in_legacy_and_current_form_emitted_once(monkeypatch):
    legacy = _CURRENT_ITEM.format(title="THYAO hedef fiyat", desc="THYAO",
                                  link="https://www.foreks.com/haber/detay/thyao?haber_id=6aeae54a95131d72027d620e",
                                  guid="", pub="Wed, 04 Nov 2026 07:00:00 +0000")
    current = _CURRENT_ITEM.format(title="THYAO icin tamamen baska kelimeler iceren bir baslik", desc="THYAO",
                                   link="https://www.foreks.com/haber/detay/6aeae54a95131d72027d620e/PICNEWS/tr/s",
                                   guid="", pub="Wed, 04 Nov 2026 07:00:00 +0000")
    _patch_requests(monkeypatch, _FakeResponse(_feed(legacy, current)))

    items = _provider().get_market_news(limit=10)

    assert [i.external_id for i in items] == ["foreks:6aeae54a95131d72027d620e"]


def test_malformed_link_uses_deterministic_fallback_or_is_skipped(monkeypatch):
    weird = _CURRENT_ITEM.format(title="ASELS yeni ihale", desc="ASELS", link="https://www.foreks.com/odd",
                                 guid="foreks-guid-77", pub="Wed, 04 Nov 2026 07:00:00 +0000")
    nolink = _CURRENT_ITEM.format(title="ASELS linksiz", desc="ASELS", link="", guid="g",
                                  pub="Wed, 04 Nov 2026 07:00:00 +0000")

    class _Repo:
        def list_active(self):
            return [Asset(symbol="ASELS", name="Aselsan", market="BIST", asset_type="STOCK", currency="TRY")]
    _patch_requests(monkeypatch, _FakeResponse(_feed(weird, nolink)))

    a = ForeksNewsProvider(asset_repo=_Repo(), config_repo=_FakeConfigRepo()).get_market_news(limit=10)
    b = ForeksNewsProvider(asset_repo=_Repo(), config_repo=_FakeConfigRepo()).get_market_news(limit=10)

    assert [i.external_id for i in a] == [i.external_id for i in b] and len(a) == 1  # link yoksa eskisi gibi atlanır
    assert a[0].external_id.startswith("foreks:guid-")


def test_near_duplicate_filtering_unchanged_for_current_format(monkeypatch):
    _patch_requests(monkeypatch, _FakeResponse(_feed(
        _current(1, "THYAO hisseleri icin hedef fiyat yukseltildi aciklamasi geldi"),
        _current(2, "THYAO hisseleri icin hedef fiyat yukseltildi aciklamasi geldi bugun"))))

    items = _provider().get_market_news(limit=10)

    assert [i.external_id for i in items] == ["foreks:6aeae54a95131d72027d0001"]


def test_provider_unit_uses_no_firestore(monkeypatch):
    import app.core.firebase as fb
    monkeypatch.setattr(fb, "get_firestore_client", lambda: (_ for _ in ()).throw(AssertionError("Firestore!")))
    _patch_requests(monkeypatch, _FakeResponse(_feed(_current(1, "GARAN haberi", "GARAN"))))

    assert len(_provider().get_market_news(limit=10)) == 1


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
