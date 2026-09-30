"""BSOKE/FENER resmî bülten geçmişini teknik hattın gerektirdiği başlangıca kadar genişletir (devam edilebilir).

Kullanım (backend dizininden): python -m app.research.official_bist.extend_history <çıktı_klasörü>
* Gereken aralık `required_history.json`'dan okunur (indirmeden ÖNCE kodla hesaplanıp kaydedildi).
* Önce yeniden kullanım: (1) bu klasörde manifestte kayıtlı dosyalar (devam), (2) önceki çalıştırmada indirilmiş
  bültenler (erişim zamanı o manifestten), (3) hash'i doğrulanan en eski 8 bülten. Kalanlar `obtain()` ile
  sınırlı hız ve sınırlı denemeyle indirilir. Eksik seans Yahoo/ileri taşıma/interpolasyonla DOLDURULMAZ.
* Ham satırlar ayrı CSV'ye; bültenin 'OZSERMAYE HALI' (CORPORATE ACTION) ve 'GECICI DURDURMA' (SUSPENDED)
  alanları ayrıca kaydedilir (ayrıştırıcı değiştirilmedi).
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from app.research.official_bist import build_bsoke_fener as bb
from app.research.official_bist.bulletin import BulletinError, ohlc_issues, parse_bulletin_text, read_bulletin_zip
from app.services.market_data.trading_calendar import expected_trading_sessions

BACKEND = bb.BACKEND
V1 = BACKEND / "app/research/official_bist/runs/bsoke_fener_20260929"
EXTRA = {"OZSERMAYE HALI": "CORPORATE ACTION", "GECICI DURDURMA": "SUSPENDED"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extra_fields(text: str, code: str) -> dict:
    lines = text.lstrip("﻿").splitlines()
    tr = [" ".join(h.split()) for h in lines[0].split(";")]
    en = [" ".join(h.split()) for h in lines[1].split(";")]
    idx = {k: next((i for i in range(len(tr)) if tr[i] == k and en[i] == v), None) for k, v in EXTRA.items()}
    code_i = next(i for i in range(len(tr)) if tr[i] == "ISLEM KODU")
    for line in lines[2:]:
        c = line.split(";")
        if c[code_i].strip() == code:
            return {k: (c[i].strip() if i is not None else "HEADER_NOT_FOUND") for k, i in idx.items()}
    return {}


def main(out: Path) -> int:
    out = out.resolve()
    req = json.loads((out / "required_history.json").read_text(encoding="utf-8"))
    bulletins = out / "bulletins"
    bulletins.mkdir(exist_ok=True)
    manifest_path = out / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"sessions": {}}
    prior = bb.prior_log()
    v1_log = bb.earlier_attempt_log(V1)
    ranges = {s: (date.fromisoformat(v["required_start_with_pre_roll"]), date.fromisoformat(v["evaluation"][1]))
              for s, v in req["symbols"].items()}
    needed = sorted({d for a, b in ranges.values() for d in expected_trading_sessions(a, b)})
    counts = {"reused_this_folder": 0, "reused_v1": 0, "reused_prior": 0, "downloaded": 0, "failed": 0}
    blobs = {}
    for d in needed:
        key = d.isoformat()
        rec = manifest["sessions"].get(key)
        if rec and rec.get("local_file") and (BACKEND / rec["local_file"]).exists():
            data = (BACKEND / rec["local_file"]).read_bytes()
            if sha(data) == rec["sha256"]:
                blobs[key] = data
                counts["reused_this_folder"] += 1
                continue
        src = bb.obtain(d, bulletins, prior, V1, v1_log)
        data = src.pop("data")
        counts[{"ONCEKI_YARIM_CALISTIRMADA_INDIRILDI": "reused_v1", "ONCEKI_KAYIT_YENIDEN_INDIRILMEDI": "reused_prior",
                "YENI_INDIRME": "downloaded"}.get(src["origin"], "failed")] += 1
        manifest["sessions"][key] = src
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")  # devam için
        if data is not None:
            blobs[key] = data
    summary = {"needed_bulletin_days": len(needed), "counts": counts, "symbols": {}}
    for sym, (a, b) in ranges.items():
        rows, missing, flags = [], [], []
        for d in expected_trading_sessions(a, b):
            key = d.isoformat()
            data = blobs.get(key)
            if data is None:
                missing.append({"trade_date": key, "reason": "BULLETIN_NOT_OBTAINED"})
                continue
            try:
                _, text = read_bulletin_zip(data)
                parsed = parse_bulletin_text(text, f"{sym}.E", key)
            except BulletinError as exc:
                missing.append({"trade_date": key, "reason": f"PARSE_ERROR: {exc}"})
                continue
            if parsed is None:
                missing.append({"trade_date": key, "reason": "SYMBOL_ROW_NOT_IN_BULLETIN"})
                continue
            ex = extra_fields(text, f"{sym}.E")
            if ex.get("OZSERMAYE HALI") or (ex.get("GECICI DURDURMA") not in ("", "0", None)):
                flags.append({"trade_date": key, **ex})
            src = manifest["sessions"][key]
            rows.append({"trade_date": key, "instrument_code": parsed.fields["instrument_code"], "instrument_name": parsed.fields["instrument_name"],
                         **{k: parsed.raw[k] for k in ("open", "high", "low", "close", "previous_last_price",
                                                        "total_traded_quantity_raw", "total_traded_value_raw")},
                         "corporate_action_flag": ex.get("OZSERMAYE HALI", ""), "suspended_flag": ex.get("GECICI DURDURMA", ""),
                         "missing_fields": "|".join(parsed.missing_fields), "ohlc_issues": "|".join(ohlc_issues(parsed.fields)),
                         "source_url": src["url"], "source_sha256": src["sha256"], "accessed_at_utc": src["accessed_at_utc"]})
        with (out / f"{sym}_official_daily_extended.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        summary["symbols"][sym] = {"range": [a.isoformat(), b.isoformat()], "expected": len(expected_trading_sessions(a, b)),
                                   "obtained": len(rows), "missing": missing, "flags": flags,
                                   "ohlc_issue_rows": [r["trade_date"] for r in rows if r["ohlc_issues"]]}
    (out / "extension_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
