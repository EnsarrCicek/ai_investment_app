"""MARKET-RISK-1 — kayıtlı sepet sonuçlarından BLOCKED dönem analizi (ağsız, hesap değişmez).

Dönem tanımı: aynı hissede ARDIŞIK beklenen seanslarda kapı sonucu BLOCKED olan ham
AL (BUY/WEAK_BUY) günleri. Eksik gün (ham sınıf yok) veya başka herhangi bir kapı
sonucu dönemi keser. Dönemler pozisyon veya işlem DEĞİLDİR; farklı hisselerin aynı
tarihli dönemleri ortak piyasa şokunu paylaşır, ileri ufuklar örtüşür -> bağımsız değildir.

Kullanım: python -m app.research.market_risk_shadow.episode_analysis <sonuç_klasörü> [girdi_klasörü]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pandas as pd

from app.research.market_risk_shadow.basket_review import BUY, HORIZONS, SYMBOLS, blocked_episodes
from app.research.market_risk_shadow.event_review import load_saved_provider_csv


def _rules(r: dict, key: str) -> dict:
    return {name: {"status": v["status"], "triggered": v["triggered"], "measure": v["measure"]} for name, v in r[key].items()}


def _next_allowed(rows: list[dict], end_index: int) -> dict:
    after = rows[end_index + 1:]
    for i, r in enumerate(after):
        if r["shadow_gate"] == "ALLOWED":
            between = sorted({f'{x["shadow_gate"]}/{x["raw_class_technical_only"]}' for x in after[:i]})
            return {"date": r["session"], "sessions_after_end": i + 1, "in_between": between}
    return {"date": None, "reason": "değerlendirme dönemi içinde sonraki ALLOWED günü yok"}


def _closes(folder: Path, symbol: str) -> pd.Series:
    df = load_saved_provider_csv(folder / f"{symbol}_provider_ohlcv.csv")
    return pd.Series(df["Close"].to_numpy(), index=[ts.date().isoformat() for ts in df.index])


def _stats(values):
    if not values:
        return {"n": 0, "median": "N/A", "negative_share": "N/A"}
    return {"n": len(values), "median": round(statistics.median(values), 4),
            "negative_share": round(sum(v < 0 for v in values) / len(values), 4)}


def analyze(folder: Path, inputs_folder: Path | None = None) -> dict:
    inputs_folder = inputs_folder or folder
    rows = {s: json.loads((folder / f"{s}_daily_review.json").read_text(encoding="utf-8")) for s in SYMBOLS}
    episodes = []
    for s, rs in rows.items():
        index = {r["session"]: i for i, r in enumerate(rs)}
        for e in blocked_episodes(rs):
            start_i = index[e["start"]]
            end_i = start_i + e["length"] - 1
            start = rs[start_i]
            episodes.append({
                "symbol": s, "start": e["start"], "end": rs[end_i]["session"], "blocked_sessions": e["length"],
                "start_technical_score": start["technical_score"], "start_raw_class": start["raw_class_technical_only"],
                "market_risk": start["market_risk"], "market_rules": _rules(start, "market_rules"),
                "asset_risk": start["asset_risk"], "asset_rules": _rules(start, "asset_rules"),
                "asset_risk_during_episode": sorted({rs[i]["asset_risk"] for i in range(start_i, end_i + 1)}),
                "market_risk_during_episode": sorted({rs[i]["market_risk"] for i in range(start_i, end_i + 1)}),
                "moves_from_start_close": start["price_move_after_close"],
                "next_allowed": _next_allowed(rs, end_i),
            })
    overlaps = [(a["symbol"], a["start"], a["end"], b["symbol"], b["start"], b["end"])
                for i, a in enumerate(episodes) for b in episodes[i + 1:]
                if a["symbol"] != b["symbol"] and a["start"] <= b["end"] and b["start"] <= a["end"]]

    def year_block(symbols):
        buy = [r for s in symbols for r in rows[s] if r["session"].startswith("2025") and r["raw_class_technical_only"] in BUY]
        blocked = [r for r in buy if r["shadow_gate"] == "BLOCKED"]
        allowed = [r for r in buy if r["shadow_gate"] == "ALLOWED"]
        eps = [e for e in episodes if e["symbol"] in symbols and e["start"].startswith("2025")]
        out = {"blocked_signals": len(blocked), "blocked_episodes": len(eps)}
        for name, grp in (("blocked", blocked), ("allowed", allowed)):
            out[name] = {h: _stats([r["price_move_after_close"][h] for r in grp
                                    if isinstance(r["price_move_after_close"].get(h), float)]) for h in HORIZONS}
        return out

    concentration = {"full_basket_2025": year_block(SYMBOLS),
                     "without_ASELS_2025": year_block([s for s in SYMBOLS if s != "ASELS"])}

    long_ep = max((e for e in episodes if e["symbol"] == "ASELS"), key=lambda e: e["blocked_sessions"])
    asels, xu = _closes(inputs_folder, "ASELS"), _closes(inputs_folder, "XU100")
    asels_rows = {r["session"]: r for r in rows["ASELS"]}
    days = [d for d in asels.index if long_ep["start"] <= d <= long_ep["end"]]
    path = [{"session": d,
             "ASELS_vs_start_pct": round((asels[d] / asels[long_ep["start"]] - 1) * 100, 4),
             "XU100_vs_start_pct": round((xu[d] / xu[long_ep["start"]] - 1) * 100, 4) if d in xu.index and long_ep["start"] in xu.index else None,
             "market_risk": asels_rows[d]["market_risk"],
             "market_triggered_rules": [k for k, v in asels_rows[d]["market_rules"].items() if v["triggered"]],
             "asset_risk": asels_rows[d]["asset_risk"],
             "asset_triggered_rules": [k for k, v in asels_rows[d]["asset_rules"].items() if v["triggered"]],
             "gate": asels_rows[d]["shadow_gate"]} for d in days]
    low_day = min(days, key=lambda d: asels[d])
    return {"episodes": episodes, "overlapping_episodes": overlaps, "asels_concentration": concentration,
            "asels_long_episode": {"start": long_ep["start"], "end": long_ep["end"],
                                   "lowest_close_day_in_hindsight": low_day,
                                   "lowest_close_vs_start_pct": round((asels[low_day] / asels[long_ep["start"]] - 1) * 100, 4),
                                   "path": path}}


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    result = analyze(folder, Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    (folder / "episode_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(folder / "episode_analysis.json")
