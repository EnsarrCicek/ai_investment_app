"""BSOKE/FENER — resmî bülten fiyatları + tarih kesiti ile teknik skor/sınıfın yeniden hesaplanması (pilot; ağsız).

Kullanım (backend dizininden): python -m app.research.official_bist.recompute_technical <extension_klasörü>

Her T için: yalnızca T'ye kadar olan resmî ham satırlar -> `price_view_as_of` (yalnızca rights_start <= T olan
bedelli olaylar, araştırma dönüşümü) -> DEĞİŞTİRİLMEMİŞ `event_review.default_technical` (üretim teknik hattı:
seans normalizasyonu, süreklilik, bütünlük, kalite, compute_technical_analysis; Technical V2 dondurulmuş ağırlıkları)
-> ham sınıf `_classify(skor, DEFAULT_THRESHOLDS)`. Firestore config OKUNMAZ; tam DecisionEngine kararı DEĞİLDİR.
Karşılaştırma için endeks serisi eski çalıştırmayla aynı Yahoo XU100 dosyasıdır (V2 skorunda kullanılmıyor; yalnızca
RS alanı için). Hacim: bültenin TOPLAM ISLEM ADEDI alanı, dönüştürülmeden (V2 skoruna girmiyor).
Eski sonuçlar yalnızca karşılaştırma sütunudur; yeni hesaplamaya girdi DEĞİLDİR.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.engines.decision.engine import DEFAULT_THRESHOLDS, _classify
from app.engines.technical.history_window import compute_history_window
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow.event_review import (completion_moment, default_technical, frozen_v2_scoring,
                                                          load_saved_provider_csv, prepare_run_input)
from app.research.official_bist.rights_adjustment import AdjustmentError, RightsEvent, price_view_as_of
from app.services.market_data.trading_calendar import expected_trading_sessions

BACKEND = Path(__file__).resolve().parents[3]
UNIVERSE = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925"
EVENTS = {
    "BSOKE": [RightsEvent("BSOKE", date(2024, 12, 10), Decimal(3), Decimal("1.00"), "https://www.kap.org.tr/tr/Bildirim/1363968")],
    "FENER": [RightsEvent("FENER", date(2024, 12, 17), Decimal("1.5257627"), Decimal("6.00"), "https://www.kap.org.tr/tr/Bildirim/1365941"),
              RightsEvent("FENER", date(2025, 6, 30), Decimal(4), Decimal("1.00"), "https://www.kap.org.tr/tr/Bildirim/1452776")],
}
KNOWLEDGE = {  # KAP gönderim zamanı (yayım); yerel arşivin o gün var olduğunu göstermez
    "https://www.kap.org.tr/tr/Bildirim/1363968": "KAP gönderim 2024-12-09 12:58:56",
    "https://www.kap.org.tr/tr/Bildirim/1365941": "KAP gönderim 2024-12-16 14:31:48",
    "https://www.kap.org.tr/tr/Bildirim/1452776": "KAP gönderim 2025-06-27 16:22:03",
}
EXPLAINED_FLAGS = {("BSOKE", "2024-12-10"), ("FENER", "2024-12-17"), ("FENER", "2025-06-30")}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def to_frame(view_rows: list[dict]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(r["trade_date"]).tz_localize(ISTANBUL_TZ) for r in view_rows], name="Date")
    return pd.DataFrame({"Open": [float(r["derived_open"]) for r in view_rows], "High": [float(r["derived_high"]) for r in view_rows],
                         "Low": [float(r["derived_low"]) for r in view_rows], "Close": [float(r["derived_close"]) for r in view_rows],
                         "Volume": [float(r["total_traded_quantity_raw"]) for r in view_rows]}, index=idx)


def evaluate_symbol(sym: str, rows: list[dict], flags: list[dict], index_close: pd.Series, sessions: list[date],
                    events: list | None = None, explained_flags: set | None = None, include_components: bool = False) -> list[dict]:
    events = EVENTS.get(sym, []) if events is None else events
    explained_flags = EXPLAINED_FLAGS if explained_flags is None else explained_flags
    out = []
    first_row = date.fromisoformat(min(r["trade_date"] for r in rows))
    for t in sessions:
        rec = {"session": t.isoformat()}
        need_start = compute_history_window(completion_moment(t)).provider_request_start
        unexplained = [f for f in flags if need_start.isoformat() <= f["trade_date"] <= t.isoformat()
                       and (sym, f["trade_date"]) not in explained_flags]
        if need_start < first_row:
            rec |= {"status": "HESAPLANAMADI", "reason": f"RESMI_GECMIS_YETERSIZ: gereken {need_start}, eldeki ilk {first_row}"}
        elif unexplained:
            rec |= {"status": "HESAPLANAMADI", "reason": f"ACIKLANAMAYAN_KURUMSAL_ISLEM_ISARETI: {unexplained}"}
        else:
            try:
                view = price_view_as_of(rows, events, t, KNOWLEDGE)
            except AdjustmentError as exc:
                rec |= {"status": "HESAPLANAMADI", "reason": f"FIYAT_GORUNUMU: {exc}"}
                out.append(rec)
                continue
            df = to_frame(view["rows"])
            tech = default_technical(df, index_close[index_close.index <= t], t, sym, include_components=include_components)
            rec["applied_events"] = [f"{a['rights_start']} DK={Decimal(a['dk']):.6f}" for a in view["applied_events"]]
            if tech["status"] != "OK":
                rec |= {"status": "HESAPLANAMADI", "reason": f"TEKNIK_HAT: {tech['reason']}"}
            elif tech["technical_score"] is None:  # tüm bileşenler kullanılamaz; sınıf uydurulmaz
                rec |= {"status": "HESAPLANAMADI", "reason": "TEKNIK_SKOR_YOK"}
            else:
                rec |= {"status": "OK", "technical_score": tech["technical_score"],
                        "raw_class": _classify(float(tech["technical_score"]), DEFAULT_THRESHOLDS)}
                if include_components:
                    rec |= {k: tech[k] for k in ("components", "family_scores", "evidence_coverage", "confidence")}
        out.append(rec)
    return out


def main(ext: Path) -> int:
    ext = ext.resolve()
    req = json.loads((ext / "required_history.json").read_text(encoding="utf-8"))
    summary_ext = json.loads((ext / "extension_summary.json").read_text(encoding="utf-8"))
    entries = json.loads((UNIVERSE / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    index_df = prepare_run_input(load_saved_provider_csv(UNIVERSE / "inputs" / "XU100_provider_ohlcv.csv"),
                                 datetime.fromisoformat(entries["XU100"]["fetched_at"]))
    index_close = pd.Series(index_df["Close"].to_numpy(), index=[ts.date() for ts in index_df.index])
    weights, family, scoring_hash = frozen_v2_scoring()
    result = {"identity": {"engine_path": "event_review.default_technical (değiştirilmedi)", "scoring_config_hash": scoring_hash,
                           "family_weights": family, "indicator_weights": weights, "decision_thresholds": DEFAULT_THRESHOLDS,
                           "firestore_config_read": False, "benchmark": "Yahoo XU100 (eski çalıştırmayla aynı dosya; V2 skorunda yok)",
                           "benchmark_sha256": entries["XU100"]["sha256"],
                           "volume": "TOPLAM ISLEM ADEDI, dönüştürülmeden (V2 skorunda yok)",
                           "provider_label_note": "default_technical seans normalizasyonuna log için sabit 'yahoo_finance' etiketi veriyor; veri resmî bülten",
                           "not_full_decision_engine": True},
              "symbols": {}}
    for sym, spec in req["symbols"].items():
        raw_path = ext / f"{sym}_official_daily_extended.csv"
        rows = list(csv.DictReader(raw_path.open(encoding="utf-8")))
        before = sha(raw_path)
        sessions = expected_trading_sessions(date.fromisoformat(spec["evaluation"][0]), date.fromisoformat(spec["evaluation"][1]))
        new = evaluate_symbol(sym, rows, summary_ext["symbols"][sym]["flags"], index_close, sessions)
        assert sha(raw_path) == before  # ham girdi korunur
        old = {r["session"]: r for r in json.loads((UNIVERSE / "results" / f"{sym}.json").read_text(encoding="utf-8"))["rows"]}
        table = []
        for r in new:
            o = old.get(r["session"], {})
            old_cls = o.get("raw_class_technical_only")
            new_cls = r.get("raw_class")
            if r["status"] != "OK":
                why = "Yeni hesap yapılamadı: " + r["reason"]
            elif o.get("technical_status") != "OK":
                why = f"Eski hesap yoktu ({o.get('technical_status')}); yeni hesap resmî veriyle yapıldı"
            elif old_cls == new_cls:
                why = "Sınıf aynı; skor farkı fiyat kaynağı/ölçeğinden"
            else:
                why = "Sınıf değişti; eski girdi yapay ölçek kırılması içeren Yahoo serisi, yeni girdi resmî fiyat + tarih kesitli bedelli dönüşümü"
            table.append({"date": r["session"], "old_status": o.get("technical_status"), "old_score": o.get("technical_score"), "old_class": old_cls,
                          "new_status": r["status"], "new_score": round(r["technical_score"], 2) if r.get("technical_score") is not None else None,
                          "new_class": new_cls, "applied_events": r.get("applied_events", []), "explanation": why})
        ok = [x for x in table if x["new_status"] == "OK"]
        comparable = [x for x in ok if x["old_status"] == "OK"]
        result["symbols"][sym] = {
            "raw_input": str(raw_path.relative_to(BACKEND)), "raw_sha256": before, "evaluation_sessions": len(table),
            "computed": len(ok), "not_computed": {x["date"]: x["explanation"] for x in table if x["new_status"] != "OK"},
            "comparable_with_old": len(comparable), "class_changed": sum(x["old_class"] != x["new_class"] for x in comparable),
            "table": table}
    (ext / "technical_recompute.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for sym, s in result["symbols"].items():
        print("=====", sym, {k: v for k, v in s.items() if k not in ("table",)})
        for x in s["table"]:
            print(f"{x['date']} | eski {x['old_status']} {x['old_score']} {x['old_class']} | yeni {x['new_status']} {x['new_score']} {x['new_class']} | {x['applied_events']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
