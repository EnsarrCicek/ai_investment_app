import re

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT_SECONDS = 8
DEFAULT_MAX_CHARS = 4000
MIN_PARAGRAPH_CHARS = 40
_USER_AGENT = "Mozilla/5.0 (compatible; AIYatirimApp/1.0)"

# news.google.com/rss/articles/... bir SPA kabuğu döner; gerçek yönlendirme
# istemci tarafı JS ile (Google'ın iç batchexecute API'si üzerinden) çözülüyor
# ve bunu sunucu tarafında GÜVENİLİR şekilde çözecek resmi bir yol yok — bu
# yüzden bu host için hiç istek ATILMAZ (boşuna ağ çağrısı + SPA kabuğunu
# "içerik" sanma riski). Gerçek makale, kullanıcı linke dokunduğunda tarayıcıda
# (JS çalıştığı için) doğru şekilde açılır — bkz. Flutter tarafındaki url_launcher.
_UNFETCHABLE_HOSTS = ("news.google.com",)


def fetch_article_text(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Bir haber makalesinin GERÇEK gövde metnini iyi niyetli (best-effort)
    şekilde çeker. Bu, AI analizine (EventIntelligenceEngine) yalnızca başlık
    değil gerçek içerik verebilmek için kullanılır — kullanıcı isteği: "haberin
    detayı verilmediği için kesin bir yargıya varılamıyor" sorununu çözer.

    Herhangi bir ağ/parse hatasında (zaman aşımı, 4xx/5xx, bilinmeyen yapı)
    sessizce boş string döner — çağıran (engine) bu durumda yalnızca başlığa
    dayanarak analiz yapmaya devam eder, hiçbir şey uydurulmaz.
    """
    if not url or any(host in url for host in _UNFETCHABLE_HOSTS):
        return ""

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
    except requests.RequestException:
        return ""

    try:
        soup = BeautifulSoup(response.content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = " ".join(p for p in paragraphs if len(p) >= MIN_PARAGRAPH_CHARS)
        text = re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""

    return text[:max_chars]
