"""MARKET-RISK-1 — AL sinyallerinde sonradan gelen sert düşüşlerin yakalanma/kaçırılma kapsamı
(betimsel, ağsız; kayıtlı universe_20260925 girdileri ve sonuçlarını okur).

Sonuç tanımı (sonuçlar görüldükten SONRA seçilmiş araştırma tanımı; önceden kilitlenmiş
doğrulama DEĞİL): "izleyen 10 seansta sert düşüş" = T kapanışına göre T+1..T+10
(beklenen BIST seansları) kapanışlarından en az birinin %10 veya daha fazla aşağıda olması.
  * mevcut kapanışlardan biri eşiği aşıyorsa         -> DROP (eksik bar olsa bile kesin)
  * 10 seansın hepsi mevcut ve hiçbiri eşiği aşmıyor -> NO_DROP
  * aksi (eksik bar / henüz tamamlanmamış ufuk)      -> UNDETERMINED
T günündeki kayıp sonuca girmez; risk durumu yalnızca T'ye kadar bilinen kayıtlı sonuçtan gelir.

Kullanım: python -m app.research.market_risk_shadow.sharp_drop_coverage <universe_run_dir>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from app.engines.risk.shadow_inputs import MEASURE_DECIMALS
from app.research.market_risk_shadow.asset_gate_analysis import ALT_ALLOWED, ALT_BLOCKED, alternative_gate
from app.research.market_risk_shadow.basket_review import BUY, YEARS
from app.research.market_risk_shadow.event_review import load_saved_provider_csv
from app.research.market_risk_shadow.universe_review import _calendar_end
from app.services.market_data.trading_calendar import expected_trading_sessions

DROP_PCT = -10.0
HORIZON = 10
DROP, NO_DROP, UNDETERMINED = "DROP", "NO_DROP", "UNDETERMINED"


def forward_drop_outcome(closes_by_date: dict, session: date, calendar: list[date]) -> str:
    if session not in closes_by_date:
        return UNDETERMINED
    i = calendar.index(session)
    window = calendar[i + 1: i + 1 + HORIZON]
    base = closes_by_date[session]
    available = [closes_by_date[d] for d in window if d in closes_by_date]
    # Eşik dahil; karşılaştırmadan önce risk ölçümleriyle aynı hassasiyete yuvarlanır.
    if any(round((c / base - 1) * 100, MEASURE_DECIMALS) <= DROP_PCT for c in available):
        return DROP
    if len(window) == HORIZON and len(available) == HORIZON:
        return NO_DROP
    return UNDETERMINED


def current_gate(row: dict) -> str:
    return {"BLOCKED": "BLOCKED", "ALLOWED": "ALLOWED", "INDETERMINATE": "INDETERMINATE"}[row["shadow_gate"]]


def asset_filter_gate(row: dict) -> str:
    alt = alternative_gate(row)
    return {ALT_BLOCKED: "BLOCKED", ALT_ALLOWED: "ALLOWED"}.get(alt, "INDETERMINATE")


def first_days(rows: list[dict]) -> list[dict]:
    """Takvime göre kesintisiz ham AL dizilerinin yalnızca ilk günü (rows = ardışık beklenen seanslar)."""
    out, previous_buy = [], False
    for r in rows:
        is_buy = r["raw_class_technical_only"] in BUY
        if is_buy and not previous_buy:
            out.append(r)
        previous_buy = is_buy
    return out


def _ratio(num: int, den: int) -> dict:
    return {"num": num, "den": den, "share": round(num / den, 4) if den else "N/A"}


def coverage_table(items: list[tuple[str, str, bool]]) -> dict:
    """items: (gate, outcome, sharp_rule_at_T)."""
    cells = Counter((g, o) for g, o, _ in items)
    gates = ("BLOCKED", "ALLOWED", "INDETERMINATE")
    determined = [(g, o, s) for g, o, s in items if o != UNDETERMINED]
    blocked_det = [x for x in determined if x[0] == "BLOCKED"]
    drops = [x for x in determined if x[1] == DROP]
    return {
        "total": len(items),
        "cells": {o: {g: cells[(g, o)] for g in gates} for o in (DROP, NO_DROP, UNDETERMINED)},
        "outcome_undetermined": _ratio(sum(1 for x in items if x[1] == UNDETERMINED), len(items)),
        "blocked_that_later_dropped": _ratio(sum(1 for x in blocked_det if x[1] == DROP), len(blocked_det)),
        "drops_that_were_blocked": _ratio(sum(1 for x in drops if x[0] == "BLOCKED"), len(drops)),
        "drops_allowed": _ratio(sum(1 for x in drops if x[0] == "ALLOWED"), len(drops)),
        "drops_gate_indeterminate": _ratio(sum(1 for x in drops if x[0] == "INDETERMINATE"), len(drops)),
        "blocked_drops_with_sharp_rule_at_T": _ratio(sum(1 for x in drops if x[0] == "BLOCKED" and x[2]), sum(1 for x in drops if x[0] == "BLOCKED")),
        "drops_with_no_asset_warning_at_T": _ratio(sum(1 for x in drops if not x[2] and x[0] != "BLOCKED"), len(drops)),
    }


def analyze(run_dir: Path) -> dict:
    symbols = json.loads((run_dir / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    entries = json.loads((run_dir / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    calendar = expected_trading_sessions(date(YEARS[0], 1, 1), _calendar_end(entries))
    report = {"definition": __doc__.split("Sonuç tanımı")[1].split("Kullanım:")[0].strip(),
              "calendar_end": calendar[-1].isoformat(), "years": {}}
    items = {(y, view, policy): [] for y in YEARS for view in ("all_days", "first_day_of_buy_run") for policy in ("current_combined_gate", "asset_filter_alternative")}
    for s in symbols:
        rows = json.loads((run_dir / "results" / f"{s}.json").read_text(encoding="utf-8"))["rows"]
        if not rows:
            continue
        df = load_saved_provider_csv(run_dir / "inputs" / f"{s}_provider_ohlcv.csv")
        closes = {ts.date(): float(v) for ts, v in df["Close"].items() if v == v}
        firsts = {r["session"] for r in first_days(rows)}
        for r in rows:
            if r["raw_class_technical_only"] not in BUY:
                continue
            outcome = forward_drop_outcome(closes, date.fromisoformat(r["session"]), calendar)
            sharp = r["asset_rules"]["SHARP_DAILY_DECLINE_OBSERVED"]["triggered"] is True
            year = int(r["session"][:4])
            for view in ("all_days", "first_day_of_buy_run"):
                if view == "first_day_of_buy_run" and r["session"] not in firsts:
                    continue
                items[(year, view, "current_combined_gate")].append((current_gate(r), outcome, sharp))
                items[(year, view, "asset_filter_alternative")].append((asset_filter_gate(r), outcome, sharp))
    for (year, view, policy), its in items.items():
        report["years"].setdefault(str(year), {}).setdefault(view, {})[policy] = coverage_table(its)
    return report


if __name__ == "__main__":
    run_dir = Path(sys.argv[1])
    out = run_dir / "sharp_drop_coverage.json"
    out.write_text(json.dumps(analyze(run_dir), ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)
