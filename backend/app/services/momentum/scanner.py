"""MomentumScanner — aktif varlık evreninde erken momentum taraması (salt-okunur).

* Süreç genelinde TEK havuz, en çok `MOMENTUM_MAX_WORKERS` (4) eşzamanlı Yahoo isteği. Dashboard havuzundan (8)
  ayrıdır: tarama dashboard'u aç bırakmaz; ikisinin birlikte en kötü toplamı 12'dir.
* Mutlak süre bütçesi (istek başından; haber bağlamı yüklemesi dahil). Bitmeyen semboller açık `ERROR /
  SCAN_DEADLINE_EXCEEDED` satırı olur; başlamamış işler iptal edilir (dashboard ile aynı tasarım).
* Gün içi veri süreç içi 60 sn önbellekte (anahtar: sembol, aralık, dönem, kaynak); süresi dolan sunulmaz.
* Haber/olay bağlamı yalnız OKUNUR (dashboard haber önbelleği); yüklenemezse katalizör "yok" değil "bilinmiyor".
* Firestore'a hiçbir şey yazılmaz; bildirim gönderilmez.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Callable

from app.models import momentum_alert as ma
from app.services.market_data.bist_provenance_provider import ProviderIdentityError
from app.services.momentum.early_momentum_engine import DEFAULT_CONFIG, CatalystEvent, evaluate
from app.services.momentum.intraday_provider import CachedIntradayProvider, YahooIntradayProvider

MOMENTUM_MAX_WORKERS = 4
DEFAULT_SCAN_BUDGET_SECONDS = 45.0
SCAN_DEADLINE_EXCEEDED = "SCAN_DEADLINE_EXCEEDED"
# ≥ önceki 10 seans (dönüş bileşeni) + bugün; yfinance "15d" = son 15 işlem günü.
INTRADAY_PERIOD = "15d"
INTERVAL = "5m"

_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
PROVIDER = CachedIntradayProvider(YahooIntradayProvider(), ttl_seconds=60.0)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def momentum_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=MOMENTUM_MAX_WORKERS, thread_name_prefix="momentum")
        return _EXECUTOR


def catalyst_events(analyses, raws: dict) -> list[CatalystEvent]:
    """Haber analizlerini olay bağlamına çevirir. Ham kaydı olmayan analiz atlanır (yayın zamanı doğrulanamaz).
    `available_at` = analizin üretildiği an ile haberin sisteme ilk girdiği anın geç olanı."""
    events = []
    for a in analyses:
        raw = raws.get(a.news_id)
        if raw is None:
            continue
        events.append(CatalystEvent(published_at=raw.published_at, available_at=max(a.created_at, raw.received_at),
                                    sentiment=a.sentiment_score, confidence=a.confidence,
                                    reliability=raw.source_reliability))
    return events


def load_events(symbols: list[str], timeout: float) -> dict[str, list[CatalystEvent]] | None:
    """Dashboard haber önbelleğinden (salt-okunur). Herhangi bir hata → None (katalizör bilinmiyor)."""
    try:
        from app.repositories.news_analysis_repository import NewsAnalysisRepository
        from app.repositories.news_raw_repository import NewsRawRepository
        from app.services.decisions.dashboard import NEWS_READ_CACHE

        snapshot = NEWS_READ_CACHE.prepare(NewsAnalysisRepository(), NewsRawRepository(), symbols, timeout=timeout)
        return {s: catalyst_events(snapshot.analyses(s), {a.news_id: snapshot.raw(a.news_id)
                                                           for a in snapshot.analyses(s)}) for s in symbols}
    except Exception:  # noqa: BLE001 — bağlam isteğe bağlıdır; alarmı engellemez
        return None


def evaluate_symbol(symbol: str, now: datetime, provider=None,
                    events: list[CatalystEvent] | None = None) -> ma.MomentumAlert:
    provider = provider or PROVIDER
    base = {"asset": symbol.upper(), "evaluated_at": now, "interval": INTERVAL}
    try:
        bars = provider.get_intraday(symbol, interval=INTERVAL, period=INTRADAY_PERIOD)
    except ProviderIdentityError as exc:
        return ma.MomentumAlert(status=ma.STATUS_IDENTITY_UNVERIFIED, reason=str(exc), **base)
    except ValueError as exc:
        return ma.MomentumAlert(status=ma.STATUS_ERROR, reason=str(exc), **base)
    except Exception as exc:  # noqa: BLE001 — tek sembolün sağlayıcı hatası yalnız o satırı etkiler
        return ma.MomentumAlert(status=ma.STATUS_ERROR, reason=f"{type(exc).__name__}: {exc}", **base)
    return evaluate(symbol, bars.bars, bars.provenance, now, DEFAULT_CONFIG, events)


def scan(symbols: list[str], now: datetime | None = None, provider=None,
         events_loader: Callable[[list[str], float], dict | None] = load_events,
         budget_seconds: float = DEFAULT_SCAN_BUDGET_SECONDS, executor: ThreadPoolExecutor | None = None,
         include_all: bool = False, clock: Callable[[], float] = time.monotonic) -> dict:
    now = now or now_utc()
    started = clock()
    deadline = started + budget_seconds
    events_by_symbol = events_loader(symbols, max(0.0, deadline - clock()))
    pool = executor or momentum_executor()
    remaining = deadline - clock()
    futures = []
    done = set()
    if remaining > 0:
        futures = [(s, pool.submit(evaluate_symbol, s, now, provider,
                                   events_by_symbol.get(s) if events_by_symbol is not None else None))
                   for s in symbols]
        done, _ = wait([f for _, f in futures], timeout=remaining, return_when=FIRST_EXCEPTION)
        for _s, f in futures:
            if f not in done:
                f.cancel()
    by_symbol = dict(futures)
    results = []
    for s in symbols:
        f = by_symbol.get(s)
        results.append(f.result() if f is not None and f in done
                       else ma.MomentumAlert(asset=s.upper(), status=ma.STATUS_ERROR, reason=SCAN_DEADLINE_EXCEEDED,
                                             evaluated_at=now, interval=INTERVAL))
    alerts = sorted((r for r in results if r.detected), key=lambda r: (r.level != ma.LEVEL_STRONG,
                                                                         -(r.momentum_score or 0), r.asset))
    out = {"generated_at": now.isoformat(), "scanned_count": len(results),
           "watch_count": sum(r.level == ma.LEVEL_WATCH for r in results),
           "strong_count": sum(r.level == ma.LEVEL_STRONG for r in results),
           "unavailable_count": sum(r.status != ma.STATUS_OK for r in results),
           "deadline_exceeded_count": sum(r.reason == SCAN_DEADLINE_EXCEEDED for r in results),
           "catalyst_context": "AVAILABLE" if events_by_symbol is not None else "UNAVAILABLE",
           "alerts": [r.model_dump(mode="json") for r in alerts], "disclaimer": ma.DISCLAIMER}
    if include_all:
        out["items"] = [r.model_dump(mode="json") for r in results]
    return out
