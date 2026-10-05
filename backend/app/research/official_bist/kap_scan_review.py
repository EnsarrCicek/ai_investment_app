"""KAP taramasından 27 sembollük kimlik / kurumsal işlem / kullanılabilir seans tablosu (ağsız).

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.kap_scan_review <çalıştırma_klasörü>
Kurallar (sonuçlardan önce sabitlendi):
* Yürürlük tarihi: (1) Borsa İstanbul 'Hak Kullanımı' duyurusunun yayın günü (ilgili hisse anılıyorsa),
  (2) aksi halde bildirimdeki Hak Kullanım / Kar Payı Ödeme / Rüçhan Başlangıç tarihi. Kayıt/ödeme tarihi yalnızca
  bu alanlar yoksa ve açıkça etiketliyse kullanılır. Duyuru (yayın) tarihi yürürlük tarihi sayılmaz.
* Nakit/pay temettüsü 'Ödenmeyecek' ise fiyat etkisi yok. Fiyatı etkileyebilecek olup tarihi belirlenemeyen olay sembolü
  ENGELLER (seans uydurulmaz).
* Kullanılabilir seans: teknik pencere ön kontrolünü geçen T ve [pencere başlangıcı, T] aralığında fiyat etkili olay YOK.
* READY yalnızca kimlik MATCH + tüm sorgular başarılı + belirsiz olay yok + en az bir kullanılabilir seans; yalnız bu veri
  sürümüne (ham CSV hash'i) ve incelenen aralığa bağlıdır. KAP tamlığı belgelenmediğinden durum WITH_LIMITS'tir.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from app.engines.technical.history_window import compute_history_window
from app.research.market_risk_shadow.event_review import completion_moment
from app.research.official_bist.kap_scan import EFFECT_RANGE, QUERY_RANGES, dmy
from app.research.official_bist.kap_scan import classify, extract_fields, notice_text, tr_lower
from app.research.official_bist.raw_package import evaluable_sessions
from app.services.market_data.trading_calendar import expected_trading_sessions

NO_PAY = "ödenmeyecek"


def event_effect(ev: dict) -> dict:
    """Tek bildirim -> {'price_affecting': bool|None, 'effective_date': str|None, 'kind': str, 'basis': str}."""
    cat = ev["category"]
    text_flags = tr_lower(" ".join(str(ev.get(k) or "") for k in ("subject", "summary")))
    labels, dates = ev.get("date_labels") or [], ev.get("rights_dates") or []
    labelled = dict(zip(labels, (dmy(d) for d in dates)))
    if ev.get("fetch_failed"):
        return {"price_affecting": None, "effective_date": None, "kind": cat, "basis": "NOTICE_FETCH_FAILED"}
    if cat == "DIVIDEND":
        cash = (ev.get("cash_dividend_payment") or "").lower()
        share = (ev.get("share_dividend_payment") or "").lower()
        if NO_PAY in cash and (not share or NO_PAY in share):
            return {"price_affecting": False, "effective_date": None, "kind": "DIVIDEND_NOT_PAID", "basis": "Ödenmeyecek"}
        if not cash and not share:
            return {"price_affecting": None, "effective_date": None, "kind": "DIVIDEND_UNPARSED", "basis": "ödeme alanı okunamadı"}
        ex = [dmy(x) for x in ev.get("dividend_ex_dates") or []]
        d = labelled.get("Hak Kullanım Tarihi") or labelled.get("Kar Payı Ödeme Tarihi") or (ex[0] if ex else None)
        return {"price_affecting": True, "effective_date": d, "effective_dates_all": ex, "kind": "DIVIDEND_PAID",
                "basis": "kar payı ödeme tablosu (kesinleşen/teklif hak kullanım tarihi)" if d else "tarih yok"}
    if cat == "RIGHTS_EXERCISE_NOTICE":
        if "BORSA" in (ev.get("kap_title") or "").upper() and "hak kullanım" in text_flags:
            hhmm = ev["publish"][11:16]
            day = date.fromisoformat(dmy(ev["publish"]))
            if hhmm >= "12:00":  # 2015/116 m.3: 16:30 listesi bir SONRAKİ iş günü içindir
                nxt = expected_trading_sessions(day + timedelta(days=1), day + timedelta(days=10))
                eff = nxt[0].isoformat() if nxt else None
            else:
                eff = day.isoformat()
            return {"price_affecting": True, "effective_date": eff, "kind": "BIST_RIGHTS_EXERCISE_DAY",
                    "basis": f"Borsa 'Hak Kullanımı' duyurusu ({hhmm}; öğleden sonra ise sonraki seans)"}
        return {"price_affecting": None, "effective_date": None, "kind": "RIGHTS_NOTICE_OTHER", "basis": "destekleyici; tarih türetilmedi"}
    if cat == "CAPITAL":
        d = labelled.get("Rüçhan Hakkı Kullanımı Başlangıç Tarihi") or labelled.get("Hak Kullanım Tarihi")
        if d:
            return {"price_affecting": True, "effective_date": d, "kind": "CAPITAL_CHANGE", "basis": "bildirim tarih etiketi"}
        if re.search(r"başvuru|yönetim kurulu kararı|fonun kullanım|izahname|tamamlan|tescil|esas sözleşme", text_flags):
            return {"price_affecting": False, "effective_date": None, "kind": "CAPITAL_PROCESS_NOTICE", "basis": "süreç bildirimi; yürürlük tarihi içermiyor"}
        return {"price_affecting": None, "effective_date": None, "kind": "CAPITAL_UNDETERMINED", "basis": "tarih etiketi yok"}
    if cat == "MERGER_OR_DEMERGER":
        return {"price_affecting": None, "effective_date": None, "kind": cat, "basis": "incelenmedi"}
    return {"price_affecting": None, "effective_date": None, "kind": cat, "basis": "bilinmeyen"}


def usable_sessions(evaluable: list[str], event_dates: list[str]) -> list[str]:
    out = []
    for t in evaluable:
        start = compute_history_window(completion_moment(date.fromisoformat(t))).provider_request_start.isoformat()
        if not any(start <= d <= t for d in event_dates):
            out.append(t)
    return out


def refresh_events(scan: dict, cache: Path) -> list[dict]:
    """Önbellekteki bildirimlerden (ağsız) güncel sınıflandırma ve alan çıkarımıyla olayları yeniden üretir."""
    out = []
    for ev in scan.get("events", []):
        cat = classify(ev["subject"], ev["summary"])
        if cat is None or cat == "TITLE_CHANGE":
            continue
        p = cache / f"notice_{ev['index']}.html"
        fields = extract_fields(notice_text(p.read_text(encoding="utf-8", errors="replace"))) if p.exists() else {"fetch_failed": True}
        out.append({**{k: ev[k] for k in ("publish", "index", "kap_title", "subject", "summary")}, "category": cat, **fields})
    return out


def review_symbol(scan: dict, rows: list[dict], raw_sha: str) -> dict:
    ident = scan.get("identity") or {}
    effects = []
    for ev in scan.get("events", []):
        e = event_effect(ev)
        effects.append({"index": ev["index"], "publish": ev["publish"], "subject": ev["subject"], **e})
    in_range = lambda d: d and EFFECT_RANGE[0] <= d <= EFFECT_RANGE[1]
    bist_days = {e["effective_date"] for e in effects if e["kind"] == "BIST_RIGHTS_EXERCISE_DAY"}
    for e in effects:  # kapsamdaki temettü tarihi Borsa 'Hak Kullanımı' duyurusuyla doğrulanmazsa kesin sayılmaz
        if e["kind"] == "DIVIDEND_PAID" and in_range(e["effective_date"]) and e["effective_date"] not in bist_days:
            e.update(price_affecting=None, kind="DIVIDEND_DATE_NOT_CORROBORATED",
                     basis=f"bildirim tarihi {e['effective_date']} Borsa duyurusuyla doğrulanmadı (öneri/değişiklik olabilir)")
    dated = sorted({e["effective_date"] for e in effects if e["price_affecting"] and in_range(e["effective_date"])})
    undetermined = [e for e in effects if (e["price_affecting"] is None or (e["price_affecting"] and not e["effective_date"]))
                    and (e["kind"] not in ("RIGHTS_NOTICE_OTHER",)) and EFFECT_RANGE[0] <= dmy(e["publish"]) <= "2025-07-31"]
    evaluable = evaluable_sessions(rows)
    usable = usable_sessions(evaluable, dated)
    blockers = []
    if ident.get("status") != "MATCH":
        blockers.append(f"IDENTITY_{ident.get('status', 'UNRESOLVED')}")
    if any(q["result"] is None for q in scan.get("queries", [])) or not scan.get("queries"):
        blockers.append("KAP_QUERY_INCOMPLETE")
    if undetermined:
        blockers.append("UNDETERMINED_CORPORATE_EVENT")
    if dated:
        blockers.append("PRICE_AFFECTING_EVENT_IN_SCOPE_NO_TRANSFORMATION")  # yalnızca etkilenen seanslar düşer
    if not usable:
        blockers.append("NO_USABLE_SESSION")
    hard = [b for b in blockers if b != "PRICE_AFFECTING_EVENT_IN_SCOPE_NO_TRANSFORMATION"]
    status = "READY_FOR_RESEARCH_WITH_LIMITS" if not hard else "NOT_READY"
    return {"symbol": scan["symbol"], "identity": ident, "bulletin_name": scan.get("bulletin_name"),
            "reviewed_publish_range": [QUERY_RANGES[0][0], QUERY_RANGES[-1][1]], "effect_range": list(EFFECT_RANGE),
            "events": effects, "price_affecting_effective_dates": dated, "undetermined_events": [e["index"] for e in undetermined],
            "coverage_limit": "KAP sorgu servisi belgelenmiş API değil; tamlık/sayfalama doğrulanamadı; başlık+ilgili bildirim içeriği. Olay bulunmaması yokluk kanıtı değil.",
            "evaluable_sessions": len(evaluable), "usable_sessions": usable if status != "NOT_READY" else [],
            "usable_count": len(usable) if status != "NOT_READY" else 0,
            "bound_to": {"raw_csv_sha256": raw_sha, "sessions_scope": list(EFFECT_RANGE)},
            "blockers": blockers, "status": status}


def main(run: Path) -> int:
    run = run.resolve()
    scans = json.loads((run / "scan_results.json").read_text(encoding="utf-8"))
    pkg = run.parent / "raw_package_20260930" / "symbols"
    out = {}
    for sym, scan in scans.items():
        p = pkg / f"{sym}_official_raw.csv"
        rows = list(csv.DictReader(p.open(encoding="utf-8")))
        scan = scan | {"events": refresh_events(scan, run / "kap")}
        out[sym] = review_symbol(scan, rows, hashlib.sha256(p.read_bytes()).hexdigest())
    (run / "review_27.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with (run / "review_27.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "identity", "reviewed_publish_range", "events_effective_dates", "coverage_limit", "usable_sessions", "blockers", "status"])
        for s, r in out.items():
            w.writerow([s, r["identity"].get("status"), "..".join(r["reviewed_publish_range"]), "|".join(r["price_affecting_effective_dates"]),
                        "KAP tamlığı belgelenmedi", r["usable_count"], "|".join(r["blockers"]), r["status"]])
    from collections import Counter
    print(json.dumps({"status": dict(Counter(r["status"] for r in out.values())),
                      "blockers": dict(Counter(b for r in out.values() for b in r["blockers"])),
                      "rows": {s: [r["identity"].get("status"), r["price_affecting_effective_dates"], r["usable_count"], r["status"]] for s, r in out.items()}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
