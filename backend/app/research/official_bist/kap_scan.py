"""Seçilmiş semboller için KAP kimlik ve kurumsal işlem taraması (salt-okunur, ücretsiz kamu kaynağı).

Kullanım (backend dizininden): python -X utf8 -m app.research.official_bist.kap_scan <çalıştırma_klasörü>
Girdi: <klasör>/selection.json (sonuçlardan önce kaydedildi). Çıktılar aynı klasöre.

* Her istek diske önbelleklenir; aynı URL/sorgu tekrar indirilmez. En fazla 2 deneme, istekler arası bekleme.
* KAP sorgu servisi belgelenmiş bir API değildir; tamlık/sayfa sınırı doğrulanamaz. Olay bulunmaması YOKLUK kanıtı değildir.
* Kimlik: bugünkü üye kaydı geçmişe otomatik taşınmaz; inceleme dönemindeki şirket bildirimlerinin hisse kodu ve unvanı esas alınır.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.kap.org.tr"
PAUSE, MAX_ATTEMPTS, RATE_LIMIT_WAIT, BREAKER = 4.0, 2, 60, 3  # KAP 429 sınırına uyum; aşma yok
QUERY_RANGES = [("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-07-31")]
EFFECT_RANGE = ("2024-05-07", "2025-07-11")  # resmî bülten kapsamı (ısınma geçmişi dahil)
QUERY_BODY = {"memberTypes": ["IGS"], "inactiveMkkMemberOidList": [], "disclosureClass": "", "subjectList": [], "isLate": "",
              "mainSector": "", "sector": "", "subSector": "", "marketOid": "", "index": "", "bdkReview": "", "bdkMemberOidList": [],
              "year": "", "term": "", "ruleType": "", "period": "", "fromSrc": False, "srcCategory": "", "discIndex": []}


def tr_lower(text: str) -> str:
    """Türkçe küçük harf: str.lower() 'İ' harfini 'i̇' (i + birleşik nokta) yapar ve eşleşmeyi bozar."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def classify(subject: str, summary: str) -> str | None:
    """KAP'ın resmî bildirim KONUSU esas alınır (serbest metindeki 'temettü'/'bedelsiz' geçişleri — bağlı ortaklıktan
    temettü geliri, endeks duyurusu, dava bildirimi — olay sayılmaz)."""
    subj = tr_lower(subject or "")
    summ = tr_lower(summary or "")
    if "kar payı dağıtım işlemlerine ilişkin bildirim" in subj or "kâr payı dağıtım işlemlerine ilişkin bildirim" in subj:
        return "DIVIDEND"
    if "sermaye artırımı - azaltımı" in subj or "rüçhan hakkı referans fiyatı" in subj or "pay bölünmesi" in subj:
        return "CAPITAL"
    if subj.strip() == "hak kullanımı" or "özsermaye hallerine" in subj or             ("alım satım sistemi duyurusu" in subj and summ.strip().startswith("hak kullanımı")):
        return "RIGHTS_EXERCISE_NOTICE"
    if "birleşme işlemlerine" in subj or "bölünme işlemlerine" in subj:
        return "MERGER_OR_DEMERGER"
    if any(k in subj or k in summ for k in ("ünvan değişikliği", "unvan değişikliği")):
        return "TITLE_CHANGE"  # kimlik için özet metni de taranır (konu genelde 'Özel Durum Açıklaması')
    return None


