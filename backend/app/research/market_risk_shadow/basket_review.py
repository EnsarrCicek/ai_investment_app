"""MARKET-RISK-1 — sabit hisse sepetinde keşifsel karşılaştırma (gölge mod).

Kapsam sonuçlar görülmeden sabitlendi: AKBNK, THYAO, TUPRS, BIMAS, EREGL, ASELS,
KCHOL, TCELL; değerlendirme 2024 ve 2025 (yıl bazında ayrı). Sepet sonuçlara göre
seçilmedi; tarihsel BIST100 evrenini veya piyasayı temsil etmez; bugün işlem gören
şirketlerden oluştuğu için hayatta kalan seçimi yanlılığı taşır.

Parametreler (EXPERIMENTAL_PARAMS_V0), üç durumlu mantık, teknik ağırlıklar (V2
manifesti) ve karar eşikleri (DEFAULT_THRESHOLDS) sabittir. Bu, "bugünkü motorun
bugün indirilen geçmiş verilerle yeniden canlandırılması"dır; ham sınıf yalnızca
teknik kanaldandır. İleri getiriler sinyal sonrası kapanış hareketidir; işlem
sonucu, gün içi drawdown veya ekonomik fayda DEĞİLDİR.

Adımlar (backend klasöründen):
    python -m app.research.market_risk_shadow.basket_review --fetch <out_dir>   # tek seferlik indirme
    python -m app.research.market_risk_shadow.basket_review --compute <out_dir> # ağsız hesap + özet
"""

from __future__ import annotations

import dataclasses
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.engines.risk.shadow_inputs import EXPERIMENTAL_PARAMS_V0, RULE_LOGIC_VERSION
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow.event_review import (
    BACKEND_ROOT,
    CODE_FILES,
    _sha256_file,
    CSV_READER,
    load_saved_provider_csv,
    prepare_run_input,
    review,
)
from app.services.market_data.completed_bars import latest_expected_completed_date
from app.services.market_data.trading_calendar import expected_trading_sessions

SYMBOLS = ("AKBNK", "THYAO", "TUPRS", "BIMAS", "EREGL", "ASELS", "KCHOL", "TCELL")
INDEX = "XU100"
YEARS = (2024, 2025)
FETCH_START = date(2022, 6, 1)  # ısınma: piyasa volatilitesi 270 seans, teknik hat 6 ay + pre-roll
HORIZONS = ("T+5", "T+10", "T+20")
BUY = ("BUY", "WEAK_BUY")
ANOMALY_ABS_DAILY_PCT = 20.0  # BIST günlük fiyat marjının belirgin üstü: veri anomalisi adayı
EXTRA_CODE_FILES = ("app/research/market_risk_shadow/basket_review.py",)


# ------------------------------------------------------------------ fetch (tek seferlik, ağ)


