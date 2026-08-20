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


def test_unknown_publisher_falls_back_to_other_media():
    assert classify_publisher("Bilinmeyen Site") == "OTHER_MEDIA"


def test_default_weights_cover_every_category_used_by_classify_publisher():
    categories = {"KAP", "NEWS_AGENCY", "FINANCIAL_MEDIA", "OTHER_MEDIA"}
    assert categories.issubset(DEFAULT_SOURCE_RELIABILITY.keys())
