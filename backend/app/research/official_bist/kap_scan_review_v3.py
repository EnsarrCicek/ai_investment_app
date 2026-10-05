"""KAP taraması değerlendirmesi — SÜRÜM 3 (ağsız; yalnız önbellek). Sürüm 1/2 çıktıları korunur.

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.kap_scan_review_v3 <çalıştırma_klasörü>

Sürüm 2'ye göre yalnız eşleştirme kanıtı daraltıldı (sınıflandırma, tarih okuma, sorgu önbelleği aynı):
1. OUT_OF_SCOPE_PUBLISHED_AFTER_RANGE KALDIRILDI. Yayın tarihinin dönemden sonra olması olayın dönem dışında olduğunu
   kanıtlamaz; yalnız belgelenmiş yürürlük tarihi (DATED) dönem dışıysa olay kapsam dışıdır. Aksi hâlde belirsiz kalır.
2. Zaman penceresi (120 gün, -60/+365 gün, 10 gün) eşleşme kanıtı DEĞİLDİR; hiçbir kural pencereye dayanmaz.
   - Kar payı yerine geçme: sonraki bildirim Güncelleme/Düzeltme işaretli olmalı ve aynı yönetim kurulu karar tarihi,
     aynı ISIN kümesi, aynı taksit etiketleri ve aynı taksit başına brüt tutar taşımalı (iki bildirimde de yazılıysa
     genel kurul tarihi de eşit). Taksit yapısı değiştiyse (ör. 2 taksit -> peşin) eşleşme YOK sayılır.
   - Sermaye uygulaması: süreç anahtarı (YK karar tarihi + işlem gören ISIN + iç kaynak bedelsiz oranı) aynı olan bir
     bildirimde açık 'Bedelsiz Pay Alma Hakkı Kullanım Başlangıç Tarihi' D bulunmalı VE Borsa sermaye listesinde
     (açık tarih D) aynı sembol aynı 'Bedelsiz Pay Alma Oranı' ile yer almalı. Olay o zaman D tarihli olur.
   - Borsa sabah/teorik fiyat duyurusu: içerik (brüt temettü tutarı veya bedelsiz oranı) açık tarihli listedeki satırla
     birebir aynı VE listenin açık tarihi duyurunun yayın günü olmalı. Yalnız aynı gün/aynı tür yeterli değildir.
3. Liste satırları HTML tablosundan okunur (boş hücreler metin çıkarımında kaybolduğu için sütun eşlemesi gerekir).
"""

from __future__ import annotations

import csv
import hashlib
import html as htmlmod
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.research.official_bist.kap_scan import EFFECT_RANGE, classify, dmy, extract_fields, notice_text
from app.research.official_bist.kap_scan_review import usable_sessions
from app.research.official_bist.kap_scan_review_v2 import codes, event_effect, list_section, query_files
from app.research.official_bist.raw_package import evaluable_sessions

DATE = r"([0-9]{2}\.[0-9]{2}\.[0-9]{4})"


