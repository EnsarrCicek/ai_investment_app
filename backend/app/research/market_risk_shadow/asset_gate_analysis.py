"""MARKET-RISK-1 — hisse kaynaklı engellerin ayrıştırılması ve tek bir araştırma
alternatifiyle karşılaştırma (ağsız; yalnızca kayıtlı universe sonuçlarını okur).

Alternatif politika (SONUÇLAR GÖRÜLDÜKTEN SONRA seçildi; bağımsız doğrulama veya
önceden belirlenmiş başarılı strateji DEĞİLDİR):
  "Piyasa riski bilgi/uyarı olarak kalır; araştırmadaki alım engeli yalnızca mevcut
   hisse risk kurallarından gelir."
  * ham sınıf yok            -> NO_RAW_CLASS (yeni karar üretilmez)
  * ham sınıf AL yönlü değil -> NOT_APPLICABLE
  * hisse riski tetiklendi   -> BLOCKED
  * hisse riski belirsiz     -> INDETERMINATE (endeks verisi eksikliği yok sayılmaz)
  * hisse riski tetiklenmedi -> ALLOWED_BY_ASSET_FILTER ("güvenli AL" anlamına gelmez)
Ham teknik kararlar ve kayıtlı risk durumları DEĞİŞTİRİLMEZ; üretim risk_gate'ine bağlı değildir.

Kullanım: python -m app.research.market_risk_shadow.asset_gate_analysis <universe_run_dir>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from app.research.market_risk_shadow.basket_review import BUY, HORIZONS, YEARS

TRIGGERED, CLEAR, UNDETERMINED = "RISK_TRIGGERED", "NO_DEFINED_RULE_TRIGGERED", "UNDETERMINED"
ALT_BLOCKED, ALT_INDETERMINATE, ALT_ALLOWED = "BLOCKED", "INDETERMINATE", "ALLOWED_BY_ASSET_FILTER"


def alternative_gate(row: dict) -> str:
    raw = row["raw_class_technical_only"]
    if raw is None:
        return "NO_RAW_CLASS"
    if raw not in BUY:
        return "NOT_APPLICABLE"
    return {TRIGGERED: ALT_BLOCKED, CLEAR: ALT_ALLOWED}.get(row["asset_risk"], ALT_INDETERMINATE)


def asset_rule_pattern(row: dict) -> str:
    rules = {k: v["triggered"] for k, v in row["asset_rules"].items()}
    sharp = rules["SHARP_DAILY_DECLINE_OBSERVED"] is True
    combo = rules["ASSET_PERIOD_DECLINE"] is True and rules["ASSET_UNDERPERFORMS_INDEX"] is True
    return "SHARP_AND_COMBO" if sharp and combo else ("SHARP_ONLY" if sharp else ("COMBO_ONLY" if combo else "NONE"))


def _pct(values, q):
    if not values:
        return "N/A"
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))], 4)


def outcome_stats(rows: list[dict]) -> dict:
    out = {"signals": len(rows)}
    for h in HORIZONS:
        vals = [r["price_move_after_close"][h] for r in rows if isinstance(r["price_move_after_close"].get(h), float)]
        out[h] = {"n": len(vals), "unavailable": len(rows) - len(vals),
                  "median": round(statistics.median(vals), 4) if vals else "N/A",
                  "negative_share": round(sum(v < 0 for v in vals) / len(vals), 4) if vals else "N/A"}
    worst = [r["t10_path"]["worst"] for r in rows if r["t10_path"]["status"] == "OK"]
    out["T+10_worst_close"] = {"n": len(worst), "median": round(statistics.median(worst), 4) if worst else "N/A",
                               "p10": _pct(worst, 0.10)}
    return out


def runs(rows: list[dict], predicate) -> list[tuple[int, int]]:
    """Aynı hissede ardışık beklenen seanslarda predicate'i sağlayan satır dizileri (başlangıç, bitiş)."""
    spans, start = [], None
    for i, r in enumerate(rows):
        if predicate(r):
            start = i if start is None else start
        elif start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(rows) - 1))
    return spans


def _prev(rows, i):
    if i == 0:
        return "BİLİNMİYOR (önceki seans kayıtta yok)"
    p = rows[i - 1]
    return {"session": p["session"], "raw_class": p["raw_class_technical_only"], "asset_risk": p["asset_risk"],
            "current_gate": p["shadow_gate"], "technical_status": p["technical_status"]}


