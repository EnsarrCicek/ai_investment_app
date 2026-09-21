"""Yayıncı adından kaynak güvenilirlik kategorisine eşleme (ana doküman bölüm 7).

Ağırlıkların sayısal değerleri her zaman system_config'ten okunur (bkz.
get_latest_news çağıranları); burada yalnızca hangi kategoriye girdiğinin
sınıflandırması var — hem Yahoo hem Google News sağlayıcıları bu modülü
paylaşır, iki yerde ayrı ayrı tanımlanmaz.
"""

DEFAULT_SOURCE_RELIABILITY = {
    "OFFICIAL_INSTITUTION": 1.00,
    "KAP": 1.00,
    "CENTRAL_BANK": 0.98,
    "GOVERNMENT": 0.95,
    "NEWS_AGENCY": 0.90,
    "FINANCIAL_MEDIA": 0.80,
    "OTHER_MEDIA": 0.60,
    "SOCIAL_MEDIA": 0.30,
}

_PUBLISHER_CATEGORY = {
    "reuters": "NEWS_AGENCY",
    "associated press": "NEWS_AGENCY",
    "anadolu ajansı": "NEWS_AGENCY",
    "aa.com": "NEWS_AGENCY",
    "hibya": "NEWS_AGENCY",
    "bloomberg": "FINANCIAL_MEDIA",
    "bloomberght": "FINANCIAL_MEDIA",
    "mt newswires": "FINANCIAL_MEDIA",
    "motley fool": "FINANCIAL_MEDIA",
    "investor's business daily": "FINANCIAL_MEDIA",
    "barrons": "FINANCIAL_MEDIA",
    "mynet": "FINANCIAL_MEDIA",
    "foreks": "FINANCIAL_MEDIA",
    "investing.com": "FINANCIAL_MEDIA",
    "cnbc": "FINANCIAL_MEDIA",
    "bigpara": "FINANCIAL_MEDIA",
    "paratic": "FINANCIAL_MEDIA",
    "para ajansı": "FINANCIAL_MEDIA",
    "para ajansi": "FINANCIAL_MEDIA",
    "rota borsa": "FINANCIAL_MEDIA",
    "ekonomim": "FINANCIAL_MEDIA",
    "dünya": "FINANCIAL_MEDIA",
    "dunya": "FINANCIAL_MEDIA",
}


def classify_publisher(publisher: str | None) -> str | None:
    """Yayıncıyı bilinen bir kategoriye eşler; eşleşme yoksa `None` döner.

    HATA 15C SON DÜZELTME: `OTHER_MEDIA`, eşleşmeyen/bilinmeyen bir yayıncı
    için icat edilmiş bir varsayılan DEĞİL -- şu anda kod tabanında hiçbir
    yayıncıyı BİLEREK OTHER_MEDIA'ya eşleyen açık bir kural yok
    (`_PUBLISHER_CATEGORY` yalnızca KAP/NEWS_AGENCY/FINANCIAL_MEDIA
    kategorilerini tanır). Eşleşmeyen/boş/`None` bir yayıncı, sayısal bir
    güvenilirlik değeri TAŞIMAYAN `None` döner -- çağıran taraf bunu
    "bilinmiyor" olarak ele almalı, asla `OTHER_MEDIA=0.60` gibi icat
    edilmiş bir değere düşürmemeli (bkz. `decision/engine.py::_effective_news_weight`,
    "available-dimension weighting").
    """
    if not publisher or not publisher.strip():
        return None
    name = publisher.strip().lower()
    if name == "kap" or name.startswith("kap "):
        return "KAP"
    for key, category in _PUBLISHER_CATEGORY.items():
        if key in name:
            return category
    return None
