"""MARKET-RISK-1 — protokoldeki tarihli sabit evrende keşifsel karşılaştırma (gölge mod).

Evren: Technical V2 protokolünün dondurulmuş 100 sembollük listesi (üyelik dönemi
2026-07-01..2026-09-30, evren tarihi 2026-09-09; kaynak KAP Endeksler). Salt okunur
kullanılır. Bu liste 2024-2025 tarihsel BIST100 üyeliğini TEMSİL ETMEZ (bugünkü
üyelerden oluşur, hayatta kalan seçimi yanlılığı taşır); BIST100 de Borsa İstanbul'daki
bütün hisseler değildir. Çalışma tarihsel BIST100 performansı veya bağımsız doğrulama
değildir; bugünkü motorun bugün indirilen verilerle yeniden canlandırılmasıdır ve
ham sınıf yalnızca teknik kanaldandır.

Parametreler, kural birleşimleri, teknik ağırlıklar, eşikler ve veri kalitesi
kontrolleri basket_review/event_review ile aynıdır.

Adımlar (backend klasöründen):
    python -m app.research.market_risk_shadow.universe_review --manifest <out>
    python -m app.research.market_risk_shadow.universe_review --fetch <out> --reuse <önceki_girdi_klasörü>
    python -m app.research.market_risk_shadow.universe_review --compute <out>   # ağsız, kaldığı yerden devam
    python -m app.research.market_risk_shadow.universe_review --summarize <out>
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.engines.risk.shadow_inputs import EXPERIMENTAL_PARAMS_V0, RULE_LOGIC_VERSION
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow.basket_review import (
    BUY,
    FETCH_START,
    HORIZONS,
    INDEX,
    YEARS,
    _outcomes,
    blocked_episodes,
    path_extremes,
)
from app.research.market_risk_shadow.event_review import (
    BACKEND_ROOT,
    CODE_FILES,
    CSV_READER,
    _sha256_file,
    load_saved_provider_csv,
    prepare_run_input,
    review,
)
from app.services.market_data.completed_bars import latest_expected_completed_date
from app.services.market_data.trading_calendar import expected_trading_sessions

PROTOCOL_PATH = BACKEND_ROOT / "app/research/resources/technical_v2_protocol_v1.json"
EXTRA_CODE_FILES = (
    "app/research/market_risk_shadow/basket_review.py",
    "app/research/market_risk_shadow/universe_review.py",
)
DOWNLOAD_ATTEMPTS = 2
GROUP_SIZE = 10
GROUP_PAUSE_SECONDS = 3


# ------------------------------------------------------------------ evren manifesti


def build_manifest(out: Path) -> dict:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    universe = protocol["universe"]
    symbols = list(universe["frozen_symbol_list"])
    if len(symbols) != len(set(symbols)):
        raise ValueError("evren listesinde tekrarlı sembol var")
    manifest = {
        "name": "protokoldeki tarihli sabit evren (Technical V2 dondurulmuş BIST100 listesi)",
        "not_current_bist100": True,
        "not_historical_2024_2025_membership": True,
        "bist100_is_not_all_borsa_istanbul_stocks": True,
        "source_file": str(PROTOCOL_PATH.relative_to(BACKEND_ROOT)).replace("\\", "/"),
        "source_file_sha256": _sha256_file(PROTOCOL_PATH),
        "universe_as_of_date": universe["universe_as_of_date"],
        "membership_period": [universe["membership_period_start"], universe["membership_period_end"]],
        "membership_source": universe["membership_source_primary"],
        "symbol_count": len(symbols),
        "symbols": symbols,
        "symbol_list_sha256": hashlib.sha256("\n".join(symbols).encode("utf-8")).hexdigest(),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "universe_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def load_symbols(out: Path) -> list[str]:
    return json.loads((out / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]


# ------------------------------------------------------------------ girdiler (ağ yalnızca burada)


def _describe_csv(path: Path) -> dict:
    df = load_saved_provider_csv(path)
    return {"rows": len(df), "first_session": df.index[0].date().isoformat() if len(df) else None,
            "last_session": df.index[-1].date().isoformat() if len(df) else None, "sha256": _sha256_file(path)}


def fetch_inputs(out: Path, reuse_dir: Path | None, downloader=None) -> dict:
    """Kayıtlı uygun girdileri yeniden kullanır; eksikleri gruplar halinde, sınırlı
    denemeyle indirir. Başarısızlar gerekçesiyle kaydedilir; diğerlerine devam edilir.
    Kesilirse tekrar çalıştırıldığında kayıtlı semboller atlanır."""
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    manifest_path = inputs / "fetch_manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    reuse_meta = json.loads((reuse_dir / "fetch_manifest.json").read_text(encoding="utf-8")) if reuse_dir else {}
    downloader = downloader or _yahoo_download
    downloads = 0
    for symbol in (INDEX, *load_symbols(out)):
        if entries.get(symbol, {}).get("status") in ("REUSED", "DOWNLOADED"):
            continue
        target = inputs / f"{symbol}_provider_ohlcv.csv"
        source = reuse_dir / f"{symbol}_provider_ohlcv.csv" if reuse_dir else None
        if source is not None and source.exists():
            shutil.copyfile(source, target)
            entry = {"status": "REUSED", "fetched_at": reuse_meta.get("run_at"), "source": str(source),
                     "fetch_start": reuse_meta.get("fetch_start")}
        else:
            if downloads and downloads % GROUP_SIZE == 0:
                time.sleep(GROUP_PAUSE_SECONDS)
            downloads += 1
            entry = downloader(symbol, target, inputs)
        if entry["status"] in ("REUSED", "DOWNLOADED"):
            entry.update(_describe_csv(target))
        entry["price_adjustment"] = "yfinance history varsayılanı auto_adjust=True (bölünme+temettü düzeltmeli)"
        entries[symbol] = entry
        manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return entries


def _yahoo_download(symbol: str, target: Path, inputs: Path) -> dict:
    """BistProvider.get_history ile aynı çağrı (start/end, 1d, yfinance varsayılanları);
    aynı yanıttaki kurumsal işlem sütunları ve Yahoo meta verisi ayrıca saklanır."""
    import yfinance as yf

    end_exclusive = (datetime.now(ISTANBUL_TZ).date() + timedelta(days=1)).isoformat()
    last_error = None
    for _ in range(DOWNLOAD_ATTEMPTS):
        try:
            ticker = yf.Ticker(f"{symbol}.IS")
            history = ticker.history(start=FETCH_START.isoformat(), end=end_exclusive, interval="1d")
            if history.empty:
                last_error = "EMPTY_HISTORY"
                continue
            history[["Open", "High", "Low", "Close", "Volume"]].to_csv(target)
            actions = [c for c in ("Dividends", "Stock Splits") if c in history.columns]
            history[actions][(history[actions] != 0).any(axis=1)].to_csv(inputs / f"{symbol}_corporate_actions.csv")
            meta = ticker.history_metadata or {}
            return {"status": "DOWNLOADED", "fetched_at": datetime.now(ISTANBUL_TZ).isoformat(),
                    "fetch_start": FETCH_START.isoformat(),
                    "yahoo_metadata": {k: meta.get(k) for k in ("symbol", "instrumentType", "exchangeName", "currency", "firstTradeDate")}}
        except Exception as exc:  # noqa: BLE001 — sınırlı deneme, erişim kısıtı aşılmaz
            last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
    return {"status": "FAILED", "reason": last_error, "attempted_at": datetime.now(ISTANBUL_TZ).isoformat()}


# ------------------------------------------------------------------ hesap (ağsız, kaldığı yerden devam)


def run_identity() -> dict:
    return {
        "params": dataclasses.asdict(EXPERIMENTAL_PARAMS_V0),
        "rule_logic_version": RULE_LOGIC_VERSION,
        "csv_reader": {**CSV_READER, "pandas_version": pd.__version__},
        "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in (*CODE_FILES, *EXTRA_CODE_FILES)},
    }


def _calendar_end(entries: dict) -> date:
    times = [datetime.fromisoformat(e["fetched_at"]) for e in entries.values() if e.get("fetched_at")]
    return expected_trading_sessions(date(2026, 1, 1), latest_expected_completed_date(min(times)))[-1]


def compute_all(out: Path, review_fn=review, identity: dict | None = None, log=print) -> None:
    inputs = out / "inputs"
    results = out / "results"
    results.mkdir(parents=True, exist_ok=True)
    entries = json.loads((inputs / "fetch_manifest.json").read_text(encoding="utf-8"))
    identity = identity or run_identity()
    calendar = expected_trading_sessions(date(YEARS[0], 1, 1), _calendar_end(entries))
    review_days = [d for d in calendar if d.year in YEARS]
    index_entry = entries[INDEX]
    index_df = prepare_run_input(load_saved_provider_csv(inputs / f"{INDEX}_provider_ohlcv.csv"),
                                 datetime.fromisoformat(index_entry["fetched_at"]))
    for n, symbol in enumerate(load_symbols(out), 1):
        path = results / f"{symbol}.json"
        entry = entries.get(symbol, {"status": "MISSING_FROM_FETCH_MANIFEST"})
        key = {"identity": identity, "input_sha256": entry.get("sha256"), "index_sha256": index_entry.get("sha256"),
               "calendar_end": calendar[-1].isoformat()}
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("key") == key:
            log(f"[{n}/{len(entries) - 1}] {symbol}: aynı kimlikle mevcut, atlandı")
            continue
        if entry.get("status") not in ("REUSED", "DOWNLOADED"):
            payload = {"key": key, "status": "NOT_COMPUTED", "reason": entry.get("reason", entry.get("status")), "rows": []}
        else:
            df = prepare_run_input(load_saved_provider_csv(inputs / f"{symbol}_provider_ohlcv.csv"),
                                   datetime.fromisoformat(entry["fetched_at"]))
            rows = review_fn(df, index_df, symbol, review_days, EXPERIMENTAL_PARAMS_V0, calendar_sessions=calendar)
            by_date = {ts.date(): float(v) for ts, v in df["Close"].items()}
            for r in rows:
                r["t10_path"] = path_extremes(by_date, date.fromisoformat(r["session"]), calendar, 10)
            payload = {"key": key, "status": "COMPUTED", "rows": rows}
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        log(f"[{n}] {symbol}: {payload['status']}")


# ------------------------------------------------------------------ özet


def _block_source(r: dict) -> str:
    m, a = r["market_risk"] == "RISK_TRIGGERED", r["asset_risk"] == "RISK_TRIGGERED"
    return "BOTH" if m and a else ("MARKET_ONLY" if m else "ASSET_ONLY")


def _reason_key(reason: str) -> str:
    return reason.split(":")[0] if reason else "UNKNOWN"


def summarize(out: Path) -> dict:
    symbols = load_symbols(out)
    entries = json.loads((out / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    rule_names = ("INDEX_DRAWDOWN_FROM_HIGH", "INDEX_VOLATILITY_ELEVATED", "INDEX_BELOW_TREND",
                  "ASSET_PERIOD_DECLINE", "ASSET_UNDERPERFORMS_INDEX", "SHARP_DAILY_DECLINE_OBSERVED")
    per, pooled = {}, {y: {"ALLOWED": [], "BLOCKED": [], "INDETERMINATE": 0, "episode_starts": []} for y in YEARS}
    counts = {"universe": len(symbols), "downloaded_or_reused": 0, "computed": 0, "produced_valid_decision": 0}
    for symbol in symbols:
        entry = entries.get(symbol, {"status": "MISSING_FROM_FETCH_MANIFEST"})
        result_path = out / "results" / f"{symbol}.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {"status": "NO_RESULT_FILE", "rows": []}
        counts["downloaded_or_reused"] += entry.get("status") in ("REUSED", "DOWNLOADED")
        counts["computed"] += result["status"] == "COMPUTED"
        rows = result["rows"]
        counts["produced_valid_decision"] += any(r["technical_status"] == "OK" for r in rows)
        for year in YEARS:
            yr = [r for r in rows if r["session"].startswith(str(year))]
            buy = [r for r in yr if r["raw_class_technical_only"] in BUY]
            gates = {g: sum(r["shadow_gate"] == g for r in buy) for g in ("ALLOWED", "BLOCKED", "INDETERMINATE")}
            ok = sum(r["technical_status"] == "OK" for r in yr)
            episodes = blocked_episodes(yr)
            blocked = [r for r in buy if r["shadow_gate"] == "BLOCKED"]
            per[f"{symbol} {year}"] = {
                "download_status": entry.get("status"), "data_range": [entry.get("first_session"), entry.get("last_session")],
                "compute_status": result["status"], "not_computed_reason": result.get("reason"),
                "expected_sessions": len(yr), "technical_ok_sessions": ok,
                "coverage": round(ok / len(yr), 4) if yr else "N/A",
                "no_decision_reasons": dict(Counter(_reason_key(r["technical_reason"]) for r in yr if r["technical_status"] != "OK")),
                "buy_direction": len(buy), "gate_on_buy_direction": gates,
                "rule_evaluable_share": {
                    name: (round(sum(1 for r in yr if (r["market_rules"] | r["asset_rules"])[name]["status"] == "EVALUATED") / len(yr), 4) if yr else "N/A")
                    for name in rule_names},
                "blocked_episodes": len(episodes),
                "blocked_sources": dict(Counter(_block_source(r) for r in blocked)),
            }
            pooled[year]["ALLOWED"] += [r for r in buy if r["shadow_gate"] == "ALLOWED"]
            pooled[year]["BLOCKED"] += blocked
            pooled[year]["INDETERMINATE"] += gates["INDETERMINATE"]
            pooled[year]["episode_starts"] += [e["start_row"] | {"_symbol": symbol} for e in episodes]
    pooled_out = {}
    for year, p in pooled.items():
        blocked_by_symbol = Counter(k.split()[0] for k, v in per.items() if k.endswith(str(year)) for _ in range(v["gate_on_buy_direction"]["BLOCKED"]))
        total_blocked = sum(blocked_by_symbol.values())
        top5 = blocked_by_symbol.most_common(5)
        pooled_out[str(year)] = {
            "allowed_outcomes": _outcomes(p["ALLOWED"]),
            "blocked_outcomes": _outcomes(p["BLOCKED"]),
            "blocked_outcomes_by_source": {src: _outcomes([r for r in p["BLOCKED"] if _block_source(r) == src])
                                           for src in ("MARKET_ONLY", "ASSET_ONLY", "BOTH")},
            "blocked_count_by_source": dict(Counter(_block_source(r) for r in p["BLOCKED"])),
            "indeterminate_buy_direction": p["INDETERMINATE"],
            "blocked_episodes": len(p["episode_starts"]),
            "blocked_episode_start_outcomes": _outcomes(p["episode_starts"]),
            "blocked_episode_start_dates_shared_by_multiple_symbols": sum(
                1 for _, c in Counter(r["session"] for r in p["episode_starts"]).items() if c > 1),
            "top5_blocked_symbols": top5,
            "top5_share_of_blocked": round(sum(c for _, c in top5) / total_blocked, 4) if total_blocked else "N/A",
        }
    summary = {"counts": counts, "per_symbol_year": per, "pooled_by_year": pooled_out,
               "fetch_times": sorted({e.get("fetched_at", "")[:16] for e in entries.values() if e.get("fetched_at")}),
               "identity": run_identity()}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


def main() -> int:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--manifest":
        build_manifest(Path(args[1]))
    elif len(args) in (2, 4) and args[0] == "--fetch":
        fetch_inputs(Path(args[1]), Path(args[3]) if len(args) == 4 and args[2] == "--reuse" else None)
    elif len(args) == 2 and args[0] == "--compute":
        compute_all(Path(args[1]))
    elif len(args) == 2 and args[0] == "--summarize":
        summarize(Path(args[1]))
    else:
        raise SystemExit("kullanım: --manifest <out> | --fetch <out> [--reuse <dir>] | --compute <out> | --summarize <out>")
    print(args[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
