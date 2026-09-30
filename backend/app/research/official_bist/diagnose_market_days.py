"""06.09.2024 ve 08.05.2025 piyasa geneli OHLC uyumsuzluğu — yerel teşhis (ağsız).

Kullanım (backend dizininden): python -m app.research.official_bist.diagnose_market_days <çıktı_klasörü>
* THYAO/AKBNK/FENER için ham bülten satırı, bağımsız başlık eşlemesi, ayrıştırıcı çıktısı ve Yahoo CSV metni.
* Tüm semboller için TEŞHİS amaçlı ölçüm: s = Yahoo açılış / resmî açılış; Yahoo H/L/C'nin s×resmî aralık içindeki
  konumu; hacim oranı (birim/düzeltme temeli doğrulanmadı). Bu ölçüm düzeltme veya onarım DEĞİLDİR.
* Komşu seanslar (bir önceki/sonraki) tarih kayması olasılığı için kontrol edilir.
"""

from __future__ import annotations

import csv
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

from app.research.official_bist.bulletin import parse_bulletin_text, read_bulletin_zip
from app.research.official_bist.run_universe_quality import UNIVERSE, index_bulletin, load_bulletins

DAYS = {"2024-09-06": ("2024-09-05", "2024-09-09"), "2025-05-08": ("2025-05-07", "2025-05-09")}
FOCUS = ("THYAO", "AKBNK", "FENER")
TOL = Decimal("1e-6")


def D(x) -> Decimal:
    return Decimal(str(x))


def independent_row(text: str, code: str) -> dict:
    """Ayrıştırıcıdan bağımsız: başlıkları kendimiz eşleyip satırı sözlük olarak döner."""
    lines = text.lstrip("﻿").splitlines()
    tr, en = lines[0].split(";"), lines[1].split(";")
    for line in lines[2:]:
        c = line.split(";")
        if len(c) > 1 and c[1].strip() == code:
            return {"raw_line": line, "by_header": {f"{tr[i].strip()} | {en[i].strip()}": c[i] for i in range(min(len(tr), len(c)))}}
    return {}


