"""EXIT-EXP-1 — normalize, keşifsel çıkış karşılaştırması (yerel, ağsız).

Kapsam: düzeltilmiş (auto_adjust) fiyatlarla KESİRLİ miktarlı normalize hesap. Gerçek TL,
tam lot, gerçek anapara tahsilatı veya uygulanabilir emir sonucu DEĞİLDİR. Tam lot motoru
(`engine.py`) kullanılmaz. Kurallar: `EVALUATION_CONTRACT.md` bölüm K (sonuçlardan önce yazıldı).

Kullanım: python -m app.research.position_exit.normalized <universe_run_dir> <out_dir>
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

C = 0.001
TARGET, STOP, TRAIL, MAX_HOLD = 0.10, 0.08, 0.05, 20
BUY, SELL = ("BUY", "WEAK_BUY"), ("SELL", "WEAK_SELL")
POLICIES = ("REF", "A", "B", "C")
PRIORITY = ("STOP_LOSS", "TRAILING_STOP", "MAX_HOLD", "REFERENCE_EXIT", "TARGET")
FULL_REASONS = ("STOP_LOSS", "TRAILING_STOP", "MAX_HOLD", "REFERENCE_EXIT")
EPS = 1e-12
CODE_FILE = "app/research/position_exit/normalized.py"
CONTRACT_FILE = "app/research/position_exit/EVALUATION_CONTRACT.md"


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def _finite_pos(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def executable(bar: Bar | None) -> bool:
    return bar is not None and _finite_pos(bar.open) and _finite_pos(bar.volume)


def valid_close(bar: Bar | None) -> bool:
    return bar is not None and _finite_pos(bar.close)


def single_price(bar: Bar) -> bool:
    return bar.open == bar.high == bar.low == bar.close


# ---------------------------------------------------------------------------------------------
# Referans epizotları (sözleşme K.8–K.9)
# ---------------------------------------------------------------------------------------------

def reference_episodes(symbol: str, sessions: list[date], bars: dict, classes: dict) -> dict:
    state, pending, ep = "FLAT", None, None
    episodes, unknown_buy_days, no_next = [], [], []

    def close_ep(status, reason=None, **kw):
        nonlocal ep
        ep.update(status=status, reason=reason, **kw)
        episodes.append(ep)
        ep = None

    for i, d in enumerate(sessions):
        bar = bars.get(d)
        if pending is not None:
            kind, sig = pending
            pending = None
            ok = executable(bar)
            if kind == "ENTRY":
                ep = {"id": f"{symbol}:{sig.isoformat()}", "symbol": symbol, "signal_session": sig.isoformat(),
                      "year": sig.year}
                if ok:
                    ep.update(entry_session=d.isoformat(), entry_price=bar.open, entry_single_price=single_price(bar))
                    state = "HOLDING"
                else:
                    close_ep("UNDETERMINED", "ENTRY_EXECUTION_UNDETERMINED", attempted_session=d.isoformat())
                    state = "UNKNOWN"
            elif kind == "EXIT":
                if ok:
                    close_ep("OK", None, end_kind="REFERENCE_EXIT", exit_signal_session=sig.isoformat(),
                             exit_session=d.isoformat(), exit_price=bar.open, exit_single_price=single_price(bar))
                    state = "FLAT"
                else:
                    close_ep("UNDETERMINED", "EXIT_EXECUTION_UNDETERMINED", attempted_session=d.isoformat())
                    state = "UNKNOWN"
            elif kind == "RESYNC" and ok:
                state = "FLAT"

        cls = classes.get(d)
        observed = cls is not None and valid_close(bar)
        last = i == len(sessions) - 1
        if not observed:
            if state == "HOLDING":
                close_ep("UNDETERMINED", "SIGNAL_MISSING_WHILE_HOLDING", at_session=d.isoformat())
            state = "UNKNOWN"
            continue
        if state == "FLAT" and cls in BUY:
            if last:
                no_next.append(f"{symbol}:{d.isoformat()}")
            else:
                pending = ("ENTRY", d)
        elif state == "HOLDING" and cls in SELL and not last:
            pending = ("EXIT", d)
        elif state == "UNKNOWN":
            if cls in BUY:
                unknown_buy_days.append(f"{symbol}:{d.isoformat()}")
            elif cls in SELL and not last:
                pending = ("RESYNC", d)
    if ep is not None:
        close_ep("OK", None, end_kind="OPEN_AT_END", end_session=sessions[-1].isoformat())
    return {"episodes": episodes, "unknown_state_buy_days": unknown_buy_days, "buy_signal_on_final_session": no_next}


# ---------------------------------------------------------------------------------------------
# Politika simülasyonu (sözleşme K.1–K.7, K.11–K.13)
# ---------------------------------------------------------------------------------------------

def run_policy(policy: str, ep: dict, sessions: list[date], bars: dict) -> dict:
    entry = date.fromisoformat(ep["entry_session"])
    exit_d = date.fromisoformat(ep["exit_session"]) if ep["end_kind"] == "REFERENCE_EXIT" else None
    span = [d for d in sessions if d >= entry and (exit_d is None or d <= exit_d)]
    p0 = ep["entry_price"]
    q0 = 1.0 / (p0 * (1 + C))
    shares, cash, cum_net = q0, 0.0, 0.0
    values, peak_value, mdd = [1.0], 1.0, 0.0
    peak_close, trailing, c_done = None, False, False
    pending = None  # {"qty": float|None (None=tam), "reasons": [...], "session": d}
    sales, recovered_k, full_exit = [], None, None
    single_price_fills = 0
    unexecuted_at_end = None

    def track(v):
        nonlocal peak_value, mdd
        values.append(v)
        peak_value = max(peak_value, v)
        mdd = max(mdd, 1 - v / peak_value)

    for k, d in enumerate(span):
        bar = bars[d]
        ref_now = exit_d is not None and d == exit_d
        if k > 0 and shares > 0 and (pending is not None or ref_now):
            reasons = list(pending["reasons"]) if pending else []
            if ref_now:
                reasons.append("REFERENCE_EXIT")
            if not executable(bar):  # referans çıkışı belirli epizotta her zaman dolum koşulunu sağlar
                return {"policy": policy, "status": "EXECUTION_UNDETERMINED", "session": d.isoformat(), "reasons": reasons}
            ordered = [r for r in PRIORITY if r in reasons]
            full = any(r in FULL_REASONS for r in ordered) or pending is None or pending["qty"] is None
            qty = shares if full else min(pending["qty"], shares)
            gross = qty * bar.open
            net = gross * (1 - C)
            cash += net
            cum_net += net
            shares -= qty
            if shares < EPS * q0:
                shares = 0.0
            single_price_fills += single_price(bar)
            sales.append({"session": d.isoformat(), "qty_fraction": qty / q0, "price": bar.open, "net": net,
                          "reasons": ordered, "hypothetical": True, "single_price_day": single_price(bar)})
            if recovered_k is None and cum_net >= 1 - 1e-12:
                recovered_k = k
            if shares == 0.0 and full_exit is None:
                full_exit = {"k": k, "session": d.isoformat(), "price": bar.open, "primary_reason": ordered[0]}
            pending = None
        if ref_now:
            track(cash + shares * bar.open)
            break
        close = bar.close
        track(cash + shares * close)
        if shares == 0.0:
            continue
        peak_close = close if peak_close is None else max(peak_close, close)
        reasons, qty = [], None
        if close <= p0 * (1 - STOP):
            reasons.append("STOP_LOSS")
        if trailing and close <= peak_close * (1 - TRAIL):
            reasons.append("TRAILING_STOP")
        if k + 1 >= MAX_HOLD:
            reasons.append("MAX_HOLD")
        if policy != "REF" and close >= p0 * (1 + TARGET):
            if policy == "A":
                reasons.append("TARGET")
            elif policy == "B" and recovered_k is None:
                reasons.append("TARGET")
                qty = (1 - cum_net) / (close * (1 - C))  # T kapanışı; T+1 açılışı kullanılmaz
                if qty >= shares:
                    qty = None
            elif policy == "C" and not c_done:
                c_done, trailing = True, True
                reasons.append("TARGET")
                qty = q0 / 2
        if policy == "REF":
            reasons = []  # referansın kendi çıkışı yalnızca REFERENCE_EXIT
        if reasons:
            full = any(r in FULL_REASONS for r in reasons) or (policy == "A")
            req = {"qty": None if full else qty, "reasons": reasons, "session": d.isoformat()}
            if k == len(span) - 1:
                unexecuted_at_end = req  # dönem sonu: sonraki seans yok
            else:
                pending = req

    last_close = bars[span[-1]].close if exit_d is None else None
    final_value = cash + (shares * last_close if shares else 0.0)
    unrealized = shares * (last_close - 1.0 / q0) if shares and last_close is not None else 0.0
    return {
        "policy": policy, "status": "OK", "return": final_value - 1.0, "final_value": final_value, "cash": cash,
        "remaining_fraction": shares / q0, "unrealized": unrealized, "open_at_end": shares > 0,
        "mdd": mdd, "sales": sales, "cum_net": cum_net,
        "recovered": recovered_k is not None, "recovery_sessions": recovered_k,
        "full_exit_sessions": full_exit["k"] if full_exit else None,
        "exit_reason": full_exit["primary_reason"] if full_exit else "OPEN_AT_END",
        "early_exit": full_exit is not None and (exit_d is None or full_exit["session"] != exit_d.isoformat()),
        "missed_upside": _missed(full_exit, span, bars, exit_d),
        "single_price_fills": single_price_fills,
        "unexecuted_at_window_end": unexecuted_at_end["reasons"] if unexecuted_at_end else None,
    }


def _missed(full_exit, span, bars, exit_d):
    if not full_exit or (exit_d is not None and full_exit["session"] == exit_d.isoformat()):
        return None
    after = [bars[d].close for d in span if d.isoformat() >= full_exit["session"] and d != exit_d]
    return (max(after) / full_exit["price"] - 1) if after else None


# ---------------------------------------------------------------------------------------------
# Toplama ve koşucu
# ---------------------------------------------------------------------------------------------

def _q(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(p * (len(s) - 1)))]


def _pct(x):
    return None if x is None else round(100 * x, 3)


def summarize(common: list[dict]) -> dict:
    out = {"episodes": len(common), "symbols": len({e["symbol"] for e in common})}
    ref = {e["id"]: e["runs"]["REF"]["return"] for e in common}
    for pol in POLICIES:
        runs = [e["runs"][pol] for e in common]
        rets = [r["return"] for r in runs]
        diffs = [e["runs"][pol]["return"] - ref[e["id"]] for e in common]
        exited = [r["full_exit_sessions"] for r in runs if r["full_exit_sessions"] is not None]
        rec = [r["recovery_sessions"] for r in runs if r["recovered"]]
        early = [r["missed_upside"] for r in runs if r["missed_upside"] is not None]
        open_runs = [r for r in runs if r["open_at_end"]]
        out[pol] = {
            "mean_return_pct": _pct(statistics.fmean(rets)) if rets else None,
            "median_return_pct": _pct(statistics.median(rets)) if rets else None,
            "mean_diff_vs_ref_pct": _pct(statistics.fmean(diffs)) if diffs else None,
            "median_diff_vs_ref_pct": _pct(statistics.median(diffs)) if diffs else None,
            "loss_share": round(sum(r < 0 for r in rets) / len(rets), 4) if rets else None,
            "mdd_median_pct": _pct(_q([r["mdd"] for r in runs], 0.5)),
            "mdd_p90_pct": _pct(_q([r["mdd"] for r in runs], 0.9)),
            "open_at_end": len(open_runs),
            "open_at_end_with_unrealized_loss": sum(r["unrealized"] < 0 for r in open_runs),
            "open_unrealized_loss_sum_units": round(sum(min(r["unrealized"], 0) for r in open_runs), 4),
            "full_exit_sessions_median": _q(exited, 0.5), "not_fully_exited": len(runs) - len(exited),
            "principal_recovered": len(rec), "principal_not_recovered": len(runs) - len(rec),
            "recovery_rate": round(len(rec) / len(runs), 4) if runs else None,
            "recovery_sessions_median": _q(rec, 0.5),
            "exit_reasons": dict(Counter(r["exit_reason"] for r in runs)),
            "early_exits": len(early),
            "missed_upside_median_pct": _pct(_q(early, 0.5)),
            "missed_upside_over_10pct": sum(m > 0.10 for m in early),
            "unexecuted_at_window_end": sum(r["unexecuted_at_window_end"] is not None for r in runs),
            "single_price_day_fills": sum(r["single_price_fills"] for r in runs),
        }
    return out


def max_concurrency(common: list[dict], sessions: list[date]) -> int:
    """Seans d'de elde: giriş <= d < referans çıkış açılışı (açık kalanlar için giriş <= d)."""
    best = 0
    for d in sessions:
        iso = d.isoformat()
        n = sum(e["entry_session"] <= iso and (e.get("exit_session") is None or iso < e["exit_session"]) for e in common)
        best = max(best, n)
    return best