def analyze(run_dir: Path) -> dict:
    symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    data = {s: json.loads((run_dir / "results" / f"{s}.json").read_text(encoding="utf-8"))["rows"] for s in symbols}
    report = {"alternative_policy": __doc__.split("Alternatif politika")[1].split("Kullanım:")[0].strip(), "years": {}}
    for year in YEARS:
        y = str(year)
        episodes, released_starts, blocked_rows, released_rows, still_blocked, transitions = [], [], [], {}, [], Counter()
        released_rows = {"BLOCKED->ALLOWED_BY_ASSET_FILTER": [], "INDETERMINATE->ALLOWED_BY_ASSET_FILTER": []}
        for s in symbols:
            rows = [r for r in data[s] if r["session"].startswith(y)]
            for r in rows:
                alt = alternative_gate(r)
                transitions[(r["shadow_gate"], alt)] += 1
                if alt == ALT_BLOCKED:
                    still_blocked.append(r | {"_symbol": s})
                key = f"{r['shadow_gate']}->{alt}"
                if key in released_rows:
                    released_rows[key].append(r | {"_symbol": s})
            # hisse kaynaklı engel dönemleri (mevcut politika: BLOCKED ve hisse riski tetiklenmiş)
            asset_blocked = lambda r: r["shadow_gate"] == "BLOCKED" and r["asset_risk"] == TRIGGERED
            for a, b in runs(rows, asset_blocked):
                start = rows[a]
                first_trigger = a
                while first_trigger > 0 and rows[first_trigger - 1]["asset_risk"] == TRIGGERED:
                    first_trigger -= 1
                blocked_rows += [rows[i] | {"_symbol": s} for i in range(a, b + 1)]
                episodes.append({
                    "symbol": s, "start": start["session"], "end": rows[b]["session"], "blocked_sessions": b - a + 1,
                    "technical_score": start["technical_score"], "raw_class": start["raw_class_technical_only"],
                    "market_risk": start["market_risk"], "rule_pattern": asset_rule_pattern(start),
                    "asset_measures": start["asset_measures"],
                    "first_risk_trigger_session": rows[first_trigger]["session"],
                    "risk_triggered_before_first_blocked_buy": first_trigger < a,
                    "previous_session": _prev(rows, a),
                    "moves_from_start_close": start["price_move_after_close"],
                    "t10_path": start["t10_path"],
                })
            released = lambda r: r["shadow_gate"] in ("BLOCKED", "INDETERMINATE") and alternative_gate(r) == ALT_ALLOWED
            released_starts += [rows[a] | {"_symbol": s} for a, _ in runs(rows, released)]
        start_rows = [e | {"price_move_after_close": e["moves_from_start_close"]} for e in episodes]
        per_symbol = Counter(r["_symbol"] for r in blocked_rows)
        top5 = per_symbol.most_common(5)
        report["years"][y] = {
            "asset_sourced_blocked_signals": len(blocked_rows),
            "asset_sourced_unique_symbols": len(per_symbol),
            "asset_sourced_episodes": len(episodes),
            "episode_start_dates_shared_by_multiple_symbols": {d: c for d, c in Counter(e["start"] for e in episodes).items() if c > 1},
            "symbols_with_multiple_episodes": {s: c for s, c in Counter(e["symbol"] for e in episodes).items() if c > 1},
            "rule_pattern_signals": dict(Counter(asset_rule_pattern(r) for r in blocked_rows)),
            "rule_pattern_episode_starts": dict(Counter(e["rule_pattern"] for e in episodes)),
            "episodes_risk_triggered_before_first_blocked_buy": sum(e["risk_triggered_before_first_blocked_buy"] for e in episodes),
            "episode_start_daily_return": {"median": round(statistics.median([e["asset_measures"]["daily_return_pct"] for e in episodes if e["asset_measures"]["daily_return_pct"] is not None]), 4) if episodes else "N/A"},
            "episode_start_period_return": {"median": round(statistics.median([e["asset_measures"]["period_return_pct"] for e in episodes if e["asset_measures"]["period_return_pct"] is not None]), 4) if episodes else "N/A"},
            "episode_starts_outcomes": outcome_stats(start_rows),
            "top5_asset_blocked_symbols": top5,
            "top5_share": round(sum(c for _, c in top5) / len(blocked_rows), 4) if blocked_rows else "N/A",
            "transitions_current_to_alternative": {f"{a}->{b}": c for (a, b), c in sorted(transitions.items())},
            "alternative_still_blocked": outcome_stats(still_blocked),
            "released": {k: outcome_stats(v) for k, v in released_rows.items()},
            "released_all": outcome_stats(released_rows["BLOCKED->ALLOWED_BY_ASSET_FILTER"] + released_rows["INDETERMINATE->ALLOWED_BY_ASSET_FILTER"]),
            "released_episode_starts": outcome_stats(released_starts),
            "episodes": episodes,
        }
    return report


if __name__ == "__main__":
    run_dir = Path(sys.argv[1])
    out = run_dir / "asset_gate_analysis.json"
    out.write_text(json.dumps(analyze(run_dir), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(out)
