"""İleriye dönük momentum toplayıcısı — gün sonu (EOD) arşivi ve preflight (YALNIZ araştırma; üretim DEĞİL).

* Ağ yalnız `YahooCollectorSource` çağrıldığında kullanılır; testler sahte kaynakla çalışır.
* Kaynak, üretim `YahooIntradayProvider`'ın aksine kimlik uyuşmazlığında hata FIRLATMAZ: yanıt MISMATCH olarak
  arşivlenir (birincil analize girmez). Meta yoksa UNVERIFIED; varsayılan TRY/IST yazılmaz.
* Başarısız/boş yanıt → `fetch_failures`; bar yazılmaz, ileri doldurma yok.
* Model, etiket, sonuç, PASS/FAIL ÜRETİLMEZ.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector.storage import Archive, FetchResult, IngestCounts

EOD_PERIOD = "5d"
PREFLIGHT_SYMBOLS = ("AKBNK", "THYAO")


class CollectorSource(Protocol):
    def fetch(self, symbol: str, interval: str, period: str) -> FetchResult:
        ...


class EmptyResponse(RuntimeError):
    pass


class YahooCollectorSource:
    """Mevcut Yahoo erişimi: aynı `_fetch_with_retry` (geçici hata/boş yanıt yeniden denemesi) ve aynı yanıtın meta
    bilgisi (`_response_metadata`, ek istek yok). Kimlik `_identity` ile; uyuşmazlık MISMATCH olarak döner."""

    def fetch(self, symbol: str, interval: str, period: str) -> FetchResult:
        import yfinance as yf

        from app.services.market_data.bist_provenance_provider import (ProviderIdentityError, _identity,
                                                                       _response_metadata)
        from app.services.market_data.bist_provider import _fetch_with_retry

        ticker = yf.Ticker(f"{symbol}.IS")
        history = _fetch_with_retry(lambda: ticker.history(period=period, interval=interval))
        retrieved_at = datetime.now(timezone.utc)
        if history is None or history.empty:
            raise EmptyResponse(f"'{symbol}' {interval} boş yanıt")
        meta = _response_metadata(ticker)
        try:
            currency, exchange, identity = _identity(symbol, meta)
        except ProviderIdentityError:
            currency, exchange, identity = meta.get("currency"), meta.get("exchangeName"), "MISMATCH"
        return FetchResult(symbol=symbol, interval=interval, provider_symbol=meta.get("symbol"),
                           request={"provider_symbol_requested": f"{symbol}.IS", "interval": interval,
                                    "period": period, "method": "yfinance.Ticker.history"},
                           retrieved_at=retrieved_at, bars=history[["Open", "High", "Low", "Close", "Volume"]],
                           currency=currency, exchange=exchange, identity_check=identity)


def roles(m: dict) -> dict[str, str]:
    c = m["config"]
    out = {s: "PRIMARY" for s in c["universe"]}
    out[c["benchmark"]] = "BENCHMARK"
    out.update({s: "DESCRIPTIVE_ONLY" for s in c["descriptive_only_symbols"]})
    return out


def collect(archive: Archive, source: CollectorSource, plan: list[tuple[str, str, str, str]], *, mode: str,
            manifest: dict | None, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
            pace_seconds: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> dict:
    """plan: (symbol, interval, period, universe_role). Her yanıt kendi işleminde; hata diğerlerini durdurmaz."""
    params = {"mode": mode, "plan": [list(p) for p in plan],
              "manifest_sha256": manifest["sha256"] if manifest else None}
    run_id = archive.begin_run(mode, params, now())
    total = IngestCounts()
    ok, failed, identity_fail, errors, requests = set(), set(), set(), [], 0
    for k, (symbol, interval, period, role) in enumerate(plan):
        if k and pace_seconds:
            sleep(pace_seconds)
        requests += 1
        try:
            res = source.fetch(symbol, interval, period)
        except Exception as exc:  # kaynak farklı istisnalar fırlatabilir; ham hata saklanır
            archive.log_failure(run_id, symbol, interval, {"interval": interval, "period": period}, now(), exc)
            failed.add(symbol)
            errors.append({"symbol": symbol, "interval": interval, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        if res.identity_check != "MATCH":
            identity_fail.add(f"{symbol}:{res.identity_check}")
        total.add(archive.ingest(res, run_id, mode=mode, universe_role=role, manifest=manifest))
        ok.add(symbol)
    summary = {"run_id": run_id, "mode": mode, "manifest_sha256": params["manifest_sha256"],
               "symbols_requested": sorted({p[0] for p in plan}), "symbols_succeeded": sorted(ok - failed),
               "symbols_failed": sorted(failed), "intervals": sorted({p[1] for p in plan}),
               "request_count": requests, "new_bars": total.new_bars, "duplicate_bars": total.duplicate_bars,
               "revisions": total.revisions, "partial_observations": total.partial_observations,
               "finalizations": total.finalizations, "invalid_rows": total.invalid_rows,
               "identity_failures": sorted(identity_fail), "errors": errors,
               "started_at": archive.db.execute("SELECT started_at FROM runs WHERE run_id=?",
                                                (run_id,)).fetchone()[0]}
    return archive.finish_run(run_id, summary, now())


def eod_plan(m: dict) -> list[tuple[str, str, str, str]]:
    r = roles(m)
    return [(s, iv, EOD_PERIOD, r[s]) for s in sorted(r) for iv in m["config"]["intervals"]]


def run_eod(archive: Archive, source: CollectorSource, m: dict, **kw) -> dict:
    """Gün sonu arşivi: evren + gösterge + açıklayıcı semboller × 5m/1m; yalnız eksik barlar eklenir."""
    if archive.role != "primary":
        raise RuntimeError("EOD arşivi yalnız birincil depoya")
    return collect(archive, source, eod_plan(m), mode="EOD", manifest=m,
                   pace_seconds=kw.pop("pace_seconds", m["config"]["collection_policy"]
                                       ["pacing_seconds_between_requests"]), **kw)


def run_preflight(archive: Archive, source: CollectorSource, symbols=PREFLIGHT_SYMBOLS, **kw) -> dict:
    """Smoke: 2 varlık + XU100, ayrı preflight deposu. Doğrulama verisi DEĞİLDİR."""
    if archive.role != "preflight":
        raise RuntimeError("preflight yalnız preflight deposuna yazar")
    plan = [(s, iv, "1d", "PREFLIGHT") for s in [*symbols, mm.BENCHMARK] for iv in mm.INTERVALS]
    return collect(archive, source, plan, mode="PREFLIGHT", manifest=None, **kw)
