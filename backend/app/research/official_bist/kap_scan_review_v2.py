"""KAP taraması değerlendirmesi — SÜRÜM 2 (ağsız; yalnız önbellek). Sürüm 1 çıktıları korunur.

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.kap_scan_review_v2 <çalıştırma_klasörü>

Sürüm 1'e göre düzeltmeler:
1. Kayıtlı sorgu sonuçlarının TAMAMI güncel `classify` ile yeniden sınıflandırılır (yalnız önceden seçilenler değil);
   içerik önbellekte yoksa MISSING_CONTENT -> belirsiz.
2. Belirsiz olaylar yayın tarihine göre SÜZÜLMEZ. Yalnız kanıtlı gerekçelerle ayrılır:
   - OUT_OF_SCOPE_PUBLISHED_AFTER_RANGE: yayın tarihi yürürlük kapsamının sonundan sonra (etki duyurudan önce olamaz);
   - SUPERSEDED_DIVIDEND: aynı sembolde sonraki (<=120 gün) kar payı bildirimi kesinleşen tarihleri veya 'ödenmeyecek' verir;
   - CORROBORATED_BY_EXPLICIT_LIST: Borsa sabah duyurusu / MKK hak kullanım duyurusu, açık tarihli Borsa listesiyle eşleşir;
   - EXECUTION_FOUND: bedelsiz/bedelli süreç bildiriminden sonra tarihli uygulama kaydı var.
3. Temettü: yalnız KESİNLEŞEN hak kullanım tarihi; teklif tarihiyle tamamlanmaz; ödeme/kayıt tarihi kullanılmaz.
4. Borsa listesi: yürürlük tarihi yalnız metindeki açık '... tarihinden itibaren hak kullanımı' ifadesinden; yayın saatinden türetilmez.
5. Sorgu önbelleği URL + gövde (üye OID + tarih aralığı) ile eşlenir; belirsiz üyede yanlış adayın eski önbelleği kanıt sayılmaz.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from app.research.official_bist.kap_scan import BASE, EFFECT_RANGE, QUERY_BODY, classify, dmy, extract_fields, notice_text, tr_lower
from app.research.official_bist.kap_scan_review import usable_sessions
from app.research.official_bist.raw_package import evaluable_sessions

SUPERSEDE_DAYS = 120
EXEC_WINDOW = (60, 365)  # sermaye uygulaması: bildirimden 60 gün önce .. 365 gün sonra
SECTION_HEADERS = {"Kar Payı Ödemesi": "DIVIDEND", "Sermaye Artırımı/Azaltımı": "CAPITAL", "Birleşme": "MERGER", "Bölünme": "DEMERGER"}


def list_section(text: str | None, sym: str) -> str | None:
    """Borsa hak kullanım listesinde sembolün altında geçtiği işlem başlığı (yoksa None)."""
    if not text or "listesi aşağıdadır" not in text:
        return None
    body = text[text.index("listesi aşağıdadır"):]
    m = re.search(rf"\b{re.escape(sym)}\b", body)
    if not m:
        return None
    best, pos = None, -1
    for h, kind in SECTION_HEADERS.items():
        i = body.rfind(h, 0, m.start())
        if i > pos:
            best, pos = kind, i
    return best
CORROBORATION_DAYS = 10
PROCESS_RE = re.compile(r"başvuru|yönetim kurulu kararı|fonun kullanım|izahname|tamamlan|tescil|esas sözleşme|kullanılmayan|satış")


def codes(field: str | None) -> list[str]:
    return [c.strip() for c in (field or "").split(",") if c.strip()]


def query_files(run: Path, sym: str, scan: dict, log: dict) -> tuple[list[dict], list[dict]]:
    """(geçerli sorgu dosyaları, geçersiz/karışmış önbellek kayıtları)."""
    ambiguous = "identity_resolution" in scan
    oid = scan["identity"]["kap_oid"]
    used, invalid = [], []
    for q in scan["queries"]:
        name = f"disc_{sym}_{oid}_{q['from']}_{q['to']}.json" if ambiguous else f"disc_{sym}_{q['from']}_{q['to']}.json"
        p = run / "kap" / name
        body = {"fromDate": q["from"], "toDate": q["to"], "mkkMemberOidList": [q["oid"]], **QUERY_BODY}
        rec = {"file": name, "url": f"{BASE}/tr/api/disclosure/members/byCriteria", "body_oid": q["oid"], "range": [q["from"], q["to"]],
               "body_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
               "file_sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None,
               "access_log": log.get(name)}
        if q["oid"] != oid or not p.exists() or (rec["access_log"] and rec["access_log"]["sha256"] != rec["file_sha256"]):
            rec["problem"] = "OID_MISMATCH_OR_MISSING_OR_HASH_MISMATCH"
            invalid.append(rec)
        else:
            used.append(rec)
    if ambiguous:
        for p in (run / "kap").glob(f"disc_{sym}_20*.json"):  # OID'siz eski ad: belirsiz adayda yanlış adayın yanıtı olabilir
            invalid.append({"file": p.name, "problem": "LEGACY_NAME_WITHOUT_OID_FOR_AMBIGUOUS_MEMBER_NOT_USED",
                            "file_sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return used, invalid


def event_effect(sym: str, ev: dict) -> dict:
    cat, f = ev["category"], ev["fields"]
    if f is None:
        return {"state": "UNDETERMINED", "kind": "MISSING_CONTENT", "dates": [], "basis": "bildirim içeriği önbellekte yok"}
    flags = tr_lower(f"{ev['subject']} {ev['summary']}")
    if cat == "DIVIDEND":
        cash, share = tr_lower(f.get("cash_dividend_payment") or ""), tr_lower(f.get("share_dividend_payment") or "")
        if "ödenmeyecek" in cash and (not share or "ödenmeyecek" in share):
            return {"state": "NO_PRICE_EFFECT", "kind": "DIVIDEND_NOT_PAID", "dates": [], "basis": "nakit ve pay: Ödenmeyecek"}
        rows = f.get("dividend_table_rows") or []
        finals = [r.get("final") for r in rows]
        if rows and all("unparsed" not in r for r in rows) and all(finals):
            return {"state": "DATED", "kind": "DIVIDEND_FINAL", "dates": sorted({dmy(x) for x in finals}),
                    "basis": "kesinleşen nakit kar payı hak kullanım tarihi", "proposed": [r.get("proposed") for r in rows]}
        return {"state": "UNDETERMINED", "kind": "DIVIDEND_NO_FINAL_DATE", "dates": [],
                "basis": "kesinleşen hak kullanım tarihi yok/okunamadı (teklif tarihiyle tamamlanmadı)",
                "proposed": [r.get("proposed") for r in rows]}
    if cat == "RIGHTS_EXERCISE_NOTICE":
        explicit = f.get("rights_list_effective_date")
        if explicit and "BORSA" in (ev["kap_title"] or "").upper():
            return {"state": "DATED", "kind": "BIST_LIST_EXPLICIT_DATE", "dates": [dmy(explicit)], "section": ev.get("list_section"),
                    "basis": "metindeki açık 'tarihinden itibaren' tarihi"}
        if "BORSA" in (ev["kap_title"] or "").upper() and sym in (f.get("theoretical_price_codes") or []):
            return {"state": "UNDETERMINED", "kind": "BIST_MORNING_THEORETICAL_PRICE", "dates": [], "basis": "açık tarih yok; teyit gerekir"}
        return {"state": "UNDETERMINED", "kind": "RIGHTS_NOTICE_NO_DATE", "dates": [], "basis": "açık tarih yok; teyit gerekir"}
    if cat == "CAPITAL":
        labels = dict(zip(f.get("date_labels") or [], f.get("rights_dates") or []))
        d = labels.get("Rüçhan Hakkı Kullanımı Başlangıç Tarihi")
        if d:
            return {"state": "DATED", "kind": "RIGHTS_ISSUE_START", "dates": [dmy(d)], "basis": "rüçhan hakkı kullanım başlangıç tarihi"}
        if re.search(r"bedelsiz|bedelli|rüçhan|pay bölün", flags):
            return {"state": "UNDETERMINED", "kind": "CAPITAL_PENDING_EXECUTION", "dates": [], "basis": "bedelsiz/bedelli/bölünme süreci; uygulama tarihi yok"}
        if PROCESS_RE.search(flags):
            return {"state": "NO_PRICE_EFFECT", "kind": "CAPITAL_PROCESS_NOTICE", "dates": [], "basis": "süreç bildirimi (bedelsiz/bedelli/bölünme ifadesi yok)"}
        return {"state": "UNDETERMINED", "kind": "CAPITAL_UNDETERMINED", "dates": [], "basis": "tür/tarih belirlenemedi"}
    return {"state": "UNDETERMINED", "kind": cat, "dates": [], "basis": "fiyat etkisi incelenmedi"}


def resolve(sym: str, events: list[dict]) -> None:
    """Belirsiz olayları yalnız kanıtlı gerekçelerle ayırır (yerinde günceller)."""
    pub = lambda e: date.fromisoformat(dmy(e["publish"]))
    explicit = [(e, d) for e in events if e["effect"]["kind"] == "BIST_LIST_EXPLICIT_DATE" for d in e["effect"]["dates"]]
    dated_capital = [(e, d) for e in events for d in e["effect"]["dates"]
                     if e["effect"]["kind"] == "RIGHTS_ISSUE_START"
                     or (e["effect"]["kind"] == "BIST_LIST_EXPLICIT_DATE" and e["effect"].get("section") == "CAPITAL")]
    end = date.fromisoformat(EFFECT_RANGE[1])
    for e in events:
        eff = e["effect"]
        if eff["state"] != "UNDETERMINED":
            continue
        p = pub(e)
        if p > end:
            eff.update(state="RESOLVED", resolution="OUT_OF_SCOPE_PUBLISHED_AFTER_RANGE"); continue
        if eff["kind"] == "DIVIDEND_NO_FINAL_DATE":
            later = [x for x in events if x["category"] == "DIVIDEND" and p < pub(x) <= p + timedelta(days=SUPERSEDE_DAYS)
                     and x["effect"]["kind"] in ("DIVIDEND_FINAL", "DIVIDEND_NOT_PAID")]
            if later:
                eff.update(state="RESOLVED", resolution=f"SUPERSEDED_DIVIDEND by {[x['index'] for x in later]}"); continue
        if eff["kind"] in ("BIST_MORNING_THEORETICAL_PRICE", "RIGHTS_NOTICE_NO_DATE"):
            match = [x["index"] for x, d in explicit if 0 <= (p - date.fromisoformat(d)).days <= CORROBORATION_DAYS
                     or (eff["kind"] == "BIST_MORNING_THEORETICAL_PRICE" and d == p.isoformat())]
            if eff["kind"] == "BIST_MORNING_THEORETICAL_PRICE":
                match = [x["index"] for x, d in explicit if d == p.isoformat()]
            if match:
                eff.update(state="RESOLVED", resolution=f"CORROBORATED_BY_EXPLICIT_LIST {match}"); continue
        if eff["kind"] == "CAPITAL_PENDING_EXECUTION":
            execs = [x["index"] for x, d in dated_capital
                     if -EXEC_WINDOW[0] <= (date.fromisoformat(d) - p).days <= EXEC_WINDOW[1]]
            if execs:
                eff.update(state="RESOLVED", resolution=f"EXECUTION_FOUND {execs}"); continue


def review_symbol_v2(run: Path, sym: str, scan: dict, log: dict, rows: list[dict], raw_sha: str) -> dict:
    ident = scan.get("identity") or {}
    if ident.get("status") != "MATCH":
        return {"symbol": sym, "identity": ident, "status": "NOT_READY", "blockers": [f"IDENTITY_{ident.get('status')}"], "usable_sessions": []}
    used, invalid = query_files(run, sym, scan, log)
    disc = []
    for q in used:
        d = json.loads((run / "kap" / q["file"]).read_text(encoding="utf-8"))
        disc += d if isinstance(d, list) else []
    seen, events, missing = set(), [], []
    for x in disc:
        if x["disclosureIndex"] in seen:
            continue
        seen.add(x["disclosureIndex"])
        cat = classify(x["subject"], x["summary"])
        if cat in (None, "TITLE_CHANGE"):
            continue
        if sym not in codes(x.get("stockCodes")) and sym not in codes(x.get("relatedStocks")):
            continue
        p = run / "kap" / f"notice_{x['disclosureIndex']}.html"
        text = notice_text(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else None
        if text is None:
            missing.append(x["disclosureIndex"])
        ev = {"index": x["disclosureIndex"], "publish": x["publishDate"], "kap_title": x["kapTitle"], "subject": x["subject"],
              "summary": (x["summary"] or "")[:160], "category": cat, "fields": extract_fields(text) if text else None,
              "list_section": list_section(text, sym),
              "notice_sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None}
        ev["effect"] = event_effect(sym, ev)
        events.append(ev)
    resolve(sym, events)
    in_range = lambda d: EFFECT_RANGE[0] <= d <= EFFECT_RANGE[1]
    dated = sorted({d for e in events if e["effect"]["state"] == "DATED" for d in e["effect"]["dates"] if in_range(d)})
    undetermined = [e for e in events if e["effect"]["state"] == "UNDETERMINED"]
    evaluable = evaluable_sessions(rows)
    usable = usable_sessions(evaluable, dated)
    blockers = []
    if len(used) != len(scan["queries"]):
        blockers.append("KAP_QUERY_CACHE_INVALID_OR_MISSING")
    if undetermined:
        blockers.append("UNDETERMINED_CORPORATE_EVENT")
    if not usable:
        blockers.append("NO_USABLE_SESSION")
    status = "READY_FOR_RESEARCH_WITH_LIMITS" if not blockers else "NOT_READY"
    for e in events:
        e.pop("fields", None)
    return {"symbol": sym, "identity": ident, "queries_used": used, "invalid_cache": invalid, "missing_content": missing,
            "events": events, "in_scope_dated_events": dated,
            "undetermined": [{"index": e["index"], "publish": e["publish"], "kind": e["effect"]["kind"], "subject": e["subject"]} for e in undetermined],
            "evaluable_sessions": len(evaluable), "usable_sessions": usable if status != "NOT_READY" else [],
            "blocked_sessions_by_dated_events": [t for t in evaluable if t not in usable],
            "bound_to": {"raw_csv_sha256": raw_sha, "effect_range": list(EFFECT_RANGE)},
            "limits": "KAP sorgu servisi tamlığı/sayfalaması belgelenmedi; olay bulunmaması yokluk kanıtı değildir; keşifsel kullanım.",
            "blockers": blockers, "status": status}


def main(run: Path) -> int:
    run = run.resolve()
    scans = json.loads((run / "scan_results.json").read_text(encoding="utf-8"))
    log = {}
    for line in (run / "kap" / "access_log.tsv").read_text(encoding="utf-8").splitlines():
        url, name, ts, code, sha = (line.split("\t") + [""] * 5)[:5]
        if code == "200":
            log[name] = {"url": url, "accessed_at_utc": ts, "sha256": sha}
    pkg = run.parent / "raw_package_20260930" / "symbols"
    out = {}
    for sym, scan in scans.items():
        p = pkg / f"{sym}_official_raw.csv"
        rows = list(csv.DictReader(p.open(encoding="utf-8")))
        out[sym] = review_symbol_v2(run, sym, scan, log, rows, hashlib.sha256(p.read_bytes()).hexdigest())
    meta = {"version": 2, "created": datetime.now().astimezone().isoformat(), "network_calls": 0,
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scan_results_sha256": hashlib.sha256((run / "scan_results.json").read_bytes()).hexdigest()}
    (run / "review_v2.json").write_text(json.dumps({"meta": meta, "symbols": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(json.dumps({"status": dict(Counter(r["status"] for r in out.values())),
                      "blockers": dict(Counter(b for r in out.values() for b in r["blockers"])),
                      "rows": {s: [r["status"], len(r.get("usable_sessions", [])), r.get("in_scope_dated_events"),
                                   [(u["kind"], u["publish"][:10]) for u in r.get("undetermined", [])][:3]] for s, r in out.items()}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
