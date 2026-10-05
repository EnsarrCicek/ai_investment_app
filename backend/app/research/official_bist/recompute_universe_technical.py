"""İnceleme sürüm 2'nin izin verdiği semboller için resmî ham fiyatlarla tarih kesitli teknik skor (ağsız).

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.recompute_universe_technical <çıktı_klasörü>
* Yalnız review_v2.json'da READY_FOR_RESEARCH_WITH_LIMITS olan semboller ve onların `usable_sessions` listesi
  (ilk/son tarih aralığı değil). Ham CSV hash'i incelemedeki değerle eşleşmezse sembol ÇALIŞTIRILMAZ.
* BSOKE/FENER pilotundaki `recompute_technical.evaluate_symbol` (üretim teknik hattı + V2 ağırlıkları + DEFAULT_THRESHOLDS)
  aynen kullanılır; olay dönüşümü yok (kapsamda tarihli fiyat etkili olay yok). Eksik seans doldurulmaz, Yahoo ile
  birleştirilmez. Uygunluk 'kayıtlı taramanın sınırları altında keşifsel kullanım'dır; kurumsal işlem yokluğunun kanıtı değildir.
* Yalnız teknik skor, bileşenler, ham sınıf ve veri durumu; haber/makro yok; tam DecisionEngine kararı DEĞİLDİR.
* Eski Yahoo sonuçları yalnız ortak sembol-seanslarda karşılaştırma sütunudur; doğruluk referansı değildir.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.research.market_risk_shadow.event_review import frozen_v2_scoring, load_saved_provider_csv, prepare_run_input
from app.research.official_bist.recompute_technical import evaluate_symbol

BACKEND = Path(__file__).resolve().parents[3]
RUNS = BACKEND / "app/research/official_bist/runs"
REVIEW = RUNS / "kap_scan_27_20261001" / "review_v2.json"
PKG = RUNS / "raw_package_20260930" / "symbols"
UNIVERSE = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925"
CODE = ["app/research/official_bist/recompute_universe_technical.py", "app/research/official_bist/recompute_technical.py",
        "app/research/market_risk_shadow/event_review.py", "app/research/official_bist/kap_scan_review_v2.py",
        "app/research/official_bist/rights_adjustment.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def select_sessions(requested: list[str], allowed: list[str]) -> tuple[list[str], list[str]]:
    """İzin listesinde olmayan T reddedilir (aralık kontrolüyle aradaki engelli seanslar dahil edilmez)."""
    allow = set(allowed)
    return [t for t in requested if t in allow], [t for t in requested if t not in allow]


def ok_rows(path: Path) -> list[dict]:
    return [r for r in csv.DictReader(path.open(encoding="utf-8")) if r["status"] == "OK"]


def run_symbol(sym: str, review: dict, index_close: pd.Series, requested: list[str] | None = None) -> dict:
    raw = PKG / f"{sym}_official_raw.csv"
    if sha(raw) != review["bound_to"]["raw_csv_sha256"]:
        return {"symbol": sym, "status": "NOT_RUN", "reason": "RAW_CSV_HASH_MISMATCH"}
    allowed = review["usable_sessions"]
    accepted, rejected = select_sessions(requested if requested is not None else allowed, allowed)
    rows = ok_rows(raw)
    flags = [{"trade_date": r["trade_date"]} for r in rows if r["corporate_action_flag"]]
    recs = evaluate_symbol(sym, rows, flags, index_close, [date.fromisoformat(t) for t in accepted],
                           events=[], explained_flags=set(), include_components=True)
    return {"symbol": sym, "status": "RUN", "raw_csv_sha256": sha(raw), "accepted": accepted, "rejected": rejected, "records": recs}


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    review = json.loads(REVIEW.read_text(encoding="utf-8"))["symbols"]
    eligible = [s for s, r in review.items() if r["status"] == "READY_FOR_RESEARCH_WITH_LIMITS"]
    entries = json.loads((UNIVERSE / "inputs" / "fetch_manifest.json").read_text(encoding="utf-8"))
    index_df = prepare_run_input(load_saved_provider_csv(UNIVERSE / "inputs" / "XU100_provider_ohlcv.csv"),
                                 datetime.fromisoformat(entries["XU100"]["fetched_at"]))
    index_close = pd.Series(index_df["Close"].to_numpy(), index=[ts.date() for ts in index_df.index])
    _, _, scoring_hash = frozen_v2_scoring()
    results, summary = {}, {}
    for sym in eligible:
        res = run_symbol(sym, review[sym], index_close)
        old = {r["session"]: r for r in json.loads((UNIVERSE / "results" / f"{sym}.json").read_text(encoding="utf-8"))["rows"]}
        for rec in res.get("records", []):
            o = old.get(rec["session"])
            rec["old_yahoo"] = ({"status": o["technical_status"], "score": o["technical_score"], "class": o["raw_class_technical_only"]}
                                if o else None)
        recs = res.get("records", [])
        okr = [r for r in recs if r["status"] == "OK"]
        common = [r for r in okr if r["old_yahoo"] and r["old_yahoo"]["status"] == "OK"]
        summary[sym] = {"candidate_sessions": review[sym]["evaluable_sessions"], "allowed_sessions": len(review[sym]["usable_sessions"]),
                        "computed": len(okr), "not_computed": len(recs) - len(okr),
                        "blocked_by_review": review[sym]["evaluable_sessions"] - len(review[sym]["usable_sessions"]),
                        "rejected_requests": len(res.get("rejected", [])),
                        "range": [okr[0]["session"], okr[-1]["session"]] if okr else None,
                        "common_with_old": len(common), "class_changed_vs_old": sum(r["raw_class"] != r["old_yahoo"]["class"] for r in common),
                        "max_abs_score_diff_vs_old": round(max((abs(r["technical_score"] - r["old_yahoo"]["score"]) for r in common), default=0), 4),
                        "not_computed_reasons": sorted({r.get("reason", "")[:60] for r in recs if r["status"] != "OK"})}
        results[sym] = res
    identity = {"created": datetime.now().astimezone().isoformat(), "network_calls": 0, "scoring_config_hash": scoring_hash,
                "decision_thresholds": "DEFAULT_THRESHOLDS (kod içi); Firestore config okunmadı",
                "code_sha256": {c: sha(BACKEND / c) for c in CODE}, "review_v2_sha256": sha(REVIEW),
                "benchmark": "Yahoo XU100 (RS alanı için; V2 skorunda yok)", "benchmark_sha256": entries["XU100"]["sha256"],
                "eligible_symbols": eligible,
                "scope": "keşifsel; kayıtlı KAP taramasının sınırları altında; tam DecisionEngine kararı değil; getiri/sinyal başarısı değil"}
    (out / "technical_results.json").write_text(json.dumps({"identity": identity, "results": results}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"identity": identity, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