def notice_text(raw_html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw_html, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def extract_fields(text: str) -> dict:
    """Bildirim metninden yalnızca fiyat sürekliliğiyle ilgili alanlar (kişisel veri saklanmaz)."""
    i = text.find("Özet Bilgi")
    s = text[i:i + 6000] if i >= 0 else text[:6000]
    def grab(label, n=40):
        m = re.search(re.escape(label) + r"\s*([^|]{1," + str(n) + r"})", s)
        return m.group(1).strip() if m else None
    return {
        "cash_dividend_payment": grab("Nakit Kar Payı Ödeme Şekli", 30),
        "share_dividend_payment": grab("Pay Biçiminde Ödeme", 30),
        "gross_cash_per_share_tl": re.findall(r"B Grubu, [A-Z]+, TR[A-Z0-9]+ ([0-9]+,[0-9]+)", s)[:2] or re.findall(r", [A-Z]{4,6}, TR[A-Z0-9]{10} ([0-9]+,[0-9]+)", s)[:2],
        "rights_dates": re.findall(r"(?:Hak Kullanım Tarihi|Kar Payı Ödeme Tarihi|Ödeme Tarihi|Rüçhan Hakkı Kullanımı Başlangıç Tarihi|Kayıt Tarihi)\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", s)[:6],
        "date_labels": re.findall(r"(Hak Kullanım Tarihi|Kar Payı Ödeme Tarihi|Ödeme Tarihi|Rüçhan Hakkı Kullanımı Başlangıç Tarihi|Kayıt Tarihi)\s*[0-9]{2}\.[0-9]{2}\.[0-9]{4}", s)[:6],
        "isin_lines": re.findall(r"[A-Z] Grubu, [A-Z0-9]+, TR[A-Z0-9]{10}", s)[:3],
        "bonus_or_rights_mentioned": bool(re.search(r"bedelsiz|bedelli|rüçhan", s, re.I)),
        "dividend_table_rows": dividend_table_rows(s),
        "rights_list_effective_date": (re.search(r"([0-9]{2}\.[0-9]{2}\.[0-9]{4}) tarihinden itibaren hak kullanım", text) or [None, None])[1],
        "theoretical_price_codes": sorted(set(re.findall(r"([A-Z0-9]+)\.E (?:Pay Başına|Gross)", text))),
    }


def dividend_table_rows(s: str) -> list[dict]:
    """Kar payı ödeme tablosu: '... Hak Kullanım Tarihi (1) Kesinleşen ... (2) Ödeme Tarihi (3) Kayıt Tarihi (4)' ardından
    satır başına (Peşin / n. Taksit) dört hücre. Hücreler ayrı tutulur; dört hücre okunamazsa satır 'unparsed' olur.
    Ödeme/kayıt tarihi hak kullanım tarihi yerine KULLANILMAZ; kesinleşen hücre teklif tarihiyle DOLDURULMAZ."""
    m = re.search(r"Kayıt Tarihi \(4\)(.{0,800})", s)
    if not m:
        return []
    rows = []
    for row in re.finditer(r"(Peşin|[0-9]+\. Taksit)((?:\s+(?:[0-9]{2}\.[0-9]{2}\.[0-9]{4}|-)){1,4})", m.group(1)):
        cells = row.group(2).split()
        if len(cells) != 4:
            rows.append({"label": row.group(1), "unparsed": cells})
            continue
        val = lambda c: None if c == "-" else c
        rows.append({"label": row.group(1), "proposed": val(cells[0]), "final": val(cells[1]),
                     "payment": val(cells[2]), "record": val(cells[3])})
    return rows


class Fetcher:
    def __init__(self, cache: Path):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.log = cache / "access_log.tsv"
        self.requests = 0
        self.consecutive_429 = 0
        self.stopped = False  # art arda BREAKER kez 429 -> yeni istek yok (kalanlar belirsiz)

    def _get(self, url: str, body: dict | None, name: str) -> bytes | None:
        path = self.cache / name
        if path.exists():
            return path.read_bytes()
        if self.stopped:
            return None
        data = None
        for _ in range(MAX_ATTEMPTS):
            ts = datetime.now(timezone.utc).isoformat()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
                                             data=json.dumps(body).encode() if body is not None else None)
                with urllib.request.urlopen(req, timeout=40) as r:
                    data, code = r.read(), r.status
            except Exception as exc:  # noqa: BLE001 — sınırlı deneme; erişim kısıtı aşılmaz
                data, code = None, f"{type(exc).__name__}: {str(exc)[:80]}"
            self.requests += 1
            with self.log.open("a", encoding="utf-8") as fh:
                fh.write(f"{url}\t{name}\t{ts}\t{code}\t{hashlib.sha256(data).hexdigest() if data else ''}\n")
            time.sleep(PAUSE)
            if data and code == 200:
                self.consecutive_429 = 0
                path.write_bytes(data)
                return data
            if "429" in str(code):
                time.sleep(RATE_LIMIT_WAIT)
        if "429" in str(code):
            self.consecutive_429 += 1
            if self.consecutive_429 >= BREAKER:
                self.stopped = True
        return None

    def member(self, sym: str):
        b = self._get(f"{BASE}/tr/api/member/filter/{sym}", None, f"member_{sym}.json")
        return json.loads(b) if b else None

    def disclosures(self, sym: str, oid: str, a: str, b: str, oid_in_name: bool = False):
        name = f"disc_{sym}_{oid}_{a}_{b}.json" if oid_in_name else f"disc_{sym}_{a}_{b}.json"
        raw = self._get(f"{BASE}/tr/api/disclosure/members/byCriteria",
                        {"fromDate": a, "toDate": b, "mkkMemberOidList": [oid], **QUERY_BODY}, name)
        if raw is None:
            return None
        d = json.loads(raw)
        return d if isinstance(d, list) else None

    def notice(self, idx: int) -> str | None:
        b = self._get(f"{BASE}/tr/Bildirim/{idx}", None, f"notice_{idx}.html")
        return notice_text(b.decode("utf-8", errors="replace")) if b else None


def dmy(s: str) -> str:
    d, m, y = s[:10].split(".")
    return f"{y}-{m}-{d}"


