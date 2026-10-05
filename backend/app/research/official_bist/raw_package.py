"""100 sembol — yereldeki resmî BIST bültenlerinden izlenebilir HAM fiyat paketi + teknik araştırma hazırlık durumu.

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.raw_package <çıktı_klasörü>
* Yeni indirme YOK; bültenler `run_universe_quality.load_bulletins` ile (hash doğrulamalı) okunur, satırlar mevcut
  `parse_bulletin_text` ile tam kod `{SYM}.E` üzerinden alınır. Tarihsel kod değişikliği tahminle eşlenmez.
* Fiyat temeli: resmî bültenin HAM seans fiyatı (OFFICIAL_RAW_SESSION_PRICE). Düzeltilmiş Yahoo serisiyle birleştirilmez.
* Eksik gün doldurulmaz; sıfır fiyat işlem fiyatı sayılmaz.
* Hazırlık: teknik hattın gerçek pencere gereksinimi (6 ay + 15 gün ön pay, seans sürekliliği, >= MIN_HISTORY_DAYS)
  ile ön kontrol. Kimliği/kurumsal işlem dayanağı doğrulanmamış sembol otomatik READY olmaz; işaret bulunmaması
  'kurumsal işlem yok' kanıtı DEĞİLDİR. Paket yatırımcı getirisi, tam lot maliyeti veya emir gerçekleşmesi kanıtı değildir.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.engines.technical.engine import MIN_HISTORY_DAYS
from app.engines.technical.history_window import compute_history_window
from app.research.market_risk_shadow.event_review import completion_moment
from app.research.official_bist.bulletin import BulletinError, parse_bulletin_text, read_bulletin_zip
from app.research.official_bist.extend_history import extra_fields
from app.research.official_bist.recompute_technical import EVENTS, EXPLAINED_FLAGS
from app.research.official_bist.run_universe_quality import REGISTRY, UNIVERSE, index_bulletin, load_bulletins
from app.services.market_data.trading_calendar import expected_trading_sessions

PRICE_BASIS = "OFFICIAL_RAW_SESSION_PRICE"
COLUMNS = ("trade_date", "share_code", "status", "open", "high", "low", "close", "previous_last_price",
           "total_traded_quantity_raw", "total_traded_value_raw", "corporate_action_flag", "suspended_flag",
           "price_basis", "source_file", "source_sha256")


def row_status(raw: dict | None) -> str:
    if raw is None:
        return "MISSING"
    try:
        o, h, l, c = (Decimal(raw[k]) for k in ("open", "high", "low", "close"))
    except (InvalidOperation, KeyError, TypeError):
        return "INVALID"
    if min(o, h, l, c) == 0:
        return "ZERO_PRICE"
    if min(o, h, l, c) < 0 or not (l <= o <= h and l <= c <= h):
        return "INVALID"
    return "OK"


def symbol_rows(code: str, days: list[str], indexed: dict, bulletins: dict) -> list[dict]:
    rows = []
    for d in days:
        header, by_code = indexed[d]
        lines = by_code.get(code, [])
        raw, ex, status = None, {}, "MISSING"
        if lines:
            text = "\n".join(header + lines)
            try:
                parsed = parse_bulletin_text(text, code, d)
                raw = parsed.raw if parsed else None
                ex = extra_fields(text, code)
                status = row_status(raw)
            except BulletinError:
                status = "PARSE_ERROR"
        rec = {k: "" for k in COLUMNS} | {"trade_date": d, "share_code": code, "status": status, "price_basis": PRICE_BASIS,
                                         "source_file": Path(bulletins[d]["path"]).name, "source_sha256": bulletins[d]["sha256"]}
        if raw is not None and status in ("OK", "ZERO_PRICE", "INVALID"):
            rec |= {k: raw[k] for k in ("open", "high", "low", "close", "previous_last_price", "total_traded_quantity_raw", "total_traded_value_raw")}
            rec |= {"corporate_action_flag": ex.get("OZSERMAYE HALI", ""), "suspended_flag": ex.get("GECICI DURDURMA", "")}
        rows.append(rec)
    return rows


def evaluable_sessions(rows: list[dict]) -> list[str]:
    """Teknik hattın pencere gereksinimi: [T-6ay-15g, T] beklenen seansların TAMAMI 'OK' ve analiz penceresinde
    >= MIN_HISTORY_DAYS satır. Kapsam başlangıcından önceyi gerektiren T değerlendirilemez (uydurulmaz)."""
    ok = {r["trade_date"] for r in rows if r["status"] == "OK"}
    first = date.fromisoformat(rows[0]["trade_date"])
    out = []
    for r in rows:
        t = date.fromisoformat(r["trade_date"])
        w = compute_history_window(completion_moment(t))
        if w.provider_request_start < first:
            continue
        need = expected_trading_sessions(w.provider_request_start, t)
        analysis = [s for s in need if s >= w.analysis_start]
        if need and all(s.isoformat() in ok for s in need) and len(analysis) >= MIN_HISTORY_DAYS:
            out.append(r["trade_date"])
    return out


# Teknik kullanımı belgelenmiş olarak incelenen seans aralıkları (yalnızca bunlar READY olabilir).
# Kaynak: official_bist/runs/history_extension_20260929 (required_history.json "evaluation", technical_recompute.json).
REVIEWED_WINDOWS = {"BSOKE": [("2024-11-22", "2024-12-20")], "FENER": [("2025-06-11", "2025-07-11")]}


def readiness(symbol: str, rows: list[dict], identity: dict | None, explained: set, events: list,
              reviewed_windows: list[tuple[str, str]] | None = None) -> dict:
    counts = Counter(r["status"] for r in rows)
    flags = [r["trade_date"] for r in rows if r["corporate_action_flag"]]
    evaluable = evaluable_sessions(rows) if counts["OK"] else []
    unexplained = [d for d in flags if (symbol, d) not in explained]
    blockers = []
    if counts["OK"] == 0:
        blockers.append("NO_OFFICIAL_ROWS_FOR_CODE")
    elif not evaluable:
        blockers.append("INSUFFICIENT_CONTINUOUS_HISTORY")
    if counts["OK"] and (counts["MISSING"] or counts["ZERO_PRICE"] or counts["INVALID"] or counts["PARSE_ERROR"]):
        blockers.append("MISSING_ZERO_OR_INVALID_SESSIONS_IN_SCOPE")
    if not identity or identity.get("result") != "MATCH":
        blockers.append("IDENTITY_NOT_VERIFIED")
    if unexplained:
        blockers.append("UNEXPLAINED_CORPORATE_ACTION_FLAGS")
    if unexplained and not events:
        blockers.append("RESEARCH_TRANSFORMATION_NOT_AVAILABLE")
    if not identity:
        blockers.append("CORPORATE_ACTION_SCAN_NOT_DONE")
    hard = {"NO_OFFICIAL_ROWS_FOR_CODE", "INSUFFICIENT_CONTINUOUS_HISTORY", "IDENTITY_NOT_VERIFIED",
            "UNEXPLAINED_CORPORATE_ACTION_FLAGS", "RESEARCH_TRANSFORMATION_NOT_AVAILABLE", "CORPORATE_ACTION_SCAN_NOT_DONE"}
    ready_sessions = [d for d in evaluable if any(a <= d <= b for a, b in (reviewed_windows or []))]
    if not (hard & set(blockers)) and not ready_sessions:
        blockers.append("REVIEW_SCOPE_NOT_DEFINED")  # READY hiçbir zaman incelenmemiş seanslara yayılmaz
        hard.add("REVIEW_SCOPE_NOT_DEFINED")
    status = "NOT_READY" if hard & set(blockers) else "READY_FOR_RESEARCH_WITH_LIMITS"
    return {"symbol": symbol, "raw_coverage": {k: counts.get(k, 0) for k in ("OK", "MISSING", "ZERO_PRICE", "INVALID", "PARSE_ERROR")},
            "first_ok": next((r["trade_date"] for r in rows if r["status"] == "OK"), None),
            "last_ok": next((r["trade_date"] for r in reversed(rows) if r["status"] == "OK"), None),
            "evaluable_sessions": len(evaluable), "evaluable_first": evaluable[0] if evaluable else None,
            "evaluable_last": evaluable[-1] if evaluable else None,
            "corporate_action_flags": flags,
            "flag_explanation": ("NONE_OBSERVED_NOT_PROOF" if not flags else "ALL_EXPLAINED" if not unexplained else "UNEXPLAINED"),
            "unexplained_flags": unexplained,
            "identity": identity["result"] if identity else "CODE_MATCH_ONLY_NOT_VERIFIED",
            "research_transformation": [f"{e.rights_start} n2={e.n2} R={e.subscription_price}" for e in events] or None,
            "technical_use_reviewed": bool(identity and identity.get("result") == "MATCH" and events),
            "ready_scope": reviewed_windows or [], "ready_sessions": ready_sessions if status != "NOT_READY" else [],
            "blockers": blockers, "status": status}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "symbols").mkdir()
    symbols = json.loads((UNIVERSE / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    bulletins = load_bulletins()
    days = list(bulletins)
    indexed = {d: index_bulletin(read_bulletin_zip(b["data"])[1], d) for d, b in bulletins.items()}
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    identities = {c["symbol"]: c for c in registry.get("identity_checks", [])}
    table, outputs = [], {}
    for sym in symbols:
        rows = symbol_rows(f"{sym}.E", days, indexed, bulletins)
        path = out / "symbols" / f"{sym}_official_raw.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        outputs[path.name] = sha(path)
        table.append(readiness(sym, rows, identities.get(sym), EXPLAINED_FLAGS, EVENTS.get(sym, []), REVIEWED_WINDOWS.get(sym)))
    blockers = Counter(b for t in table for b in t["blockers"])
    status = Counter(t["status"] for t in table)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "network_calls": 0, "price_basis": PRICE_BASIS,
                "scope": {"first": days[0], "last": days[-1], "sessions": len(days), "note": "Yalnızca bu aralık; 2024–2025'in tamamı değil."},
                "inputs": {"bulletins": {d: {"file": Path(b["path"]).name, "sha256": b["sha256"], "url": b["url"]} for d, b in bulletins.items()},
                           "registry_sha256": sha(REGISTRY), "universe_manifest_sha256": sha(UNIVERSE / "universe_manifest.json")},
                "outputs": outputs,
                "limits": ["Yatırımcı getirisi, tam lot maliyeti veya emir gerçekleşmesi kanıtı değildir.",
                           "Yeni dosya hash'leri known_issues.json'daki sorun kayıtlarını kaldırmaz; genel inceleme onayı verilmedi.",
                           "Kurumsal işlem işareti bulunmaması olay yok kanıtı değildir.",
                           "Hazırlık, teknik hattın pencere gereksiniminin ön kontrolüdür; hattın kendi kalite kontrolleri ayrıca çalışır."]}
    (out / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "readiness.csv").open("w", encoding="utf-8", newline="") as fh:
        cols = ["symbol", "status", "ok", "missing", "zero", "invalid", "evaluable_sessions", "evaluable_first", "evaluable_last",
                "flags", "flag_explanation", "identity", "research_transformation", "technical_use_reviewed", "blockers"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for t in table:
            c = t["raw_coverage"]
            w.writerow({"symbol": t["symbol"], "status": t["status"], "ok": c["OK"], "missing": c["MISSING"], "zero": c["ZERO_PRICE"],
                        "invalid": c["INVALID"] + c["PARSE_ERROR"], "evaluable_sessions": t["evaluable_sessions"],
                        "evaluable_first": t["evaluable_first"], "evaluable_last": t["evaluable_last"],
                        "flags": "|".join(t["corporate_action_flags"]), "flag_explanation": t["flag_explanation"], "identity": t["identity"],
                        "research_transformation": "|".join(t["research_transformation"] or []),
                        "technical_use_reviewed": t["technical_use_reviewed"], "blockers": "|".join(t["blockers"])})
    summary = {"symbols": len(table), "status": dict(status), "blocker_counts": dict(blockers),
               "data_available_symbols": sum(t["raw_coverage"]["OK"] > 0 for t in table),
               "technical_use_reviewed_symbols": [t["symbol"] for t in table if t["technical_use_reviewed"]],
               "symbols_with_flags": sum(bool(t["corporate_action_flags"]) for t in table),
               "symbols_with_evaluable_sessions": sum(t["evaluable_sessions"] > 0 for t in table), "table": table}
    (out / "readiness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "table"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