def fetch(out: Path) -> None:
    import yfinance as yf

    from app.services.market_data.bist_provider import BistProvider

    out.mkdir(parents=True, exist_ok=True)
    run_now = datetime.now(ISTANBUL_TZ)
    end_exclusive = (run_now.date() + timedelta(days=1)).isoformat()
    provider = BistProvider()
    identity, actions = {}, {}
    for symbol in (INDEX, *SYMBOLS):  # XU100 bir kez indirilir
        provider.get_history(symbol, start=FETCH_START.isoformat(), end=end_exclusive).to_csv(out / f"{symbol}_provider_ohlcv.csv")
        ticker = yf.Ticker(f"{symbol}.IS")
        try:
            info = ticker.info
            identity[symbol] = {k: info.get(k) for k in ("symbol", "shortName", "longName", "exchange", "currency", "quoteType")}
        except Exception as exc:  # noqa: BLE001
            identity[symbol] = {"error": type(exc).__name__}
        if symbol != INDEX:
            acts = ticker.actions
            acts.to_csv(out / f"{symbol}_corporate_actions.csv")
            actions[symbol] = [{"date": ts.date().isoformat(), **{k: float(v) for k, v in r.items()}}
                               for ts, r in acts.iterrows() if ts.date() >= FETCH_START]
    (out / "fetch_manifest.json").write_text(json.dumps({
        "run_at": run_now.isoformat(),
        "fetch_start": FETCH_START.isoformat(),
        "data_source": "Yahoo Finance via yfinance (BistProvider.get_history, yfinance default auto_adjust=True: "
                       "split+dividend adjusted prices); unofficial, ~20 min delayed",
        "yfinance_version": yf.__version__,
        "symbol_identity": identity,
        "corporate_actions_since_fetch_start": actions,
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


# ------------------------------------------------------------------ compute (ağsız)


def data_anomalies(df) -> list[dict]:
    closes = df["Close"]
    daily = closes.pct_change() * 100
    return [{"session": ts.date().isoformat(), "daily_pct": round(float(v), 4)}
            for ts, v in daily.items() if abs(v) > ANOMALY_ABS_DAILY_PCT]


def compute(folder: Path, out: Path | None = None) -> dict:
    """`folder`daki kayıtlı girdileri okur; sonuçları `out`a (varsayılan: `folder`) yazar."""
    out = out or folder
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((folder / "fetch_manifest.json").read_text(encoding="utf-8"))
    run_now = datetime.fromisoformat(manifest["run_at"])
    inputs = {s: prepare_run_input(load_saved_provider_csv(folder / f"{s}_provider_ohlcv.csv"), run_now)
              for s in (INDEX, *SYMBOLS)}
    last_completed = expected_trading_sessions(date(2026, 1, 1), latest_expected_completed_date(run_now))[-1]
    calendar = expected_trading_sessions(date(YEARS[0], 1, 1), last_completed)
    review_days = [d for d in calendar if d.year in YEARS]
    anomalies = {s: data_anomalies(inputs[s]) for s in SYMBOLS}
    rows = {}
    for symbol in SYMBOLS:
        rows[symbol] = review(inputs[symbol], inputs[INDEX], symbol, review_days, EXPERIMENTAL_PARAMS_V0,
                              calendar_sessions=calendar)
        closes = inputs[symbol]["Close"]
        by_date = {ts.date(): float(v) for ts, v in closes.items()}
        for r in rows[symbol]:
            r["t10_path"] = path_extremes(by_date, date.fromisoformat(r["session"]), calendar, 10)
        (out / f"{symbol}_daily_review.json").write_text(json.dumps(rows[symbol], ensure_ascii=False, default=str), encoding="utf-8")
    summary = summarize(rows, anomalies)
    summary["run"] = {
        "inputs_folder": folder.name,
        "inputs_run_at": manifest["run_at"],
        "last_completed_session_for_outcomes": last_completed.isoformat(),
        "input_sha256": {s: _sha256_file(folder / f"{s}_provider_ohlcv.csv") for s in (INDEX, *SYMBOLS)},
        "csv_reader": {**CSV_READER, "pandas_version": pd.__version__},
        "params": dataclasses.asdict(EXPERIMENTAL_PARAMS_V0),
        "rule_logic_version": RULE_LOGIC_VERSION,
        "technical": "V2 frozen manifest weights; raw class = _classify(score, DEFAULT_THRESHOLDS); technical channel only",
        "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in (*CODE_FILES, *EXTRA_CODE_FILES)},
        "data_anomalies_abs_daily_over_20pct": anomalies,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


def path_extremes(closes_by_date: dict, session: date, calendar: list[date], horizon: int) -> dict:
    """T'den sonraki `horizon` seansın kapanışlarına göre en kötü/en iyi ara getiri.
    Yolda eksik bar varsa veya ufuk tamamlanmadıysa hesaplanmaz (başka tarih konmaz)."""
    if session not in closes_by_date:
        return {"status": "MISSING_T"}
    i = calendar.index(session)
    if i + horizon >= len(calendar):
        return {"status": "PENDING"}
    path = calendar[i + 1: i + horizon + 1]
    if any(d not in closes_by_date for d in path):
        return {"status": "MISSING"}
    base = closes_by_date[session]
    moves = [(closes_by_date[d] / base - 1) * 100 for d in path]
    return {"status": "OK", "worst": round(min(moves), 4), "best": round(max(moves), 4)}


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": "N/A", "negative_share": "N/A"}
    return {"n": len(values), "median": round(statistics.median(values), 4),
            "negative_share": round(sum(v < 0 for v in values) / len(values), 4)}


def _outcomes(rows: list[dict]) -> dict:
    out = {}
    for h in HORIZONS:
        values = [r["price_move_after_close"][h] for r in rows if isinstance(r["price_move_after_close"].get(h), float)]
        unavailable = sum(1 for r in rows if not isinstance(r["price_move_after_close"].get(h), float))
        out[h] = {**_stats(values), "unavailable": unavailable,
                  "positive_count": sum(v > 0 for v in values), "negative_count": sum(v < 0 for v in values)}
    paths = [r["t10_path"] for r in rows if r["t10_path"]["status"] == "OK"]
    out["T+10_path"] = {"n": len(paths),
                        "median_worst_close": round(statistics.median(p["worst"] for p in paths), 4) if paths else "N/A",
                        "median_best_close": round(statistics.median(p["best"] for p in paths), 4) if paths else "N/A",
                        "unavailable": len(rows) - len(paths)}
    return out


def blocked_episodes(rows: list[dict]) -> list[dict]:
    """Ardışık değerlendirme seanslarında kesintisiz BLOCKED dizileri (tekrar sayım kontrolü)."""
    episodes, current = [], None
    for r in rows:
        if r["shadow_gate"] == "BLOCKED":
            if current is None:
                current = {"start": r["session"], "length": 0, "start_row": r}
            current["length"] += 1
        elif current is not None:
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def summarize(rows_by_symbol: dict, anomalies: dict) -> dict:
    rule_names = ("INDEX_DRAWDOWN_FROM_HIGH", "INDEX_VOLATILITY_ELEVATED", "INDEX_BELOW_TREND",
                  "ASSET_PERIOD_DECLINE", "ASSET_UNDERPERFORMS_INDEX", "SHARP_DAILY_DECLINE_OBSERVED")
    per, pooled = {}, {y: {"ALLOWED": [], "BLOCKED": [], "INDETERMINATE": 0, "episodes": []} for y in YEARS}
    for symbol, rows in rows_by_symbol.items():
        for year in YEARS:
            yr = [r for r in rows if r["session"].startswith(str(year))]
            buy = [r for r in yr if r["raw_class_technical_only"] in BUY]
            gates = {g: sum(r["shadow_gate"] == g for r in buy) for g in ("ALLOWED", "BLOCKED", "INDETERMINATE")}
            rule_rate = {}
            for name in rule_names:
                evaluated = sum(1 for r in yr
                                if (r.get("market_rules", {}) | r.get("asset_rules", {})).get(name, {}).get("status") == "EVALUATED")
                rule_rate[name] = round(evaluated / len(yr), 4) if yr else "N/A"
            episodes = blocked_episodes(yr)
            allowed = [r for r in buy if r["shadow_gate"] == "ALLOWED"]
            blocked = [r for r in buy if r["shadow_gate"] == "BLOCKED"]
            per[f"{symbol} {year}"] = {
                "expected_sessions": len(yr),
                "technical_ok_sessions": sum(r["technical_status"] == "OK" for r in yr),
                "buy_direction": len(buy),
                "gate_on_buy_direction": gates,
                "market_determined_sessions": sum(r["market_risk"] in ("RISK_TRIGGERED", "NO_DEFINED_RULE_TRIGGERED") for r in yr),
                "rule_evaluable_share": rule_rate,
                "allowed_outcomes": _outcomes(allowed),
                "blocked_outcomes": _outcomes(blocked),
                "blocked_episodes": len(episodes),
                "blocked_episode_start_outcomes": _outcomes([e["start_row"] for e in episodes]),
                "data_anomalies_in_year": [a for a in anomalies[symbol] if a["session"].startswith(str(year))],
            }
            pooled[year]["ALLOWED"] += allowed
            pooled[year]["BLOCKED"] += blocked
            pooled[year]["INDETERMINATE"] += gates["INDETERMINATE"]
            pooled[year]["episodes"] += [e["start_row"] for e in episodes]
    pooled_out = {
        str(y): {
            "allowed_outcomes": _outcomes(p["ALLOWED"]),
            "blocked_outcomes": _outcomes(p["BLOCKED"]),
            "indeterminate_buy_direction": p["INDETERMINATE"],
            "blocked_episodes": len(p["episodes"]),
            "blocked_episode_start_outcomes": _outcomes(p["episodes"]),
            "blocked_share_by_symbol": {s: per[f"{s} {y}"]["gate_on_buy_direction"]["BLOCKED"] for s in rows_by_symbol},
        }
        for y, p in pooled.items()
    }
    return {"per_symbol_year": per, "pooled_by_year": pooled_out}


def main() -> int:
    args = sys.argv[1:]
    if not ((len(args) == 2 and args[0] in ("--fetch", "--compute")) or (len(args) == 4 and args[0] == "--compute" and args[2] == "--out")):
        raise SystemExit("kullanım: --fetch <out_dir> | --compute <in_dir> [--out <out_dir>]")
    folder = Path(args[1])
    if args[0] == "--fetch":
        fetch(folder)
    else:
        compute(folder, Path(args[3]) if len(args) == 4 else None)
    print(folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
