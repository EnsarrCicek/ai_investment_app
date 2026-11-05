import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from app.models.news_raw import NewsRawItem
from app.repositories.asset_repository import AssetRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.services.news.firm_extraction import extract_analyst_firm
from app.services.news.source_reliability import DEFAULT_SOURCE_RELIABILITY, classify_publisher

# Kullanıcı isteği: "Foreks Borsa Haberleri kaynağını ekle
# (https://www.foreks.com/borsa/borsa-haberleri/)". Önce API/RSS/JSON arandı:
# /robots.txt "/api/" yolunu Disallow ediyor ama "/rss"yi kendi llms.txt
# dokümanında resmi makine-okunur uç nokta olarak listeliyor ("Son haberlerin
# RSS 2.0 formatında akışı") — canlı test edildi, çalışıyor. Ayrıca
# /borsa/borsa-haberleri/ sayfasındaki TÜM haberlerin bu genel RSS akışında da
# (aynı haber_id ile) yer aldığı doğrulandı — yani "Borsa Haberleri" bölümü bu
# akışın BIST'e değen bir alt kümesi; ayrı bir kırılgan HTML scraping yerine
# bu resmi akış kullanılıp, hangi haberlerin BIST'e değdiği kendi
# tespitimizle (bilinen sembol kodlarının metinde geçmesi) belirleniyor.
RSS_URL = "https://www.foreks.com/rss"
REQUEST_TIMEOUT_SECONDS = 10
_USER_AGENT = "Mozilla/5.0 (compatible; AIYatirimApp/1.0)"

SOURCE = "foreks"
PUBLISHER = "Foreks"

_HABER_ID_RE = re.compile(r"haber_id=([0-9a-f]+)")
# Güncel Foreks RSS bağlantı biçimi (2026-11'de gözlendi): `/haber/detay/<24 haneli hex kimlik>/<kategori>/...`
# — `haber_id=` artık yok. Eski biçim (`/haber/detay/<slug>?haber_id=<id>`) desteklenmeye devam eder.
_DETAIL_ID_RE = re.compile(r"/haber/detay/([0-9a-f]{16,})(?:[/?#]|$)")


def _item_id(link: str, guid: str) -> str:
    """Kalıcı öğe kimliği (Firestore doküman kimliği olarak kullanılır; `/` içermez). Öncelik:
    1) eski `haber_id=<id>`  2) güncel `/haber/detay/<id>/`  3) guid (yoksa bağlantı) SHA-256'sı (deterministik).
    Not: eski ve güncel biçimin aynı kimlik uzayını paylaştığı doğrulanmadı; aynı kimlik görülürse aynı haber
    sayılır (ör. `foreks:<id>`), farklı kimlikler farklı haber kalır."""
    for rx in (_HABER_ID_RE, _DETAIL_ID_RE):
        for text in (link, guid):
            m = rx.search(text)
            if m:
                return m.group(1)
    return "guid-" + hashlib.sha256((guid or link).encode("utf-8")).hexdigest()[:24]

# İki haberin "aynı olayın neredeyse birebir tekrarı" sayılması için gereken
# başlık kelime-kümesi benzerliği (Jaccard). Aynı sembol için art arda gelen,
# neredeyse aynı başlıklı (ör. bir ajansın haberinin küçük düzenlemeyle
# yeniden yayınlanması) haberleri eleyerek sonraki EventIntelligenceEngine
# analizinde gereksiz LLM/token harcamasını önler.
_NEAR_DUPLICATE_THRESHOLD = 0.82

_WORD_RE = re.compile(r"[a-zçğıöşü0-9]+")


def _title_tokens(title: str) -> set[str]:
    return set(_WORD_RE.findall(title.lower()))