def diag(y: dict, o: dict) -> dict:
    yo, yh, yl, yc, yv = (D(y[k]) for k in ("Open", "High", "Low", "Close", "Volume"))
    oo, oh, ol, oc, ov = (D(o[k]) for k in ("open", "high", "low", "close", "total_traded_quantity_raw"))
    s = yo / oo
    rng = (oh - ol) * s
    return {"scale_from_open": str(s.quantize(Decimal("0.000001"))),
            "yahoo_high_le_scaled_official_high": yh <= oh * s * (1 + TOL), "yahoo_high_equals": abs(yh / (oh * s) - 1) <= TOL,
            "yahoo_low_ge_scaled_official_low": yl >= ol * s * (1 - TOL), "yahoo_low_equals": abs(yl / (ol * s) - 1) <= TOL,
            "yahoo_close_equals": abs(yc / (oc * s) - 1) <= TOL,
            "yahoo_close_position_in_official_range": str(((yc - ol * s) / rng).quantize(Decimal("0.0001"))) if rng > 0 else None,
            "official_close_position": str(((oc - ol) / (oh - ol)).quantize(Decimal("0.0001"))) if oh > ol else None,
            "volume_ratio_yahoo_over_official_info": str((yv / ov).quantize(Decimal("0.0001"))) if ov > 0 else None}


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    symbols = json.loads((UNIVERSE / "universe_manifest.json").read_text(encoding="utf-8"))["symbols"]
    fetch = json.loads((UNIVERSE / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    bulletins = load_bulletins()
    texts = {d: read_bulletin_zip(b["data"])[1] for d, b in bulletins.items() if d in {x for k, v in DAYS.items() for x in (k, *v)}}
    meta = {}
    for d in texts:
        b = bulletins[d]
        with zipfile.ZipFile(BACKEND_PATH(b["path"])) as z:
            info = z.infolist()[0]
            meta[d] = {"url": b["url"], "sha256": b["sha256"], "local": b["path"], "inner_file": info.filename,
                       "inner_mtime_not_finality_proof": "%04d-%02d-%02d %02d:%02d:%02d" % info.date_time, "inner_size": info.file_size}
    yahoo = {s: {r["Date"][:10]: r for r in csv.DictReader((UNIVERSE / "inputs" / f"{s}_provider_ohlcv.csv").open(encoding="utf-8"))}
             for s in symbols if (UNIVERSE / "inputs" / f"{s}_provider_ohlcv.csv").exists()}
    raw_text = {}
    for s in FOCUS:
        lines = (UNIVERSE / "inputs" / f"{s}_provider_ohlcv.csv").read_text(encoding="utf-8").splitlines()
        raw_text[s] = {d: next((l for l in lines if l.startswith(d)), None) for k, v in DAYS.items() for d in (v[0], k, v[1])}
    focus = {}
    for s in FOCUS:
        for day, (prev, nxt) in DAYS.items():
            for d in (prev, day, nxt):
                text = texts[d]
                parsed = parse_bulletin_text(text, f"{s}.E", d)
                ind = independent_row(text, f"{s}.E")
                ih = ind["by_header"]
                agrees = all(parsed.raw[k] == ih[h] for k, h in (("open", "ACILIS FIYATI | OPENING PRICE"), ("high", "EN YUKSEK FIYAT | HIGHEST PRICE"),
                                                                 ("low", "EN DUSUK FIYAT | LOWEST PRICE"), ("close", "KAPANIS FIYATI | CLOSING PRICE"),
                                                                 ("total_traded_quantity_raw", "TOPLAM ISLEM ADEDI | TOTAL TRADED VOLUME")))
                focus[f"{s}@{d}"] = {"trade_date_in_row": ih["TARIH | TRADE DATE"], "code_in_row": ih["ISLEM  KODU | INSTRUMENT SERIES CODE"],
                                     "parser_matches_independent_header_mapping": agrees,
                                     "official": {k: parsed.raw[k] for k in ("open", "high", "low", "close", "total_traded_quantity_raw", "previous_last_price")},
                                     "official_closing_session_price": ih.get("KAPANIS SEANSI FIYATI | CLOSING SESSION PRICE"),
                                     "official_vwap": ih.get("A.O.F | VWAP"),
                                     "yahoo_csv_line": raw_text[s][d],
                                     "diagnostic": diag(yahoo[s][d], parsed.raw)}
    # tüm semboller: iki gün + komşular için teşhis özeti
    agg = {}
    for day, (prev, nxt) in DAYS.items():
        for d in (prev, day, nxt):
            _, by_code = index_bulletin(texts[d], d)[0], index_bulletin(texts[d], d)[1]
            header = texts[d].lstrip("﻿").splitlines()[:2]
            rows = []
            for s in symbols:
                lines = by_code.get(f"{s}.E")
                y = yahoo.get(s, {}).get(d)
                if not lines or y is None:
                    continue
                p = parse_bulletin_text("\n".join(header + lines), f"{s}.E", d)
                if D(p.raw["open"]) <= 0 or D(p.raw["high"]) <= D(p.raw["low"]):
                    continue
                rows.append((s, diag(y, p.raw)))
            n = len(rows)
            cnt = lambda k: sum(1 for _, r in rows if r[k])
            vol_lower = sum(1 for _, r in rows if r["volume_ratio_yahoo_over_official_info"] and D(r["volume_ratio_yahoo_over_official_info"]) < 1 - TOL)
            agg[d] = {"symbols": n, "high_equal": cnt("yahoo_high_equals"), "high_le_official": cnt("yahoo_high_le_scaled_official_high"),
                      "low_equal": cnt("yahoo_low_equals"), "low_ge_official": cnt("yahoo_low_ge_scaled_official_low"),
                      "close_equal": cnt("yahoo_close_equals"), "yahoo_volume_lower_info": vol_lower,
                      "inside_official_range_all": sum(1 for _, r in rows if r["yahoo_high_le_scaled_official_high"] and r["yahoo_low_ge_scaled_official_low"])}
    result = {"note": "Teşhis ölçümü; fiyat onarımı değildir. ZIP iç dosya saati kesinleşme kanıtı sayılmaz.",
              "bulletin_meta": meta,
              "yahoo_fetch_meta": {s: {k: fetch[s].get(k) for k in ("status", "fetched_at", "fetch_start", "sha256", "price_adjustment")} for s in FOCUS},
              "yahoo_call_declared": "universe_review._yahoo_download: yf.Ticker(SYM.IS).history(start, end, interval='1d') — yfinance 1.5.2 varsayılanları (auto_adjust=True, repair=False)",
              "focus": focus, "aggregate": agg}
    (out / "local_diagnosis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"aggregate": agg}, ensure_ascii=False, indent=1))
    for k, v in focus.items():
        if k.split("@")[1] in DAYS:
            print(k, v["official"], v["official_closing_session_price"], v["official_vwap"], "| yahoo:", v["yahoo_csv_line"], "|", v["diagnostic"])
    return 0


def BACKEND_PATH(rel: str) -> Path:
    return Path(__file__).resolve().parents[3] / rel


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
