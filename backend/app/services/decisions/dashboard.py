"""Toplu dashboard kararları — `GET /decisions/dashboard`.

Önce: Dashboard her açılışta `GET /assets` + varlık başına `GET /decisions/{symbol}` (~100) çağırıyordu. Her karar
çağrısı ortak config'i, makro snapshot'ı ve benchmark'ı YENİDEN okuyor, o varlığın TÜM teknik analiz ve TÜM haber
analizi geçmişini tarıyor, ham haber kayıtlarını analiz başına iki kez okuyor, `ai_decisions`'a bir kayıt
(ve cache kaçışında `technical_analyses`'a bir kayıt) YAZIYOR ve kullanıcı portföyü/bildirim kontrollerini
çalıştırıyordu.

Burada AYNI `DecisionEngine.decide_for_asset` ve `TechnicalAnalysisEngine` kullanılır (skor/karar mantığı
değişmez); yalnız bağımlılıklar istek ölçeğinde paylaşılır:
* config (`get_raw`): istek başına anahtar başına 1 okuma,
* makro snapshot: istek başına 1 okuma,
* benchmark cache: istek başına en çok 1 okuma; yeniden çekilirse sonuç yalnız bu istekte tutulur (YAZILMAZ),
* teknik analiz cache: tek aralık sorgusu (`created_at >= şimdi − TTL − pay`). Cache yalnız TTL içindeki kayıtla
  isabet edebildiğinden, daha eski kayıtları okumamak cache kararını değiştirmez,
* haber: süreç içi önbellek (bkz. `NewsReadCache`), geçerlilik anahtarı koleksiyon sayımı (1 aggregation okuması),
* kararlar `persist=False` ile üretilir: dashboard hiçbir koleksiyona YAZMAZ (ai_decisions, technical_analyses,
  benchmark cache, bildirim kayıtları),
* kullanıcı portföyü okunmaz, bildirim tetiklenmez (bunlar günlük job ve tekil karar uç noktasında kalır).

Kota hatası (`ResourceExhausted`): üretimde yükselir → 503. Yalnız yerel LAN modunda satırlar
`UNAVAILABLE / FIRESTORE_QUOTA_EXHAUSTED` olarak döner; hiçbir skor/karar uydurulmaz.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Callable

from google.api_core.exceptions import ResourceExhausted

from app.core.firestore_errors import FIRESTORE_QUOTA_EXHAUSTED
from app.core.local_dev import local_lan_dev_enabled
from app.engines.decision.engine import DecisionEngine
from app.engines.technical.engine import TECHNICAL_CACHE_TTL_SECONDS, TechnicalAnalysisEngine

logger = logging.getLogger(__name__)

MODE_NORMAL = "NORMAL"
MODE_LOCAL_DEGRADED = "LOCAL_DEGRADED"
STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
STATUS_UNAVAILABLE = "UNAVAILABLE"
# Önceki istemci 10'arlı eşzamanlı istek atıyordu; sağlayıcı (frozen `bist_provider._fetch_with_retry`) Yahoo'nun
# eşzamanlılık altında boş/geçici hata döndürdüğünü belgeliyor. Fazla paralellik rate-limit riskini artırır.
MAX_WORKERS = 8
TECHNICAL_WINDOW_MARGIN = timedelta(seconds=60)
NEWS_CACHE_TTL_SECONDS = TECHNICAL_CACHE_TTL_SECONDS

# İstek düzeyi süre bütçesi. Gerekçe (ölçüm + kod): sıcak/yerel tam istek ~7.5–8.5 sn; tek sembolün sağlayıcıdaki en
# kötü zinciri 3 deneme × yfinance 10 sn zaman aşımı + 2 × 2 sn bekleme ≈ 34 sn. 45 sn, kuyrukta geç başlayan tek
# yavaş sembolün bile zincirini bitirmesine izin verir ve Cloud Run'ın varsayılan 300 sn istek sınırının çok
# altındadır. Bütçe aşılınca biten satırlar döner, bitmeyenler açık hata satırı olur (skor üretilmez).
DEFAULT_DASHBOARD_TOTAL_BUDGET_SECONDS = 45.0
DEADLINE_EXCEEDED = "DASHBOARD_DEADLINE_EXCEEDED"


_wait = wait  # testler bekleme süresini gözlemlemek için değiştirebilir


def dashboard_budget_seconds() -> float:
    """`DASHBOARD_TOTAL_BUDGET_SECONDS` (opsiyonel) veya varsayılan. Geçersiz değer sessizce yok sayılmaz."""
    raw = os.environ.get("DASHBOARD_TOTAL_BUDGET_SECONDS")
    if raw is None:
        return DEFAULT_DASHBOARD_TOTAL_BUDGET_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"DASHBOARD_TOTAL_BUDGET_SECONDS sayı olmalı: {raw!r}") from None
    if not 0 < value <= MAX_DASHBOARD_TOTAL_BUDGET_SECONDS:
        raise ValueError(f"DASHBOARD_TOTAL_BUDGET_SECONDS (0, {MAX_DASHBOARD_TOTAL_BUDGET_SECONDS:g}] aralığında "
                         f"olmalı: {raw!r}")
    return value


# Bütçe isteğin BAŞINDAN sayılır (ön yükleme + işçiler). Ön yüklemedeki Firestore çağrıları yarıda kesilemediği için
# 300 sn Cloud Run sınırına ön yükleme ve yanıt derleme payı bırakılır.
MAX_DASHBOARD_TOTAL_BUDGET_SECONDS = 240.0

_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None


def dashboard_executor() -> ThreadPoolExecutor:
    """Süreç genelinde TEK dashboard havuzu (en çok `MAX_WORKERS` thread). İstek başına havuz, süresi dolan isteğin
    hâlâ çalışan işleri sürerken yeni isteğin yeni işçiler açmasına (8 → 16 → 24 eşzamanlı Yahoo isteği) izin
    veriyordu. Tek havuzla, üst üste gelen istekler dahil, süreçteki dashboard kaynaklı aktif iş sayısı hiçbir zaman
    `MAX_WORKERS`'ı aşmaz; yeni isteğin işleri kuyrukta bekler ve gerekirse kendi deadline'ında açık hata olur.
    Havuz istek sonunda KAPATILMAZ; yalnız o isteğin başlamamış işleri iptal edilir."""
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="dashboard")
        return _EXECUTOR


class RequestConfigRepository:
    """`get_raw` sonuçlarını istek boyunca tutar (anahtar başına tek okuma). İstekler arası paylaşılmaz: config
    değişikliği bir sonraki istekte görülür."""

    def __init__(self, inner):
        self._inner, self._lock, self._values = inner, threading.Lock(), {}

    def get_raw(self, config_id: str):
        with self._lock:
            if config_id not in self._values:
                self._values[config_id] = self._inner.get_raw(config_id)
            value = self._values[config_id]
        return dict(value) if value is not None else None


class RequestBenchmarkCacheRepository:
    """Benchmark cache okuması istek başına bir kez; `set` yalnız bu isteğin belleğine yazar (dashboard salt-okunur)."""

    def __init__(self, inner):
        self._inner, self._lock, self._loaded, self._value = inner, threading.Lock(), False, None

    def get(self):
        with self._lock:
            if not self._loaded:
                self._value, self._loaded = self._inner.get(), True
            return self._value

    def set(self, close_by_date, fetched_at) -> None:
        with self._lock:
            self._value, self._loaded = (dict(close_by_date), fetched_at), True


class WindowedTechnicalAnalysisRepository:
    """Tek aralık sorgusuyla önceden yüklenmiş son teknik analizler. `add` yoktur: dashboard yazmaz."""

    def __init__(self, records):
        latest: dict[str, tuple[str, object]] = {}
        for doc_id, analysis in records:
            current = latest.get(analysis.asset)
            if current is None or analysis.created_at > current[1].created_at:
                latest[analysis.asset] = (doc_id, analysis)
        self._latest = latest

    def get_latest_with_id(self, asset: str):
        doc_id, analysis = self._latest.get(asset, (None, None))
        return analysis, doc_id

    def add(self, analysis):  # pragma: no cover - persist=False ile çağrılmaz
        raise RuntimeError("Dashboard teknik analiz YAZMAZ (persist=False).")


class FixedMacroRepository:
    def __init__(self, latest):
        self._latest = latest

    def get_latest_with_id(self):
        return self._latest


class _NoWriteDecisionRepository:
    def add(self, decision):  # pragma: no cover - persist=False ile çağrılmaz
        raise RuntimeError("Dashboard karar YAZMAZ (persist=False).")


_MISSING = object()


class NewsReadCache:
    """Haber seçim girdilerinin süreç içi önbelleği.

    `news_analyses` uygulamada yalnız eklemelidir: tek yazan `NewsAnalysisRepository.add` (yeni rastgele kimlikli
    belge); update/delete/set yolu yok, istemci kuralları tüm yazmaları reddeder. İstek başında anahtar okunur:
    (toplam sayı, en yeni kaydın kimliği + created_at) — 2 okuma. Anahtar değiştiyse veya TTL dolduysa önbellek
    tamamen temizlenir. Uygulama dışı (konsol) yerinde güncelleme anahtarı değiştirmez; etkisi TTL ile sınırlıdır.
    Varlık analizleri ve ham
    haber kayıtları (ham kayıtlar upsert ile değişebildiği için yalnız TTL süresince) ihtiyaç anında okunup tutulur.
    Seçim algoritması (`select_recent_unique_news_analyses`) aynen çalışır; yalnız girdileri buradan gelir. Bu yüzden
    sonuç, tekil `/decisions/{symbol}` ile aynı veri üzerinde birebir aynıdır."""

    def __init__(self, ttl_seconds: float = NEWS_CACHE_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._clock = ttl_seconds, clock
        self._lock = threading.Lock()
        self._key = _MISSING
        self._expires_at = 0.0
        self._analyses: dict[str, list] = {}
        self._raw: dict[str, object] = {}

    def validate(self, key) -> None:
        with self._lock:
            if self._key != key or self._clock() >= self._expires_at:
                self._key, self._expires_at = key, self._clock() + self._ttl
                self._analyses, self._raw = {}, {}

    def analyses(self, asset: str, load: Callable[[], list]) -> list:
        with self._lock:
            cached = self._analyses.get(asset)
        if cached is None:
            cached = list(load())
            with self._lock:
                self._analyses[asset] = cached
        return list(cached)

    def raw(self, external_id: str, load: Callable[[], object]):
        with self._lock:
            cached = self._raw.get(external_id, _MISSING)
        if cached is _MISSING:
            cached = load()
            with self._lock:
                self._raw[external_id] = cached
        return cached


class CachedNewsRepository:
    def __init__(self, inner, cache: NewsReadCache):
        self._inner, self._cache = inner, cache

    def list_for_asset(self, asset: str, limit: int | None = 20):
        records = self._cache.analyses(asset, lambda: self._inner.list_for_asset(asset, limit=None))
        return records if limit is None else records[:limit]


class CachedNewsRawRepository:
    def __init__(self, inner, cache: NewsReadCache):
        self._inner, self._cache = inner, cache

    def get_by_external_id(self, external_id: str):
        return self._cache.raw(external_id, lambda: self._inner.get_by_external_id(external_id))


NEWS_READ_CACHE = NewsReadCache()


class DashboardDependencies:
    """Gerçek depolar; testler sahte nesnelerle değiştirir."""

    def __init__(self, *, config_repo=None, macro_repo=None, technical_repo=None, benchmark_cache_repo=None,
                 news_repo=None, news_raw_repo=None, technical_engine_factory=None, news_cache=None):
        from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
        from app.repositories.macro_snapshot_repository import MacroSnapshotRepository
        from app.repositories.news_analysis_repository import NewsAnalysisRepository
        from app.repositories.news_raw_repository import NewsRawRepository
        from app.repositories.system_config_repository import SystemConfigRepository
        from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository

        self.config_repo = config_repo or SystemConfigRepository()
        self.macro_repo = macro_repo or MacroSnapshotRepository()
        self.technical_repo = technical_repo or TechnicalAnalysisRepository()
        self.benchmark_cache_repo = benchmark_cache_repo or BenchmarkCacheRepository()
        self.news_repo = news_repo or NewsAnalysisRepository()
        self.news_raw_repo = news_raw_repo or NewsRawRepository()
        self.technical_engine_factory = technical_engine_factory or (
            lambda config_repo, analysis_repo, benchmark_cache_repo: TechnicalAnalysisEngine(
                config_repo=config_repo, analysis_repo=analysis_repo, benchmark_cache_repo=benchmark_cache_repo))
        self.news_cache = news_cache or NEWS_READ_CACHE


def _item(asset: str, status: str, reason: str | None = None, decision=None) -> dict:
    out = {"asset": asset, "status": status, "reason": reason, "decision": None, "final_score": None,
           "confidence": None, "channel_completeness": None, "technical_score": None, "news_score": None,
           "macro_score": None, "decision_as_of": None, "decision_engine_version": None}
    if decision is not None:
        out.update(decision=decision.decision, final_score=decision.final_score, confidence=decision.confidence,
                   channel_completeness=decision.channel_completeness, technical_score=decision.technical_score,
                   news_score=decision.news_score, macro_score=decision.macro_score,
                   decision_as_of=decision.decision_as_of.isoformat() if decision.decision_as_of else None,
                   decision_engine_version=decision.decision_engine_version)
    return out


def _sort_key(item: dict):
    # En güçlü AL üstte; karar üretilemeyenler en altta (önceki Flutter sıralamasıyla aynı).
    return (item["final_score"] is None, -(item["final_score"] or 0.0), item["asset"])


def build_dashboard(symbols: list[str], asset_source: str, deps: DashboardDependencies | None = None,
                    now: datetime | None = None, budget_seconds: float | None = None,
                    executor: ThreadPoolExecutor | None = None,
                    clock: Callable[[], float] = time.monotonic) -> dict:
    """`executor`/`clock` yalnız testler içindir; üretimde süreç genelindeki havuz ve monotonik saat kullanılır."""
    deps = deps or DashboardDependencies()
    now = now or datetime.now(timezone.utc)
    local = local_lan_dev_enabled()
    budget = dashboard_budget_seconds() if budget_seconds is None else budget_seconds
    started = clock()
    deadline = started + budget

    def degraded(reason: str) -> dict:
        return {"generated_at": now.isoformat(), "mode": MODE_LOCAL_DEGRADED, "asset_source": asset_source,
                "reason": reason, "items": [_item(s, STATUS_UNAVAILABLE, reason) for s in symbols]}

    try:
        config_repo = RequestConfigRepository(deps.config_repo)
        macro = FixedMacroRepository(deps.macro_repo.get_latest_with_id())
        cutoff = now - timedelta(seconds=TECHNICAL_CACHE_TTL_SECONDS) - TECHNICAL_WINDOW_MARGIN
        technical_repo = WindowedTechnicalAnalysisRepository(deps.technical_repo.list_created_since(cutoff))
        deps.news_cache.validate((deps.news_repo.count_all(), deps.news_repo.latest_marker()))
    except ResourceExhausted:
        if local:
            return degraded(FIRESTORE_QUOTA_EXHAUSTED)
        raise
    benchmark_repo = RequestBenchmarkCacheRepository(deps.benchmark_cache_repo)
    news_repo = CachedNewsRepository(deps.news_repo, deps.news_cache)
    news_raw_repo = CachedNewsRawRepository(deps.news_raw_repo, deps.news_cache)
    engine = DecisionEngine(config_repo=config_repo, decision_repo=_NoWriteDecisionRepository())

    cache_hits = []  # teknik analiz Firestore cache isabeti (persist=False hesaplamada kimlik yoktur)

    def decide(symbol: str) -> dict:
        try:
            technical = deps.technical_engine_factory(config_repo, technical_repo, benchmark_repo)
            decision = engine.decide_for_asset(symbol, technical_engine=technical, macro_repo=macro,
                                               news_repo=news_repo, news_raw_repo=news_raw_repo, persist=False)
        except ResourceExhausted:
            if local:
                return _item(symbol, STATUS_UNAVAILABLE, FIRESTORE_QUOTA_EXHAUSTED)
            raise
        except ValueError as exc:  # yetersiz veri / fiyat alınamadı / geçersiz config: o satır karar üretmez
            return _item(symbol, STATUS_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001 — önceki davranış: tek sembolün hatası yalnız o satırı etkiler
            return _item(symbol, STATUS_ERROR, f"{type(exc).__name__}: {exc}")
        if decision.technical_analysis_id is not None:
            cache_hits.append(symbol)
        return _item(symbol, STATUS_OK, decision=decision)

    # Süre sınırı: tek mutlak deadline (istek başı + bütçe). Ön yükleme süresi işçi beklemesinden düşülür; bütçe ön
    # yüklemede bittiyse hiçbir iş başlatılmaz (sağlayıcı çağrısı 0). Başlamış bir iş (süren bir Yahoo isteği)
    # Python'da durdurulamaz: süreç genelindeki havuzda en çok `MAX_WORKERS` iş, sağlayıcının kendi zaman aşımı/deneme
    # zinciriyle sınırlı biter ve sonucu atılır. Dashboard salt-okunur olduğundan geç biten iş hiçbir şey yazmaz.
    workers_started_at = clock()
    remaining = deadline - workers_started_at
    futures = []
    done = set()
    if remaining > 0:
        pool = executor or dashboard_executor()
        futures = [(symbol, pool.submit(decide, symbol)) for symbol in symbols]
        # `decide` üretimdeki kota hatası dışında her hatayı satıra çevirir; FIRST_EXCEPTION yalnız o durumda erken
        # döner (503 için kalan sembolleri beklemeye gerek yok).
        done, _ = _wait([f for _, f in futures], timeout=remaining, return_when=FIRST_EXCEPTION)
        for _symbol, future in futures:
            if future not in done:
                future.cancel()  # yalnız BU isteğin başlamamış işleri; başka isteğinkiler etkilenmez
    worker_wait_ms = int((clock() - workers_started_at) * 1000)
    items = []
    by_symbol = dict(futures)
    for symbol in symbols:
        future = by_symbol.get(symbol)
        if future is not None and future in done:
            items.append(future.result())  # üretimde kota hatası burada yükselir → 503
        else:  # bekleme sonrası biten iş de ihtiyatlı olarak deadline sayılır (yarışta sonuç seçilmez)
            items.append(_item(symbol, STATUS_ERROR, DEADLINE_EXCEEDED))
    mode = MODE_LOCAL_DEGRADED if any(i["status"] == STATUS_UNAVAILABLE for i in items) else MODE_NORMAL
    statuses = [i["status"] for i in items]
    logger.info("dashboard built: symbols=%d ok=%d error=%d unavailable=%d deadline_exceeded=%d "
                "technical_cache_hits=%d budget_s=%g elapsed_before_workers_ms=%d worker_wait_ms=%d duration_ms=%d",
                len(items), statuses.count(STATUS_OK), statuses.count(STATUS_ERROR),
                statuses.count(STATUS_UNAVAILABLE), sum(1 for i in items if i["reason"] == DEADLINE_EXCEEDED),
                len(cache_hits), budget, int((workers_started_at - started) * 1000), worker_wait_ms,
                int((clock() - started) * 1000))
    return {"generated_at": now.isoformat(), "mode": mode, "asset_source": asset_source,
            "reason": FIRESTORE_QUOTA_EXHAUSTED if mode == MODE_LOCAL_DEGRADED else None,
            "items": sorted(items, key=_sort_key)}