def scan_symbol(f: Fetcher, sym: str, bulletin_name: str | None) -> dict:
    out = {"symbol": sym, "bulletin_name": bulletin_name, "queries": [], "identity": None, "events": [], "limits": []}
    members = f.member(sym)
    if not members:
        out["identity"] = {"status": "UNRESOLVED", "reason": "MEMBER_LOOKUP_FAILED"}
        return out
    if len(members) != 1:
        # Belirsiz üye: her aday için dönem sorgusu; dönem içinde bu KOD ile kendi bildirimi olan TEK aday seçilir.
        with_code = []
        for c in members:
            d = f.disclosures(sym, c["mkkMemberOid"], "2024-01-01", "2024-12-31", oid_in_name=True)
            if d and any(sym in [x.strip() for x in (e.get("stockCodes") or "").split(",")] and e.get("kapTitle") == c["title"] for e in d):
                with_code.append(c)
        if len(with_code) != 1:
            out["identity"] = {"status": "AMBIGUOUS", "candidates": members, "candidates_with_code_in_2024": with_code}
            return out
        out["identity_resolution"] = {"candidates": members, "chosen_by": "2024 dönem sorgusunda bu kodla kendi bildirimi olan tek aday"}
        m = with_code[0]
    else:
        m = members[0]
    disc, failed = [], []
    for a, b in QUERY_RANGES:
        d = f.disclosures(sym, m["mkkMemberOid"], a, b, oid_in_name=len(members) != 1)
        out["queries"].append({"from": a, "to": b, "oid": m["mkkMemberOid"], "result": None if d is None else len(d)})
        if d is None:
            failed.append(f"{a}..{b}")
        else:
            disc += d
    own = [x for x in disc if sym in [c.strip() for c in (x.get("stockCodes") or "").split(",")]]
    period_own = [x for x in own if EFFECT_RANGE[0] <= dmy(x["publishDate"]) <= EFFECT_RANGE[1]]
    titles = sorted({x["kapTitle"] for x in period_own})
    title_changes = [x for x in disc if classify(x["subject"], x["summary"]) == "TITLE_CHANGE"]
    in_period_changes = [x for x in title_changes if EFFECT_RANGE[0] <= dmy(x["publishDate"]) <= EFFECT_RANGE[1]]
    if failed:
        status = "UNRESOLVED"
    elif period_own and len(titles) == 1 and not in_period_changes:
        status = "MATCH"  # dönem dışındaki unvan değişikliği dönem kimliğini değiştirmez (yayın tarihi kayıtlı)
    elif period_own:
        status = "MATCH_WITH_TITLE_CHANGE" if in_period_changes else "AMBIGUOUS_MULTIPLE_TITLES"
    else:
        status = "UNRESOLVED"
    out["identity"] = {"status": status, "kap_member_code": m["companyCode"], "kap_oid": m["mkkMemberOid"],
                       "current_kap_title": m["title"], "period_titles_with_code": titles,
                       "own_disclosures_in_period": len(period_own),
                       "title_change_notices": [{"index": x["disclosureIndex"], "publish": x["publishDate"],
                                                 "in_period": x in in_period_changes} for x in title_changes]}
    if failed:
        out["limits"].append(f"QUERY_FAILED:{failed}")
    rel = []
    for x in disc:
        cat = classify(x["subject"], x["summary"])
        related = sym in (x.get("relatedStocks") or "") or x in own
        if cat and cat != "TITLE_CHANGE" and related:
            rel.append((cat, x))
    for cat, x in rel:
        txt = f.notice(x["disclosureIndex"])
        fields = extract_fields(txt) if txt else {"fetch_failed": True}
        out["events"].append({"category": cat, "publish": x["publishDate"], "index": x["disclosureIndex"],
                              "kap_title": x["kapTitle"], "subject": x["subject"], "summary": (x["summary"] or "")[:160], **fields})
    out["disclosures_total"] = len(disc)
    return out


def main(run: Path) -> int:
    run = run.resolve()
    sel = json.loads((run / "selection.json").read_text(encoding="utf-8"))["symbols"]
    from app.research.official_bist.bulletin import read_bulletin_zip
    from app.research.official_bist.run_universe_quality import index_bulletin, load_bulletins

    bulletins = load_bulletins()  # yerel, hash doğrulamalı; ağ yok
    names = {}
    for sym in sel:  # bülten adı: kodun görüldüğü en son bültenden (dönem içi ad)
        for d in reversed(list(bulletins)):
            _, by_code = index_bulletin(read_bulletin_zip(bulletins[d]["data"])[1], d)
            if f"{sym}.E" in by_code:
                names[sym] = {"date": d, "name": by_code[f"{sym}.E"][0].split(";")[2].strip()}
                break
    f = Fetcher(run / "kap")
    results = {}
    for sym in sel:
        results[sym] = scan_symbol(f, sym, names[sym])
        (run / "scan_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"symbols": len(results), "requests_this_run": f.requests, "stopped_by_rate_limit": f.stopped,
                      "identity": {s: r["identity"]["status"] for s, r in results.items()},
                      "event_counts": {s: len(r["events"]) for s, r in results.items()}}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
