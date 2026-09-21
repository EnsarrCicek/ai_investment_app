from app.services.news.source_reliability import DEFAULT_SOURCE_RELIABILITY, classify_publisher


def test_classifies_kap_as_official_source():
    assert classify_publisher("KAP") == "KAP"
    assert classify_publisher("kap") == "KAP"


def test_classifies_known_news_agency():
    assert classify_publisher("Reuters") == "NEWS_AGENCY"
    assert classify_publisher("Anadolu Ajansı") == "NEWS_AGENCY"


def test_classifies_known_turkish_financial_media():
    assert classify_publisher("Mynet Finans") == "FINANCIAL_MEDIA"
    assert classify_publisher("Bloomberght") == "FINANCIAL_MEDIA"
    assert classify_publisher("Foreks.com") == "FINANCIAL_MEDIA"


def test_unknown_publisher_returns_none_not_fake_other_media():
    """HATA 15C SON DÜZELTME: eşleşmeyen bir yayıncı artık icat edilmiş bir
    OTHER_MEDIA=0.60 değeri DEĞİL, `None` döner -- çağıran taraf bunu
    "reliability bilinmiyor" olarak ele almalı (bkz. decision/engine.py::
    _effective_news_weight, available-dimension weighting)."""
    assert classify_publisher("Bilinmeyen Site") is None


def test_missing_or_empty_publisher_returns_none():
    assert classify_publisher(None) is None
    assert classify_publisher("") is None
    assert classify_publisher("   ") is None


def test_no_explicit_rule_currently_classifies_a_publisher_as_other_media():
    """Kod tabanında şu anda hiçbir yayıncıyı BİLEREK OTHER_MEDIA'ya eşleyen
    açık bir kural yok -- `_PUBLISHER_CATEGORY` yalnızca KAP/NEWS_AGENCY/
    FINANCIAL_MEDIA tanır. Bu nedenle "bilinen OTHER_MEDIA" ile "tarihsel
    fallback" şu an ayırt edilemez; bkz. HATA 15C SON DÜZELTME final raporu
    bölüm 12."""
    from app.services.news.source_reliability import _PUBLISHER_CATEGORY

    assert "OTHER_MEDIA" not in _PUBLISHER_CATEGORY.values()


def test_default_weights_cover_every_category_used_by_classify_publisher():
    categories = {"KAP", "NEWS_AGENCY", "FINANCIAL_MEDIA"}
    assert categories.issubset(DEFAULT_SOURCE_RELIABILITY.keys())
