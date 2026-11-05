"""Arşiv adaptörleri: mevcut proje haber sağlayıcılarını (Foreks RSS, Google News RSS, Yahoo News) AYNEN kullanır,
yalnız Firestore'a dokunan depoları yerel, yazmayan karşılıklarla değiştirir (üretim davranışı değişmez).

KAP: projede belgelenmiş resmi bir KAP uç noktası yok → `KapArchiveAdapter` yalnız sözleşmedir ve
`KAP_SOURCE_NOT_CONFIGURED` fırlatır. Uç nokta uydurulmaz, saldırgan kazıma yok.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.research.momentum_pilot.sources import NewsEventSource
from app.research.momentum_sources.common import raw_hash
from app.research.momentum_sources.news_archive.models import (NewsArchiveItem, _sha, classify_headline,
                                                               from_raw_item)

KAP_SOURCE_NOT_CONFIGURED = "KAP_SOURCE_NOT_CONFIGURED"
PER_SYMBOL_DELAY_SECONDS = 1.0


class KapSourceNotConfigured(RuntimeError):
    pass


class FeedUnavailable(RuntimeError):
    pass


class LocalConfigRepo:
    """`SystemConfigRepository` yerine: yalnız varsayılanları döndürür, Firestore'a OKUMAZ/YAZMAZ."""

    def get(self, config_id: str, defaults: dict) -> dict:
        return dict(defaults)


@dataclass(frozen=True)
class _Sym:
    symbol: str


class LocalAssetRepo:
    """`AssetRepository` yerine: sembol listesi çağırandan (ör. momentum evreni manifesti); Firestore yok."""

    def __init__(self, symbols: list[str]):
        self._symbols = sorted(set(symbols))

    def list_active(self) -> list[_Sym]:
        return [_Sym(s) for s in self._symbols]


class _RecordingRequests:
    """Sağlayıcının kendi `requests.get` çağrısını AYNEN geçirir; yalnız yanıt gövdesini gözlem için saklar."""

    def __init__(self, real):
        self._real = real
        self.content: bytes | None = None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def get(self, *a, **k):
        r = self._real.get(*a, **k)
        self.content = getattr(r, "content", None)
        self.received_at = datetime.now(timezone.utc)  # gerçek alım anı
        return r


def _rss_items(content: bytes | None):
    if not content:
        return None
    from xml.etree import ElementTree
    try:
        return ElementTree.fromstring(content).findall(".//channel/item")
    except ElementTree.ParseError:
        return None


def _rss_item_count(content: bytes | None) -> int | None:
    items = _rss_items(content)
    return None if items is None else len(items)


UNRESOLVED = "UNRESOLVED"


def foreks_item_key(fnp, link: str, guid: str) -> str:
    """Kalıcı öğe kimliği — üretim sağlayıcısının AYNI fonksiyonu (`_item_id`): eski `haber_id=`, güncel
    `/haber/detay/<id>/`, yoksa guid/bağlantı SHA-256'sı. Araştırma ve üretim aynı haberi aynı anahtarla tanır."""
    return f"foreks:{fnp._item_id(link, guid)}"


def parse_feed(fnp, prov, content: bytes, symbols: list[str], received_at: datetime, provider: str,
               semantics: str) -> list[NewsArchiveItem]:
    """Yakalanan TEK RSS yanıtındaki TÜM öğeler. Sembol eşlemesi sağlayıcının kendi kuralıyla (başlık + temizlenmiş
    açıklamada kelime sınırlı sembol kodu); eşlenemeyen öğe `UNRESOLVED` (sembol uydurulmaz). Ham arşiv eksiksiz
    olsun diye üretimdeki "neredeyse aynı haber" elemesi UYGULANMAZ. pubDate yoksa published_at None (UNVERIFIED)."""
    from email.utils import parsedate_to_datetime
    out = []
    for entry in _rss_items(content) or []:
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        guid = (entry.findtext("guid") or "").strip()
        if not title or not (link or guid):
            continue
        pub = None
        try:
            pub = parsedate_to_datetime(entry.findtext("pubDate")) if entry.findtext("pubDate") else None
            if pub is not None and pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pub = None
        desc = fnp._clean_html(entry.findtext("description"))
        ext = foreks_item_key(fnp, link, guid)
        payload = {"provider": provider, "external_id": ext, "title": title, "summary": desc, "url": link,
                   "publisher": fnp.PUBLISHER, "published_at": pub.isoformat() if pub else None}
        rh, ch = raw_hash(payload), _sha(f"{title}\n{desc}")
        for sym in prov._detect_related_assets(f"{title} {desc}", symbols) or [UNRESOLVED]:
            out.append(NewsArchiveItem(provider=provider, source=fnp.PUBLISHER, symbol=sym, company=None,
                                       published_at=pub, received_at=received_at, headline=title,
                                       event_type=classify_headline(title), event_importance=None,
                                       source_url_hash=_sha(link) if link else None, content_hash=ch, raw_hash=rh,
                                       published_at_semantics=semantics, item_key=ext))
    return out