def num(s: str | None) -> float | None:
    if s is None or not s.strip():
        return None
    try:
        return float(s.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def summary_block(text: str) -> str:
    i = text.find("Özet Bilgi")
    return text[i:i + 6000] if i >= 0 else text[:6000]


def process_evidence(text: str, sym: str) -> dict:
    """Şirket bildiriminden eşleştirme alanları (yalnız açık yazılı değerler; boşsa None)."""
    s = summary_block(text)
    one = lambda p: (re.search(p, s) or [None, None])[1]
    div_rows = [{"isin": m[2], "label": m[3], "gross": num(m[4])}
                for m in re.finditer(r"\b([A-Z]{3,6}), (TR[A-Z0-9]{10}) (Peşin|[0-9]+\. Taksit) ([0-9.]+,[0-9]+)", s)]
    cap = [{"group": m[1], "isin": m[3], "existing": num(m[4]), "bonus_amount": num(m[5]), "bonus_ratio": num(m[6])}
           for m in re.finditer(r"(?:([A-Z]) Grubu, )?\b([A-Z]{3,6}), (TR[A-Z0-9]{10}) ([0-9.]+) ([0-9.]+,[0-9]+) ([0-9.]+,[0-9]+)", s)
           if m[2] == sym]
    return {"decision_date": one(r"Karar Tarihi " + DATE), "general_meeting_date": one(r"Genel Kurul Tarihi " + DATE),
            "is_update": "Güncelleme mi ? Evet" in s, "is_correction": "Düzeltme mi ? Evet" in s,
            "previous_notice_date": one(r"Daha Önce Yapılan Açıklamanın Tarihi " + DATE),
            "dividend_rows": [r for r in div_rows], "capital_rows": cap,
            "bonus_start_date": one(r"Bedelsiz Pay Alma Hakkı Kullanım Başlangıç Tarihi " + DATE)}


def morning_evidence(text: str, sym: str) -> dict:
    """Borsa teorik fiyat duyurusundaki sembol satırı: brüt temettü veya iç kaynak bedelsiz oranı."""
    e = re.escape(sym)
    div = re.search(rf"\b{e}\.E Pay Başına Brüt Temettü:\s*:?\s*([0-9.]+,?[0-9]*) TL", text)
    bonus = re.search(rf"\b{e}\.E %([0-9.]+,?[0-9]*) İç Kaynaklardan Bedelsiz", text)
    return {"gross_dividend": num(div[1]) if div else None, "bonus_ratio": num(bonus[1]) if bonus else None}


def list_rows(raw_html: str, sym: str) -> list[dict]:
    """Borsa hak kullanım listesindeki tablolar: başlık satırı -> hücre eşlemesi; Pay Kodu == sym olan satırlar."""
    out = []
    for tbl in re.findall(r"<table(?:(?!<table).)*?</table>", raw_html, flags=re.S):  # en içteki tablolar (sayfa düzeni iç içe)
        rows = [[htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td.*?</td>", tr, flags=re.S)]
                for tr in re.findall(r"<tr.*?</tr>", tbl, flags=re.S)]
        if not rows or "Pay Kodu" not in rows[0]:
            continue
        head = rows[0]
        for r in rows[1:]:
            if len(r) == len(head) and r[head.index("Pay Kodu")] == sym:
                out.append(dict(zip(head, r)))
    return out


def list_value(rows: list[dict], kind: str) -> float | None:
    key = "1 TL Nominal değerli paya BRÜT (TL)" if kind == "DIVIDEND" else "Bedelsiz Pay Alma Oranı (%)"
    vals = {num(r.get(key)) for r in rows if num(r.get(key)) is not None}
    return vals.pop() if len(vals) == 1 else None


def dividend_link(early: dict, late: dict) -> list[str]:
    """Kar payı bildirimleri arasındaki eşleşme kontrolü; boş liste = tüm koşullar sağlandı. Aksi hâlde eksikler."""
    a, b = early["evidence"], late["evidence"]
    missing = []
    if not (b["is_update"] or b["is_correction"]):
        missing.append("LATER_NOT_FLAGGED_UPDATE_OR_CORRECTION")
    if not a["decision_date"] or a["decision_date"] != b["decision_date"]:
        missing.append("DECISION_DATE_MISMATCH_OR_MISSING")
    if a["general_meeting_date"] and b["general_meeting_date"] and a["general_meeting_date"] != b["general_meeting_date"]:
        missing.append("GENERAL_MEETING_DATE_MISMATCH")
    if late["effect"]["kind"] == "DIVIDEND_FINAL":
        ra = {(r["isin"], r["label"]): r["gross"] for r in a["dividend_rows"]}
        rb = {(r["isin"], r["label"]): r["gross"] for r in b["dividend_rows"]}
        if not ra or {k[0] for k in ra} != {k[0] for k in rb}:
            missing.append("SHARE_GROUP_ISIN_MISMATCH_OR_MISSING")
        if set(ra) != set(rb):
            missing.append("INSTALLMENT_MISMATCH")
        elif any(ra[k] is None or ra[k] != rb[k] for k in ra):
            missing.append("GROSS_AMOUNT_MISMATCH")
    return missing


def capital_key(ev: dict) -> tuple | None:
    e = ev["evidence"]
    rows = [r for r in e["capital_rows"] if r["bonus_ratio"] is not None]
    if not e["decision_date"] or len({(r["isin"], r["bonus_ratio"]) for r in rows}) != 1:
        return None
    return e["decision_date"], rows[0]["isin"], rows[0]["bonus_ratio"]


def resolve_v3(sym: str, events: list[dict]) -> None:
    """Belirsiz olayları yalnız içerik eşleşmesiyle ayırır (yerinde günceller). Pencere/yakınlık kullanılmaz."""
    lists = [e for e in events if e["effect"]["kind"] == "BIST_LIST_EXPLICIT_DATE"]
    pub_day = lambda e: dmy(e["publish"])
    for e in events:
        eff = e["effect"]
        if eff["state"] != "UNDETERMINED":
            continue
        if eff["kind"] == "DIVIDEND_NO_FINAL_DATE":
            later = [x for x in events if x["category"] == "DIVIDEND" and x["index"] != e["index"] and x.get("evidence")
                     and pub_day(x) >= pub_day(e) and x["effect"]["kind"] in ("DIVIDEND_FINAL", "DIVIDEND_NOT_PAID")]
            checks = {x["index"]: dividend_link(e, x) for x in later}
            linked = [i for i, m in checks.items() if not m]
            eff["link_check"] = checks
            if linked:
                eff.update(state="RESOLVED", resolution=f"SUPERSEDED_DIVIDEND_LINKED {linked}")
        elif eff["kind"] in ("BIST_MORNING_THEORETICAL_PRICE", "RIGHTS_NOTICE_NO_DATE") and e.get("morning"):
            m = e["morning"]
            kind, val = ("DIVIDEND", m["gross_dividend"]) if m["gross_dividend"] is not None else ("CAPITAL", m["bonus_ratio"])
            match = [x["index"] for x in lists if val is not None and x.get("list_section") == kind
                     and x["effect"]["dates"] == [pub_day(e)] and list_value(x.get("rows") or [], kind) == val]
            eff["link_check"] = {"content": [kind, val], "same_day_lists": [x["index"] for x in lists if x["effect"]["dates"] == [pub_day(e)]]}
            if match:
                eff.update(state="RESOLVED", resolution=f"CORROBORATED_CONTENT_MATCH {match}")
        elif eff["kind"] == "CAPITAL_PENDING_EXECUTION":
            key = capital_key(e) if e.get("evidence") else None
            same = [x for x in events if x.get("evidence") and x["category"] == "CAPITAL" and capital_key(x) == key] if key else []
            starts = sorted({x["evidence"]["bonus_start_date"] for x in same if x["evidence"]["bonus_start_date"]})
            match = [x["index"] for x in lists for d in starts if x.get("list_section") == "CAPITAL"
                     and x["effect"]["dates"] == [dmy(d)] and list_value(x.get("rows") or [], "CAPITAL") == key[2]]
            eff["link_check"] = {"process_key": key, "process_notices": [x["index"] for x in same], "explicit_start_dates": starts}
            if match and len(starts) == 1:
                eff.update(state="DATED", kind="CAPITAL_EXECUTION_LINKED", dates=[dmy(starts[0])],
                           resolution=f"EXECUTION_LINKED {match}", basis="süreç anahtarı + açık başlangıç tarihi + liste oranı")


def review_symbol_v3(run: Path, sym: str, scan: dict, log: dict, rows: list[dict], raw_sha: str) -> dict:
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
        if cat in (None, "TITLE_CHANGE") or (sym not in codes(x.get("stockCodes")) and sym not in codes(x.get("relatedStocks"))):
            continue
        p = run / "kap" / f"notice_{x['disclosureIndex']}.html"
        raw = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        text = notice_text(raw) if raw else None
        if text is None:
            missing.append(x["disclosureIndex"])
        ev = {"index": x["disclosureIndex"], "publish": x["publishDate"], "kap_title": x["kapTitle"], "subject": x["subject"],
              "summary": (x["summary"] or "")[:160], "category": cat, "fields": extract_fields(text) if text else None,
              "list_section": list_section(text, sym), "notice_sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None}
        ev["effect"] = event_effect(sym, ev)
        if text and cat in ("DIVIDEND", "CAPITAL"):
            ev["evidence"] = process_evidence(text, sym)
        if text and cat == "RIGHTS_EXERCISE_NOTICE":
            ev["morning"] = morning_evidence(text, sym)
            ev["rows"] = list_rows(raw, sym)
        events.append(ev)
    resolve_v3(sym, events)
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
            "undetermined": [{"index": e["index"], "publish": e["publish"], "kind": e["effect"]["kind"], "subject": e["subject"],
                              "link_check": e["effect"].get("link_check")} for e in undetermined],
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
        out[sym] = review_symbol_v3(run, sym, scan, log, rows, hashlib.sha256(p.read_bytes()).hexdigest())
    v2 = json.loads((run / "review_v2.json").read_text(encoding="utf-8"))["symbols"]
    meta = {"version": 3, "created": datetime.now().astimezone().isoformat(), "network_calls": 0,
            "code_sha256": {f: hashlib.sha256((Path(__file__).parent / f).read_bytes()).hexdigest()
                            for f in ("kap_scan_review_v3.py", "kap_scan_review_v2.py", "kap_scan.py")},
            "scan_results_sha256": hashlib.sha256((run / "scan_results.json").read_bytes()).hexdigest(),
            "review_v2_sha256": hashlib.sha256((run / "review_v2.json").read_bytes()).hexdigest()}
    (run / "review_v3.json").write_text(json.dumps({"meta": meta, "symbols": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"status": dict(Counter(r["status"] for r in out.values())),
                      "changed_vs_v2": {s: [v2[s]["status"], r["status"]] for s, r in out.items() if v2[s]["status"] != r["status"]},
                      "ready": [s for s, r in out.items() if r["status"] == "READY_FOR_RESEARCH_WITH_LIMITS"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