def _is_near_duplicate(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    union = len(a | b)
    if union == 0:
        return False
    return (len(a & b) / union) >= _NEAR_DUPLICATE_THRESHOLD


def _clean_html(text: str | None) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


class ForeksNewsProvider:
    """foreks.com'un resmi RSS akışı üzerinden genel piyasa haberi adaptörü.

    Diğer sağlayıcılardan farkı: `NewsProvider` arayüzü (`get_latest_news(symbol)`)
    TEK bir varlık için sorgu yapmaya göre tasarlanmış, ama Foreks akışı GENEL bir
    haber listesi döndürüyor (bir haberde birden çok BIST hissesi geçebilir). Bu
    yüzden `HalkArzProvider` ile aynı desende, kendi bağımsız arayüzüyle
    (`get_market_news`) ayrı bir sınıf olarak tanımlandı.
    """

    def __init__(
        self,
        asset_repo: AssetRepository | None = None,
        config_repo: SystemConfigRepository | None = None,
    ):
        self._asset_repo = asset_repo or AssetRepository()
        self._config_repo = config_repo or SystemConfigRepository()

    def _known_symbols(self) -> list[str]:
        return [a.symbol for a in self._asset_repo.list_active()]

    def _detect_related_assets(self, text: str, symbols: list[str]) -> list[str]:
        """Bilinen BIST sembol kodlarının haber metninde GEÇTİĞİ durumları
        tespit eder (kelime sınırı ile) — `firm_extraction.py`deki analist
        kurumu tespitiyle AYNI ilke: hiçbir varlık UYDURULMAZ, yalnızca gerçek
        metinde geçen sembol kodları eşleştirilir.
        """
        found: list[str] = []
        for symbol in symbols:
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                found.append(symbol)
        return found

    def get_market_news(self, limit: int = 100) -> list[NewsRawItem]:
        try:
            response = requests.get(RSS_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (requests.RequestException, ElementTree.ParseError):
            return []

        symbols = self._known_symbols()
        if not symbols:
            return []

        weights = self._config_repo.get("source_reliability", DEFAULT_SOURCE_RELIABILITY)
        _foreks_category = classify_publisher(PUBLISHER)
        reliability = weights.get(_foreks_category) if _foreks_category is not None else None
        received_at = datetime.now(timezone.utc)

        # Sembol başına daha önce eklenmiş haberlerin kelime kümeleri — neredeyse
        # aynı haberi (bkz. modül docstring'i) elemek için.
        kept_tokens_by_symbol: dict[str, list[set[str]]] = {}
        seen_ids: set[str] = set()

        items: list[NewsRawItem] = []
        for entry in root.findall(".//channel/item")[:limit]:
            title = (entry.findtext("title") or "").strip()
            link = (entry.findtext("link") or "").strip()
            guid = (entry.findtext("guid") or "").strip()
            pub_date_text = entry.findtext("pubDate")
            description = _clean_html(entry.findtext("description"))

            if not title or not link or not pub_date_text:
                continue
            external_id = f"foreks:{_item_id(link, guid)}"

            try:
                published_at = parsedate_to_datetime(pub_date_text)
            except (TypeError, ValueError):
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)

            related_assets = self._detect_related_assets(f"{title} {description}", symbols)
            if not related_assets:
                continue  # Bu haber bilinen hiçbir BIST varlığına değinmiyor — atla.
            if external_id in seen_ids:
                continue  # aynı yanıtta aynı haber (ör. eski + güncel bağlantıyla) iki kez üretilmez
            seen_ids.add(external_id)

            tokens = _title_tokens(title)
            is_duplicate = False
            for symbol in related_assets:
                for seen in kept_tokens_by_symbol.get(symbol, []):
                    if _is_near_duplicate(tokens, seen):
                        is_duplicate = True
                        break
                if is_duplicate:
                    break
            if is_duplicate:
                continue

            for symbol in related_assets:
                kept_tokens_by_symbol.setdefault(symbol, []).append(tokens)

            items.append(
                NewsRawItem(
                    external_id=external_id,
                    title=title,
                    summary=description,
                    url=link,
                    publisher=PUBLISHER,
                    source=SOURCE,
                    source_reliability=reliability,
                    related_assets=related_assets,
                    published_at=published_at,
                    received_at=received_at,
                    analyst_firm=extract_analyst_firm(f"{title} {description}"),
                )
            )
            items[-1].is_analyst_mention = items[-1].analyst_firm is not None

        return items
