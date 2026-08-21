import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from app.models.ipo import IpoDetail, IpoListing

# halkarz.com'dan (veya ara katmandaki bir proxy/CDN'den) ara sıra tek başına
# geçersiz surrogate karakterler (ör. "A.Ş." içindeki Ş) gelebildiği canlı
# testte görüldü — bunlar geçerli UTF-8'e dönüştürülemez ve istemci tarafında
# (Flutter'ın kesin UTF-8 JSON çözücüsü) çökmeye yol açar. Savunma amaçlı:
# gönderilmeden önce her zaman temizlenir.
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")

# AŞAMA 67: kullanıcı isteği "halka arz sayfası oluştur, hangisine girmeliyim,
# ne kadar bütçeyle... internette araştırma yapıp bana girmem gereken fiyatı
# gir." Kesin bir "AL/GİRME" tavsiyesi ÜRETİLMEZ (kullanıcı onayladı) —
# yalnızca GERÇEK, halkarz.com'dan (statik HTML, robots.txt izin veriyor,
# canlı test edildi) çekilen halka arz takvimi/fiyat/tarih bilgisi olduğu
# gibi gösterilir, kararı kullanıcı verir.
BASE_URL = "https://halkarz.com/"
REQUEST_TIMEOUT_SECONDS = 10
_USER_AGENT = "Mozilla/5.0 (compatible; AIYatirimApp/1.0)"


def _clean(text: str | None) -> str:
    stripped = _LONE_SURROGATE_RE.sub("", text or "")
    return " ".join(stripped.split())


def parse_listing_page(html: str) -> list[IpoListing]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("ul", class_="halka-arz-list")
    if container is None:
        return []

    listings: list[IpoListing] = []
    for li in container.find_all("li", recursive=False):
        article = li.find("article", class_="index-list")
        if article is None:
            continue
        name_tag = article.select_one(".il-halka-arz-sirket a")
        if name_tag is None:
            continue
        company_name = _clean(name_tag.get_text())
        detail_url = name_tag.get("href", "")
        if not company_name or not detail_url:
            continue

        code_tag = article.select_one(".il-bist-kod")
        bist_code = _clean(code_tag.get_text()) if code_tag else ""

        time_tag = article.select_one(".il-halka-arz-tarihi time")
        date_text = _clean(time_tag.get_text()) if time_tag else ""

        badge_tag = article.select_one(".il-badge")
        badge_text = _clean(badge_tag.get_text()) if badge_tag else ""

        listings.append(
            IpoListing(
                company_name=company_name,
                bist_code=bist_code or None,
                detail_url=detail_url,
                date_text=date_text,
                badge_text=badge_text or None,
            )
        )
    return listings


def parse_detail_page(html: str, now: datetime | None = None) -> IpoDetail | None:
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one("article.index-list.detail-page .il-content")
    if header is None:
        return None
    name_tag = header.select_one(".il-halka-arz-sirket")
    company_name = _clean(name_tag.get_text()) if name_tag else ""
    if not company_name:
        return None
    code_tag = header.select_one(".il-bist-kod")
    bist_code = _clean(code_tag.get_text()) if code_tag else ""

    fields: dict[str, str] = {}
    table = soup.select_one("table.sp-table")
    if table is not None:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue
            key = _clean(cells[0].get_text()).rstrip(" :").strip()
            value = _clean(cells[1].get_text())
            if key and value:
                fields[key] = value

    demand_results: list[dict[str, str]] = []
    results_table = soup.select_one("table.as-table")
    if results_table is not None:
        for row in results_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 4:
                continue
            demand_results.append(
                {
                    "grup": _clean(cells[0].get_text()),
                    "kisi": _clean(cells[1].get_text()),
                    "lot": _clean(cells[2].get_text()),
                    "oran": _clean(cells[3].get_text()),
                }
            )

    return IpoDetail(
        company_name=company_name,
        bist_code=bist_code or None,
        fields=fields,
        demand_results=demand_results,
        fetched_at=now or datetime.now(timezone.utc),
    )


class HalkArzProvider:
    def get_listings(self) -> list[IpoListing]:
        response = requests.get(BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        return parse_listing_page(response.text)

    def get_detail(self, detail_url: str) -> IpoDetail | None:
        if not detail_url.startswith(BASE_URL):
            raise ValueError("Yalnızca halkarz.com detay linkleri desteklenir")
        response = requests.get(detail_url, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        return parse_detail_page(response.text)
