"""BSOKE/FENER için araştırma rüçhan dönüşümünü resmî ham veriye uygular (ağsız).

Kullanım (backend dizininden): python -m app.research.official_bist.build_rights_adjusted <çıktı_klasörü>
Girdi (değiştirilmez): official_bist/runs/bsoke_fener_20260929_v2/{SYM}_official_daily.csv, corporate_actions.csv
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.research.official_bist.rights_adjustment import SERIES_KIND, RightsEvent, adjust_rows, ohlc_consistent

BACKEND = Path(__file__).resolve().parents[3]
RAW = BACKEND / "app/research/official_bist/runs/bsoke_fener_20260929_v2"
OLD_YAHOO = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925/inputs"
REGISTRY = BACKEND / "app/research/data_issues/known_issues.json"
SOURCES = "app/research/official_bist/runs/rights_adjustment_20260929/sources"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    events = {r["symbol"]: r for r in csv.DictReader((RAW / "corporate_actions.csv").open(encoding="utf-8"))}
    windows = {i["symbol"]: i["locally_inferred_scaled_window"] for i in json.loads(REGISTRY.read_text(encoding="utf-8"))["issues"]
               if "locally_inferred_scaled_window" in i}  # kayıtta bu alanı taşımayan başka sorun türleri de var
    method = {"series_kind": SERIES_KIND,
              "formula": "Ft = (Fk + n2 × R) / (1 + n2); DK = Ft / Fk; hak kullanımından önceki seansların OHLC'si × DK",
              "primary_sources": {"method": "https://www.borsaistanbul.com/data/Genelge/gn414yeni.pdf",
                                  "application_date": "https://www.borsaistanbul.com/files/kural-seti-son-hali-2025.pdf (5.2 b)",
                                  "spot_circular_formula_unreadable": "https://borsaistanbul.com/data/Genelge/gn2013415.pdf",
                                  "access_log": f"{SOURCES}/access_log.tsv"},
              "not_official_series": True, "volume_not_transformed": True,
              "not_investor_return": "rüçhan hakkı değeri, 1 TL ek ödeme ve rüçhan satışı modellenmedi",
              "inputs": {}, "events": {}}
    explanation = {}
    for sym in ("BSOKE", "FENER"):
        raw_path = RAW / f"{sym}_official_daily.csv"
        rows = list(csv.DictReader(raw_path.open(encoding="utf-8")))
        e = events[sym]
        ev = RightsEvent(sym, date.fromisoformat(e["rights_start"]), Decimal(e["ratio_pct"]) / 100, Decimal(e["subscription_price_try"]), e["kap"])
        res = adjust_rows(rows, ev)
        assert all(ohlc_consistent(r, "derived_") for r in res["rows"])
        dst = out / f"{sym}_research_rights_adjusted.csv"
        with dst.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(res["rows"][0]))
            w.writeheader()
            w.writerows(res["rows"])
        method["inputs"][sym] = {"raw_file": str(raw_path.relative_to(BACKEND)), "raw_sha256": sha(raw_path),
                                 "corporate_actions_sha256": sha(RAW / "corporate_actions.csv"), "output": dst.name, "output_sha256": sha(dst)}
        method["events"][sym] = {k: v for k, v in res.items() if k != "rows"} | {"kap": e["kap"], "record_date": e["record_date"],
                                                                                "payment_date": e["payment_date"]}
        # açıklama tablosu: Yahoo kırılma başlangıcı, hak kullanımından önceki son seans, hak kullanımı başlangıcı
        old = {r["Date"][:10]: r for r in csv.DictReader((OLD_YAHOO / f"{sym}_provider_ohlcv.csv").open(encoding="utf-8"))}
        by = {r["trade_date"]: r for r in res["rows"]}
        ft = Decimal(res["ft"])
        table = []
        for label, d in (("YAHOO_KIRILMA_BASLANGICI", windows[sym]["first"]), ("HAK_KULLANIMI_ONCESI_SON_SEANS", res["fk_session"]),
                         ("HAK_KULLANIMI_BASLANGICI", res["rights_start"])):
            r, y = by[d], old[d]
            row = {"label": label, "trade_date": d, "raw_open": r["raw_open"], "raw_close": r["raw_close"], "theoretical_Ft": str(ft.quantize(Decimal("0.0001"))),
                   "derived_open": str(Decimal(r["derived_open"]).quantize(Decimal("0.0001"))),
                   "derived_close": str(Decimal(r["derived_close"]).quantize(Decimal("0.0001"))),
                   "old_yahoo_open": str(Decimal(y["Open"]).quantize(Decimal("0.0001"))),
                   "old_yahoo_close": str(Decimal(y["Close"]).quantize(Decimal("0.0001"))),
                   "old_yahoo_over_derived_close": str((Decimal(y["Close"]) / Decimal(r["derived_close"])).quantize(Decimal("0.000001")))}
            if label == "HAK_KULLANIMI_BASLANGICI":
                row["open_vs_Ft_pct"] = str(((Decimal(r["raw_open"]) / ft - 1) * 100).quantize(Decimal("0.01")))
                row["close_vs_Ft_pct"] = str(((Decimal(r["raw_close"]) / ft - 1) * 100).quantize(Decimal("0.01")))
                row["explanation"] = ("Ham fiyat korunur (katsayı 1). Açılış/kapanışın Ft'den sapması teorik referans dışındaki piyasa "
                                      "hareketidir; nedeni bu verilerle açıklanamaz.")
            else:
                row["explanation"] = ("Resmî ham fiyat ölçeksiz; araştırma dönüşümü DK ile ölçekler. Eski Yahoo değeri bu seansta "
                                      "türetilmiş değerle aynı ölçekte (oran ~1).")
            table.append(row)
        pre_break = [x for x in res["rows"] if x["trade_date"] < windows[sym]["first"]]
        explanation[sym] = {"table": table,
                            "yahoo_vs_derived_before_break": sorted({str((Decimal(old[x["trade_date"]]["Close"]) / Decimal(x["derived_close"])).quantize(Decimal("0.000001")))
                                                                     for x in pre_break}),
                            "note": ("Kırılma öncesi seanslarda eski Yahoo = resmî ham (ölçeksiz); türetilmiş seri bunları DK ile ölçekler. "
                                     "Yani Yahoo aynı DK'yı yalnızca kırılma başlangıcından hak kullanımına kadar uygulamış.")}
    (out / "method.json").write_text(json.dumps(method, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "event_explanation.json").write_text(json.dumps(explanation, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({s: {"events": method["events"][s], "table": explanation[s]["table"],
                          "yahoo_vs_derived_before_break": explanation[s]["yahoo_vs_derived_before_break"]} for s in ("BSOKE", "FENER")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
