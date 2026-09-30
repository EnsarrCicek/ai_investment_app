"""100 sembollük dondurulmuş evren — yerelde bulunan resmî bültenlerle veri kalitesi kapsamı (ağsız).

Kullanım (backend dizininden): python -m app.research.official_bist.run_universe_quality <çıktı_klasörü>
* Bültenler: yalnızca diskte bulunan ve history_extension manifestiyle hash'i eşleşen dosyalar. Yeni indirme YOK.
* Her sembol için tam kod `{SYM}.E` (pay sınıfı); bulunamayan satır başka payla DOLDURULMAZ.
* Tolerans ve girdiler taramadan ÖNCE coverage_manifest.json'a yazılır.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from app.research.official_bist.bulletin import BulletinError, parse_bulletin_text, read_bulletin_zip
from app.research.official_bist.extend_history import extra_fields
from app.research.official_bist.universe_quality import REL_TOL, classify_symbol, compare_session

BACKEND = Path(__file__).resolve().parents[3]
R = BACKEND / "app/research"
BULLETIN_DIRS = [R / "position_exit/runs/exit_exp1_tail_official_20260929", R / "official_bist/runs/bsoke_fener_20260929/bulletins",
                 R / "official_bist/runs/history_extension_20260929/bulletins"]
MANIFEST = R / "official_bist/runs/history_extension_20260929/source_manifest.json"
UNIVERSE = R / "market_risk_shadow/runs/universe_20260925"
REGISTRY = R / "data_issues/known_issues.json"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_bulletins() -> dict[str, dict]:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))["sessions"]
    found = {}
    for d in BULLETIN_DIRS:
        for p in d.glob("thb*1.zip"):
            iso = f"{p.name[3:7]}-{p.name[7:9]}-{p.name[9:11]}"
            data = p.read_bytes()
            if iso in m and sha(data) == m[iso]["sha256"]:
                found.setdefault(iso, {"path": str(p.relative_to(BACKEND)), "sha256": sha(data), "data": data, "url": m[iso]["url"]})
    return dict(sorted(found.items()))


def index_bulletin(text: str, iso: str) -> tuple[list[str], dict[str, list[str]]]:
    lines = text.lstrip("﻿").splitlines()
    tr = [" ".join(h.split()) for h in lines[0].split(";")]
    di, ci = tr.index("TARIH"), tr.index("ISLEM KODU")
    by_code: dict[str, list[str]] = {}
    for line in lines[2:]:
        if not line.strip():
            continue
        c = line.split(";")
        if c[di].strip() != iso:
            raise BulletinError(f"bülten işlem tarihi beklenenden farklı: {c[di]} != {iso}")
        by_code.setdefault(c[ci].strip(), []).append(line)
    return lines[:2], by_code


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "symbols").mkdir()
    symbols = json.loads((UNIVERSE / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    fetch = json.loads((UNIVERSE / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    bulletins = load_bulletins()
    days = list(bulletins)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "network_calls": 0,
                "tolerance": {"relative": str(REL_TOL), "basis": "Yahoo ~7 anlamlı basamak (float32 kökenli); resmî ondalıklı metin; tarama öncesi sabitlendi"},
                "scope": {"bulletin_days": len(days), "first": days[0], "last": days[-1],
                          "continuity": "BIST takvimine göre bu aralıktaki tüm seanslar (dışı kapsam dışı; 2024-2025 tamamı doğrulanmadı)"},
                "bulletins": {d: {k: v for k, v in b.items() if k != "data"} for d, b in bulletins.items()},
                "yahoo_inputs": {s: fetch.get(s, {}).get("sha256") for s in symbols}, "symbols": symbols,
                "share_class_rule": "tam işlem kodu {SYM}.E"}
    (out / "coverage_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    indexed = {}
    for d, b in bulletins.items():
        _, text = read_bulletin_zip(b["data"])
        indexed[d] = (text, *index_bulletin(text, d))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    known = {}
    for i in registry["issues"]:
        known.setdefault(i["symbol"], []).append(i["issue_id"])

    table = []
    for sym in symbols:
        code = f"{sym}.E"
        ypath = UNIVERSE / "inputs" / f"{sym}_provider_ohlcv.csv"
        yahoo = {r["Date"][:10]: r for r in csv.DictReader(ypath.open(encoding="utf-8"))} if ypath.exists() else {}
        compared, flags, parse_errors = [], [], []
        for d in days:
            text, header, by_code = indexed[d]
            lines = by_code.get(code, [])
            off = None
            if lines:
                try:
                    parsed = parse_bulletin_text("\n".join(header + lines), code, d)  # mevcut ayrıştırıcı; tekrar -> hata
                except BulletinError as exc:
                    parse_errors.append({"date": d, "error": str(exc)})
                    parsed = None
                if parsed is not None:
                    f = parsed.raw
                    off = {"open": f["open"], "high": f["high"], "low": f["low"], "close": f["close"], "volume": f["total_traded_quantity_raw"]}
                    ex = extra_fields("\n".join(header + lines), code)
                    if ex.get("OZSERMAYE HALI") or ex.get("GECICI DURDURMA") not in ("", "0", None):
                        flags.append({"date": d, **ex})
            y = yahoo.get(d)
            yv = {"open": y["Open"], "high": y["High"], "low": y["Low"], "close": y["Close"], "volume": y["Volume"]} if y else None
            compared.append((d, compare_session(yv, off)))
        cls = classify_symbol(compared)
        vol_info = Counter(r.get("volume_ratio_info") for _, r in compared if r.get("status") == "COMPARED" and r["scale_is_one"] and r["fields_consistent"])
        detail = {"symbol": sym, "share_code": code, "yahoo_input_sha256": fetch.get(sym, {}).get("sha256"),
                  "existing_registry_issues": known.get(sym, []), **cls, "corporate_action_or_suspension_flags": flags,
                  "parse_errors": parse_errors,
                  "volume_ratio_info_on_unscaled_consistent_sessions": {k: v for k, v in vol_info.most_common(5)},
                  "sessions": {d: r for d, r in compared}}
        (out / "symbols" / f"{sym}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
        example = None
        focus = cls["field_inconsistency_dates"] or cls["scaled_dates"] or cls["missing_or_not_comparable"]
        if focus:
            r0 = dict(compared)[focus[0]]
            example = {"date": focus[0], **({"ratios": r0["ratios"]} if "ratios" in r0 else {"status": r0["status"]})}
        table.append({"symbol": sym, "matched": cls["compared"], "expected": len(days),
                      "missing": len(cls["missing_or_not_comparable"]), "findings": cls["findings"],
                      "field_inconsistency_dates": cls["field_inconsistency_dates"],
                      "scaled_sessions": len(cls["scaled_dates"]), "scale_segments": len(cls["scale_segments"]),
                      "flags": [f["date"] for f in flags], "existing_registry_issues": known.get(sym, []),
                      "example": example, "evidence": f"symbols/{sym}.json"})
    counts = Counter(f for t in table for f in t["findings"])
    summary = {"scope": manifest["scope"], "tolerance": manifest["tolerance"], "finding_counts": dict(counts),
               "notes": ["Hiçbir sınıf serinin tamamına doğruluk onayı vermez.", "Adaylar CONFIRMED kayda otomatik taşınmadı; BSOKE/FENER kayıtları değişmedi.",
                         "Ölçek farkı tek başına hata değildir (Yahoo düzeltilmiş, bülten ham).", "Hacim yalnızca bilgi; birim/düzeltme temeli doğrulanmadı.",
                         "Kurumsal işlem işareti bulunmaması olay yok kanıtı değildir."],
               "table": table}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"finding_counts": dict(counts), "days": len(days)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
