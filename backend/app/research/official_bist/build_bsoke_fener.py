"""BSOKE/FENER resmî BIST günlük bülten ham fiyat veri seti (yalnızca iki olay penceresi).

Kullanım (backend dizininden): python -m app.research.official_bist.build_bsoke_fener <çıktı_klasörü> [<yeniden_kullanılacak_önceki_çalıştırma>]
* Önceden kaydedilmiş bültenler yeniden indirilmez (hash'i erişim kaydıyla doğrulanır).
* Eksikler yalnızca borsaistanbul.com ücretsiz bülten URL'sinden, sınırlı hız ve en fazla 2 denemeyle alınır.
* Erişilemeyen seans eksik kalır; Yahoo'dan doldurma / ileri taşıma / interpolasyon YOK.
* Fiyatlara katsayı uygulanmaz; eski dosyalar ve bilinen sorun kaydı değiştirilmez.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.research.official_bist.bulletin import BulletinError, ohlc_issues, parse_bulletin_text, read_bulletin_zip
from app.services.market_data.trading_calendar import expected_trading_sessions

BACKEND = Path(__file__).resolve().parents[3]
PRIOR = BACKEND / "app/research/position_exit/runs/exit_exp1_tail_official_20260929"
OLD_YAHOO = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925/inputs"
REGISTRY = BACKEND / "app/research/data_issues/known_issues.json"
PLAN = {"BSOKE": (date(2024, 11, 1), date(2024, 12, 20)), "FENER": (date(2025, 6, 2), date(2025, 7, 11))}
URL = "https://www.borsaistanbul.com/data/thb/{y}/{m:02d}/thb{y}{m:02d}{d:02d}1.zip"
PAUSE_SECONDS, MAX_ATTEMPTS = 1.5, 2
REL_TOL = Decimal("1e-6")  # Yahoo değerleri ~7 anlamlı basamak (float32 benzeri) taşıyor; önceden sabitlendi
CORPORATE_ACTIONS = [
    {"symbol": "BSOKE", "type": "BEDELLI_SERMAYE_ARTIRIMI", "ratio_pct": "300", "subscription_price_try": "1.00",
     "rights_start": "2024-12-10", "rights_end": "2024-12-24", "record_date": "2024-12-11", "payment_date": "2024-12-12",
     "spk_approval": "2024-12-05", "kap": "https://www.kap.org.tr/tr/Bildirim/1363968",
     "evidence_file": "app/research/position_exit/runs/exit_exp1_tail_official_20260929/kap_1363968.html"},
    {"symbol": "FENER", "type": "BEDELLI_SERMAYE_ARTIRIMI", "ratio_pct": "400", "subscription_price_try": "1.00",
     "rights_start": "2025-06-30", "rights_end": "2025-07-14", "record_date": "2025-07-01", "payment_date": "2025-07-02",
     "spk_approval": "2025-06-25", "kap": "https://www.kap.org.tr/tr/Bildirim/1452776",
     "evidence_file": "app/research/position_exit/runs/exit_exp1_tail_official_20260929/kap_1452776.html"},
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prior_log() -> dict:
    out = {}
    for line in (PRIOR / "access_log.tsv").read_text(encoding="utf-8").splitlines():
        url, ts, code, digest = line.split("\t")
        out[url] = {"accessed_at_utc": ts, "http": code, "sha256": digest}
    return out


def earlier_attempt_log(reuse_run: Path | None) -> dict:
    """Önceki (yol hatasıyla yarıda kalan) çalıştırmanın HTTP 200 dolumları: url -> son başarılı erişim zamanı."""
    if reuse_run is None:
        return {}
    m = json.loads((reuse_run / "source_manifest.json").read_text(encoding="utf-8"))
    out = {}
    for s in m["sessions"]:
        ok = [a["accessed_at_utc"] for a in s.get("attempts", []) if a.get("http") == 200]
        if ok:
            out[s["url"]] = {"accessed_at_utc": ok[-1], "requests_made": len(ok)}
    return out


def obtain(d: date, bulletins: Path, prior: dict, reuse_run: Path | None = None, reuse_log: dict | None = None) -> dict:
    url = URL.format(y=d.year, m=d.month, d=d.day)
    name = url.rsplit("/", 1)[1]
    if reuse_run is not None and url in (reuse_log or {}) and (reuse_run / "bulletins" / name).exists():
        rp = reuse_run / "bulletins" / name
        data = rp.read_bytes()
        ok = data[:2] == b"PK"
        return {"url": url, "local_file": str(rp.relative_to(BACKEND)), "sha256": sha(data),
                "accessed_at_utc": reuse_log[url]["accessed_at_utc"], "origin": "ONCEKI_YARIM_CALISTIRMADA_INDIRILDI",
                "integrity": "ZIP_SIGNATURE_OK" if ok else "NOT_ZIP", "requests_made_earlier": reuse_log[url]["requests_made"],
                "data": data if ok else None}
    p = PRIOR / name
    if p.exists() and url in prior:
        data = p.read_bytes()
        ok = sha(data) == prior[url]["sha256"]
        return {"url": url, "local_file": str(p.relative_to(BACKEND)), "sha256": sha(data), "accessed_at_utc": prior[url]["accessed_at_utc"],
                "origin": "ONCEKI_KAYIT_YENIDEN_INDIRILMEDI", "integrity": "SHA_MATCH" if ok else "SHA_MISMATCH", "data": data if ok else None}
    target = bulletins / name
    attempts = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ts = datetime.now(timezone.utc).isoformat()
        try:  # yalnızca AĞ adımı tekrar edilir
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40) as resp:
                data, code = resp.read(), resp.status
        except Exception as exc:  # noqa: BLE001 — sınırlı tekrar; başka kaynağa geçilmez
            attempts.append({"attempt": attempt, "accessed_at_utc": ts, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            time.sleep(PAUSE_SECONDS)
            continue
        attempts.append({"attempt": attempt, "accessed_at_utc": ts, "http": code, "bytes": len(data)})
        if code == 200 and data[:2] == b"PK":
            # Yerel yazma/yol hataları ağ hatası DEĞİLDİR: yakalanmaz, yeniden istek üretmez.
            target.write_bytes(data)
            local_file = str(target.resolve().relative_to(BACKEND))
            time.sleep(PAUSE_SECONDS)
            return {"url": url, "local_file": local_file, "sha256": sha(data), "accessed_at_utc": ts,
                    "origin": "YENI_INDIRME", "integrity": "ZIP_SIGNATURE_OK", "attempts": attempts, "data": data}
        time.sleep(PAUSE_SECONDS)
    return {"url": url, "local_file": None, "sha256": None, "accessed_at_utc": attempts[-1]["accessed_at_utc"],
            "origin": "ERISILEMEDI", "integrity": None, "attempts": attempts, "data": None}


def rel_equal(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= REL_TOL * abs(b)


def main(out: Path, reuse_run: Path | None = None) -> int:
    out = out.resolve()
    reuse_run = reuse_run.resolve() if reuse_run else None
    reuse_log = earlier_attempt_log(reuse_run)
    out.mkdir(parents=True, exist_ok=False)
    bulletins = out / "bulletins"
    bulletins.mkdir()
    prior = prior_log()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    inferred = {i["symbol"]: i["locally_inferred_scaled_window"] for i in registry["issues"]}
    manifest, summary = {"created_utc": datetime.now(timezone.utc).isoformat(), "sessions": []}, {"symbols": {}}
    for sym, (a, b) in PLAN.items():
        code = f"{sym}.E"
        sessions = expected_trading_sessions(a, b)
        rows, missing, problems = [], [], []
        old = {r["Date"][:10]: r for r in csv.DictReader((OLD_YAHOO / f"{sym}_provider_ohlcv.csv").open(encoding="utf-8"))}
        for d in sessions:
            src = obtain(d, bulletins, prior, reuse_run, reuse_log)
            data = src.pop("data")
            entry = {"symbol": sym, "trade_date": d.isoformat(), **src}
            manifest["sessions"].append(entry)
            if data is None:
                missing.append({"trade_date": d.isoformat(), "reason": src["origin"] if src["integrity"] != "SHA_MISMATCH" else "SHA_MISMATCH"})
                continue
            try:
                inner, text = read_bulletin_zip(data)
                parsed = parse_bulletin_text(text, code, d.isoformat())
            except BulletinError as exc:
                missing.append({"trade_date": d.isoformat(), "reason": f"PARSE_ERROR: {exc}"})
                continue
            entry["inner_file"] = inner
            if parsed is None:
                missing.append({"trade_date": d.isoformat(), "reason": "SYMBOL_ROW_NOT_IN_BULLETIN"})
                continue
            f = parsed.fields
            issues = ohlc_issues(f)
            if issues:
                problems.append({"trade_date": d.isoformat(), "issues": issues})
            rows.append({"trade_date": d.isoformat(), "instrument_code": f["instrument_code"], "instrument_name": f["instrument_name"],
                         "open": parsed.raw["open"], "high": parsed.raw["high"], "low": parsed.raw["low"], "close": parsed.raw["close"],
                         "previous_last_price": parsed.raw["previous_last_price"],
                         "total_traded_quantity_raw": parsed.raw["total_traded_quantity_raw"],
                         "total_traded_value_raw": parsed.raw["total_traded_value_raw"],
                         "missing_fields": "|".join(parsed.missing_fields), "ohlc_issues": "|".join(issues),
                         "source_url": src["url"], "source_sha256": src["sha256"], "accessed_at_utc": src["accessed_at_utc"],
                         "_f": f})
        # CSV (kaynak metin değerleri)
        cols = [k for k in rows[0] if k != "_f"] if rows else []
        with (out / f"{sym}_official_daily.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: v for k, v in r.items() if k != "_f"})
        # Eski Yahoo serisiyle tüm erişilen seanslarda karşılaştırma
        comp = []
        for r in rows:
            o = old.get(r["trade_date"])
            f = r["_f"]
            if o is None:
                comp.append({"trade_date": r["trade_date"], "status": "OLD_YAHOO_ROW_MISSING"})
                continue
            ratios = {k: Decimal(o[k.capitalize()]) / f[k] for k in ("open", "high", "low", "close")}
            qty_ratio = (Decimal(o["Volume"]) / f["total_traded_quantity_raw"]) if f["total_traded_quantity_raw"] else None
            equal = all(rel_equal(Decimal(o[k.capitalize()]), f[k]) for k in ("open", "high", "low", "close"))
            comp.append({"trade_date": r["trade_date"], "status": "PRICE_MATCH" if equal else "PRICE_DIFF",
                         "ratios": {k: str(v.quantize(Decimal("0.000001"))) for k, v in ratios.items()},
                         "yahoo_volume_over_official_quantity": str(qty_ratio.quantize(Decimal("0.000001"))) if qty_ratio is not None else None})
        diff_dates = [c["trade_date"] for c in comp if c["status"] == "PRICE_DIFF"]
        win = inferred[sym]
        summary["symbols"][sym] = {
            "expected_sessions": len(sessions), "obtained_rows": len(rows), "missing_sessions": missing,
            "duplicate_dates": sorted({r["trade_date"] for r in rows if [x["trade_date"] for x in rows].count(r["trade_date"]) > 1}),
            "ohlc_issues": problems,
            "price_diff_sessions": diff_dates,
            "price_diff_ratio_values": sorted({c["ratios"]["close"] for c in comp if c["status"] == "PRICE_DIFF"}),
            "inferred_window_from_registry": {"first": win["first"], "last": win["last"]},
            "inferred_window_supported_by_official": bool(diff_dates) and diff_dates == [
                s.isoformat() for s in sessions if win["first"] <= s.isoformat() <= win["last"]],
            "volume_ratio_on_diff_sessions": sorted({c["yahoo_volume_over_official_quantity"] for c in comp if c["status"] == "PRICE_DIFF"}),
            "volume_ratio_on_match_sessions_not_1": [c["trade_date"] for c in comp if c["status"] == "PRICE_MATCH"
                                                     and c["yahoo_volume_over_official_quantity"] not in ("1.000000", None)],
            "comparison": comp,
        }
    with (out / "corporate_actions.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(CORPORATE_ACTIONS[0]))
        w.writeheader()
        w.writerows(CORPORATE_ACTIONS)
    manifest["notes"] = ["Yalnızca işlem günündeki resmî fiyatlar; kurumsal işlem boyunca karşılaştırılabilir teknik seri veya ekonomik getiri DEĞİL.",
                         "total_traded_quantity_raw birimi doğrulanmadı; Yahoo Volume ile eşdeğer ilan edilmez.",
                         "total_traded_value_raw para birimi bülten satırında yok; doğrulanmadı."]
    (out / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    summary["scope"] = manifest["notes"][0]
    summary["tolerance"] = f"fiyat eşitliği göreli {REL_TOL} (Yahoo ~7 anlamlı basamak)"
    (out / "comparison_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for sym, s in summary["symbols"].items():
        print(sym, {k: v for k, v in s.items() if k != "comparison"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None))