def evaluate(symbol_data: dict[str, tuple[dict, dict]], sessions: list[date]) -> dict:
    """symbol_data: {symbol: (bars{date: Bar}, classes{date: str|None})}. Saf."""
    all_eps, unknown_buys, final_buys, excluded = [], [], [], []
    for sym in sorted(symbol_data):
        bars, classes = symbol_data[sym]
        ref = reference_episodes(sym, sessions, bars, classes)
        unknown_buys += ref["unknown_state_buy_days"]
        final_buys += ref["buy_signal_on_final_session"]
        for ep in ref["episodes"]:
            if ep["status"] != "OK":
                excluded.append({"id": ep["id"], "year": ep["year"], "policy": "REFERENCE", "reason": ep["reason"]})
                continue
            ep["runs"] = {pol: run_policy(pol, ep, sessions, bars) for pol in POLICIES}
            bad = [(pol, r) for pol, r in ep["runs"].items() if r["status"] != "OK"]
            for pol, r in bad:
                excluded.append({"id": ep["id"], "year": ep["year"], "policy": pol, "reason": r["status"], "session": r["session"]})
            ep["common"] = not bad
            all_eps.append(ep)
    years = {}
    for y in (2024, 2025):
        common = [e for e in all_eps if e["year"] == y and e["common"]]
        determined = [e for e in all_eps if e["year"] == y]
        ref_undet = [x for x in excluded if x["year"] == y and x["policy"] == "REFERENCE"]
        years[str(y)] = {
            "candidate_entries_known_state": len(determined) + len(ref_undet),
            "unknown_state_buy_days": sum(1 for u in unknown_buys if u.split(":")[1].startswith(str(y))),
            "reference_undetermined_episodes": dict(Counter(x["reason"] for x in ref_undet)),
            "policy_execution_undetermined_episodes": len({x["id"] for x in excluded if x["year"] == y and x["policy"] != "REFERENCE"}),
            "evaluable_common_episodes": len(common),
            "max_concurrent_open_episodes": max_concurrency(common, sessions),
            "summary": summarize(common),
        }
    return {"years": years, "excluded": excluded, "buy_signal_on_final_session": final_buys, "episodes": all_eps}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(run_dir: Path):
    from app.research.market_risk_shadow.event_review import load_saved_provider_csv
    from app.services.market_data.trading_calendar import expected_trading_sessions

    symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    sessions = expected_trading_sessions(date(2024, 1, 1), date(2025, 12, 31))
    data = {}
    for s in symbols:
        df = load_saved_provider_csv(run_dir / "inputs" / f"{s}_provider_ohlcv.csv")
        bars = {ts.date(): Bar(float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"]))
                for ts, r in df.iterrows()}
        rows = json.loads((run_dir / "results" / f"{s}.json").read_text(encoding="utf-8"))["rows"]
        classes = {date.fromisoformat(r["session"]): (r["raw_class_technical_only"] if r["technical_status"] == "OK" else None)
                   for r in rows}
        data[s] = (bars, classes)
    return symbols, sessions, data


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("Kullanım:")[1].strip(), file=sys.stderr)
        return 2
    run_dir, out = Path(argv[0]), Path(argv[1])
    # Veri uygunluk kontrolü: bilinen sorunlu girdi dosyası varsa karşılaştırma BAŞLAMAZ;
    # sorunlu semboller sessizce atlanıp kalanlarla sonuç üretilmez.
    from app.research.data_issues.registry import check_input_files

    manifest_symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    data_check = check_input_files({s: run_dir / "inputs" / f"{s}_provider_ohlcv.csv" for s in manifest_symbols})
    if data_check["status"] == "BLOCKED":
        report = {"status": "BLOCKED_KNOWN_DATA_ISSUE", "blocked": data_check["blocked"],
                  "checked_files": data_check["checked_files"],
                  "note": "Politika karşılaştırması başlatılmadı; sorunlu semboller atlanarak sonuç üretilmez."}
        print(json.dumps(report, ensure_ascii=False, indent=1), file=sys.stderr)
        return 3
    out.mkdir(parents=True, exist_ok=False)
    backend = Path(__file__).resolve().parents[3]
    symbols, sessions, data = load(run_dir)
    result = evaluate(data, sessions)
    result_files = sorted((run_dir / "results").glob("*.json"))
    identity = {
        "scope": "NORMALIZE_KESIFSEL: düzeltilmiş fiyat, kesirli miktar; gerçek TL/tam lot/emir sonucu DEĞİL; "
                 "2024–2025 daha önce incelendi, bağımsız holdout DEĞİL; tüm dolumlar VARSAYIMSAL",
        "params": {"target_gross": TARGET, "stop": STOP, "trailing_C": TRAIL, "max_hold_sessions": MAX_HOLD,
                   "commission_each_side": C, "min_commission": 0, "extra_slippage": 0},
        "thresholds": "DEFAULT_THRESHOLDS (kayıtlı sınıflar); üretim config OKUNMADI",
        "code_sha256": _sha(backend / CODE_FILE),
        "contract_sha256": _sha(backend / CONTRACT_FILE),
        "universe_manifest_sha256": _sha(run_dir / "universe_manifest.json"),
        "fetch_manifest_sha256": _sha(run_dir / "inputs" / "fetch_manifest.json"),
        "results_files_sha256": hashlib.sha256("".join(_sha(p) for p in result_files).encode()).hexdigest(),
        "symbols": len(symbols), "sessions": [sessions[0].isoformat(), sessions[-1].isoformat()],
        "data_issue_check": data_check,
    }
    episodes = result.pop("episodes")
    (out / "result.json").write_text(json.dumps({"identity": identity, **result}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "episodes.jsonl").open("w", encoding="utf-8") as fh:
        for e in episodes:
            fh.write(json.dumps({k: v for k, v in e.items()}, ensure_ascii=False, default=str) + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