class ForeksArchiveAdapter:
    provider = "foreks"
    semantics = "Foreks RSS pubDate (original Foreks publication time)"
    requests_per_run = 1

    def __init__(self, symbols: list[str], limit: int = 100, raw_dir=None):
        self.symbols, self.limit, self.raw_dir = symbols, limit, raw_dir
        self.last_stats: dict = {}

    def _save_raw(self, content: bytes) -> str:
        """Ham RSS yanıtı içerik adresli (sha256) gzip olarak; aynı yanıt tekrar yazılmaz."""
        import gzip
        import hashlib
        h = hashlib.sha256(content).hexdigest()
        if self.raw_dir is not None:
            path = self.raw_dir / h[:2] / f"{h}.xml.gz"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                with gzip.open(tmp, "wb") as f:
                    f.write(content)
                tmp.replace(path)
        return h

    def fetch(self) -> list[NewsArchiveItem]:
        from app.services.news import foreks_news_provider as fnp
        rec = _RecordingRequests(fnp.requests)
        prov = fnp.ForeksNewsProvider(asset_repo=LocalAssetRepo(self.symbols), config_repo=LocalConfigRepo())
        fnp.requests = rec  # yalnız bu süreçte, tek çağrı süresince; istek davranışı değişmez
        try:
            provider_items = prov.get_market_news(limit=self.limit)  # TEK RSS isteği (mevcut sağlayıcı)
        finally:
            fnp.requests = rec._real
        feed = _rss_item_count(rec.content)
        if feed is None:  # sağlayıcı ağ/ayrıştırma hatasını boş listeye çevirir; burada hata olarak yüzeye çıkar
            raise FeedUnavailable("FOREKS_FEED_UNAVAILABLE: no parsable RSS response")
        raw_sha = self._save_raw(rec.content)
        out = parse_feed(fnp, prov, rec.content, self.symbols, rec.received_at, self.provider, self.semantics)
        resolved = [a for a in out if a.symbol != UNRESOLVED]
        self.last_stats = {"rss_items_in_feed": feed, "items_received": len({a.item_key for a in out}),
                           "items_resolved_to_universe": len({a.item_key for a in resolved}),
                           "items_unresolved_or_near_duplicate": sum(a.symbol == UNRESOLVED for a in out),
                           "symbols_resolved": len({a.symbol for a in resolved}),
                           "symbols_resolved_list": sorted({a.symbol for a in resolved}),
                           "records_item_x_symbol": len(out),
                           "production_provider_items": len(provider_items),  # 0 ise üretim filtresi akışla uyumsuz
                           "raw_response_sha256": raw_sha}
        return out


class _PerSymbolAdapter:
    provider = ""
    semantics = ""

    def __init__(self, symbols: list[str], max_symbols: int, limit: int = 10, sleep=time.sleep):
        self.symbols = sorted(set(symbols))[:max_symbols]
        self.limit, self._sleep = limit, sleep

    @property
    def requests_per_run(self) -> int:
        return len(self.symbols)

    def _provider(self):
        raise NotImplementedError

    def fetch(self) -> list[NewsArchiveItem]:
        prov = self._provider()
        out = []
        for k, s in enumerate(self.symbols):
            if k:
                self._sleep(PER_SYMBOL_DELAY_SECONDS)  # nazik hız: sembol başına tek istek, aralıklı
            for it in prov.get_latest_news(s, limit=self.limit):
                out.extend(from_raw_item(it, self.provider, self.semantics))
        return out


class GoogleNewsArchiveAdapter(_PerSymbolAdapter):
    provider = "google_news"
    semantics = "Google News RSS pubDate (aggregator time; may reflect republication, not original disclosure)"

    def _provider(self):
        from app.services.news.google_news_rss_provider import GoogleNewsRssProvider
        return GoogleNewsRssProvider(config_repo=LocalConfigRepo())


class YahooNewsArchiveAdapter(_PerSymbolAdapter):
    provider = "yahoo_news"
    semantics = "Yahoo content pubDate (aggregator time)"

    def _provider(self):
        from app.services.news.yahoo_news_provider import YahooNewsProvider
        return YahooNewsProvider(config_repo=LocalConfigRepo())


class KapArchiveAdapter(NewsEventSource):
    """Resmi KAP kaynağı yapılandırılana dek yalnız sözleşme."""

    provider = "kap"
    status = KAP_SOURCE_NOT_CONFIGURED
    requests_per_run = 0

    def fetch(self) -> list[NewsArchiveItem]:
        raise KapSourceNotConfigured(KAP_SOURCE_NOT_CONFIGURED + ": no documented official KAP endpoint in project")

    def events(self, start: datetime, end: datetime, symbols: list[str] | None = None):
        raise KapSourceNotConfigured(KAP_SOURCE_NOT_CONFIGURED)
