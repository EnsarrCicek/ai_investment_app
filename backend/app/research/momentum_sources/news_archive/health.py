"""İleriye dönük haber arşivi — VERİ KALİTESİ / KAPSAM raporu (YALNIZ araştırma; salt okunur).

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.news_archive.health

* Yalnız kaynak/veri kalitesi: getirme sürekliliği, zaman damgası kalitesi, sembol çözümleme, tekrar kalitesi,
  başlıktan olay türü, ham yanıt korunumu, zamanlayıcı durumu. Fiyat, V2 olayı, tepe, MFE, alarm, lead, aday
  sonucu OKUNMAZ / BİRLEŞTİRİLMEZ (holdout tarihli ham haber veri kalitesi için okunabilir).
* `received_at − published_at` = ARŞİV KEŞİF GECİKMESİ (archival discovery lag), sağlayıcı ağ gecikmesi DEĞİL:
  arşivin ilk getirmesi geçmiş RSS öğelerini de içerir. Temiz ileriye dönük tahmin yalnız arşivin fiilen kayıt
  yazmaya başladığı andan SONRA yayımlanan öğelerle verilir.
* Şirket adı teşhisi: yalnız proje varlık metadatası (`scripts/seed_assets.py` BIST100 sözlüğü, AST ile okunur;
  betik ÇALIŞTIRILMAZ) ile kesin/normalize ad eşleşmesi. Bulanık eşleme, LLM, fiyat çıkarımı yok; depo değişmez.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.research.momentum_pilot.sources import CLOCK_SKEW_TOLERANCE
from app.research.momentum_sources.news_archive import adapters as ad
from app.research.momentum_sources.news_archive.archiver import LOG_DIR, RAW_DIR
from app.research.momentum_sources.news_archive.models import EVENT_TYPES
from app.research.momentum_sources.storage import DEFAULT_ROOT, SecondaryStore

TASK_NAME = "MomentumProspectiveNewsArchive"
SEED_ASSETS = Path(__file__).resolve().parents[4] / "scripts" / "seed_assets.py"
LAG_LABEL = "ARCHIVAL DISCOVERY LAG (received_at - published_at; NOT provider network latency)"
FORBIDDEN_KEYS = ("precision", "recall", "fpr", "lead", "alert", "label", "mfe", "peak", "v2_event", "candidate",
                  "return", "outcome")
# Önceden sabit hazırlık ölçütleri (sonuç fiyatı kullanılmaz)
READINESS = {"published_at_present_min": 0.99, "clock_skew_max": 0.01, "storage_conflicts_max": 0,
             "source_revisions_fail_readiness": False,
             "raw_preserved_runs_min": 1.0, "continuity_days_min": 5, "max_gap_minutes_in_window": 15}
TAXONOMY = ("A_GENERAL_MARKET_MACRO", "B_FOREIGN_MARKET", "C_COMMODITY_FX", "D_COMPANY_NAME_NO_TICKER",
            "E_NON_BIST_COMPANY", "F_AMBIGUOUS", "G_OTHER")


# ------------------------------------------------------------------ metin normalizasyonu (deterministik)
_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})


def norm(text: str) -> str:
    t = (text or "").replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)
    return " ".join(re.findall(r"[a-z0-9&]+", t))


def _has(text_n: str, phrase_n: str) -> bool:
    return bool(phrase_n) and re.search(rf"(?<![a-z0-9]){re.escape(phrase_n)}(?![a-z0-9])", text_n) is not None


# ------------------------------------------------------------------ şirket adı teşhisi (yalnız proje metadatası)
LEGAL = {"a", "s", "t", "as", "tas", "anonim", "sirketi", "sirket", "sanayi", "sanayii", "ve", "ticaret", "tic",
         "san", "a.s", "aas", "tao", "corp", "inc"}


def load_company_names(path: Path = SEED_ASSETS) -> dict[str, str]:
    """`BIST100` sözlüğünü AST ile okur (betik çalıştırılmaz → Firestore yok)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "BIST100" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def name_forms(names: dict[str, str]) -> dict[str, dict]:
    """Sembol → {full: normalize tam ad, short: yasal/genel ekler atılmış baş kısım (≥2 token ya da tek token ≥6
    harf), first: ilk token}. İlk token birden çok sembole aitse belirsiz sayılır."""
    out = {}
    firsts = Counter()
    for sym, name in names.items():
        toks = norm(name).split()
        short = []
        for tok in toks:
            if tok in LEGAL:
                break
            short.append(tok)
        out[sym] = {"full": " ".join(toks), "short": " ".join(short), "first": toks[0] if toks else ""}
        firsts[out[sym]["first"]] += 1
    for sym, f in out.items():
        s = f["short"].split()
        f["short_ok"] = len(s) >= 2 or (len(s) == 1 and len(s[0]) >= 6)
        f["first_ambiguous"] = firsts[f["first"]] > 1
    return out


def company_name_match(text: str, forms: dict[str, dict]) -> dict:
    """Kesin eşleşme katmanları: FULL_NAME > SHORT_NAME > FIRST_TOKEN (yüksek YP riski; belirsiz token hariç)."""
    t = norm(text)
    hits = {"FULL_NAME": [], "SHORT_NAME": [], "FIRST_TOKEN": [], "AMBIGUOUS_FIRST_TOKEN": []}
    for sym, f in sorted(forms.items()):
        if _has(t, f["full"]):
            hits["FULL_NAME"].append(sym)
        elif f["short_ok"] and _has(t, f["short"]):
            hits["SHORT_NAME"].append(sym)
        elif len(f["first"]) >= 4 and _has(t, f["first"]):
            hits["AMBIGUOUS_FIRST_TOKEN" if f["first_ambiguous"] else "FIRST_TOKEN"].append(sym)
    return hits


# ------------------------------------------------------------------ çözümlenemeyen taksonomisi (başlık + açıklama)
_RULES = {
    "E_NON_BIST_COMPANY": ("apple", "tesla", "nvidia", "microsoft", "amazon", "alphabet", "google", "meta",
                           "boeing", "airbus", "toyota", "volkswagen", "samsung", "intel", "netflix", "openai",
                           "jpmorgan", "goldman sachs", "morgan stanley", "berkshire", "shell", "exxon", "aramco"),
    "C_COMMODITY_FX": ("petrol", "brent", "altin", "gumus", "dogal gaz", "bakir", "emtia", "ons", "dolar", "euro",
                       "avro", "kur", "doviz", "sterlin", "yen", "kripto", "bitcoin"),
    "B_FOREIGN_MARKET": ("abd", "avrupa", "asya", "cin", "japonya", "wall street", "nasdaq", "s&p", "dow", "dax",
                         "ftse", "nikkei", "fed", "ecb", "avro bolgesi", "almanya", "ingiltere", "fransa", "rusya",
                         "iran", "israil", "ukrayna", "trump", "demokrat", "kongre", "beyaz saray", "londra"),
    "A_GENERAL_MARKET_MACRO": ("borsa istanbul", "bist", "endeks", "tcmb", "merkez bankasi", "enflasyon", "faiz",
                               "piyasa", "ekonomi", "buyume", "cari", "butce", "issizlik", "ppk", "hazine",
                               "tahvil", "spk", "tufe", "ufe", "imalat", "ihracat", "ithalat", "vergi"),
}
_ORDER = ("D_COMPANY_NAME_NO_TICKER", "E_NON_BIST_COMPANY", "C_COMMODITY_FX", "B_FOREIGN_MARKET",
          "A_GENERAL_MARKET_MACRO")


def classify_unresolved(text: str, name_hits: dict) -> str:
    if name_hits["FULL_NAME"] or name_hits["SHORT_NAME"]:
        return "D_COMPANY_NAME_NO_TICKER"
    t = norm(text)
    for cat in _ORDER[1:]:
        if any(_has(t, norm(k)) for k in _RULES[cat]):
            return cat
    if name_hits["FIRST_TOKEN"] or name_hits["AMBIGUOUS_FIRST_TOKEN"]:
        return "F_AMBIGUOUS"
    return "G_OTHER"


# ------------------------------------------------------------------ istatistik yardımcıları
def dist(v) -> dict:
    a = np.asarray([x for x in v if x is not None], float)
    if not len(a):
        return {"n": 0}
    return {"n": int(len(a)), "median": round(float(np.median(a)), 3), "p25": round(float(np.percentile(a, 25)), 3),
            "p75": round(float(np.percentile(a, 75)), 3), "p90": round(float(np.percentile(a, 90)), 3),
            "min": round(float(a.min()), 3), "max": round(float(a.max()), 3)}


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


# ------------------------------------------------------------------ rapor bölümleri
def collection_health(db, raw_dir: Path) -> dict:
    runs = db.execute("SELECT run_id, status, received_at, finished_at, summary FROM source_runs WHERE "
                      "provider='foreks' AND kind='news_archive' ORDER BY received_at").fetchall()
    ok = [r for r in runs if r[1] == "COMPLETED"]
    summ = [json.loads(r[4] or "{}") for r in ok]
    shas = [s.get("raw_response_sha256") for s in summ if s.get("raw_response_sha256")]
    files = sorted(raw_dir.glob("*/*.xml.gz")) if raw_dir.exists() else []
    valid = sum(hashlib.sha256(gzip.open(f).read()).hexdigest() == f.name.split(".")[0] for f in files)
    return {"total_rss_fetches": len(runs), "successful_fetches": len(ok),
            "failed_fetches": sum(r[1] == "FAILED" for r in runs),
            "last_successful_fetch": ok[-1][3] if ok else None,
            "last_received_at": db.execute("SELECT MAX(received_at) FROM news_events").fetchone()[0],
            "rss_items_per_fetch": dist([s.get("rss_items_in_feed") for s in summ]),
            "new_items_per_fetch": dist([s.get("items_inserted") for s in summ]),
            "duplicates_per_fetch": dist([s.get("duplicates") for s in summ]),
            "runs_with_raw_response": len(shas), "runs_before_raw_saving": len(summ) - len(shas),
            "raw_response_files": len(files), "raw_response_files_hash_valid": valid,
            "distinct_raw_sha_in_runs": len(set(shas)),
            "raw_sha_all_present_on_disk": set(shas) <= {f.name.split(".")[0] for f in files},
            "_runs": [(r[2], r[3], r[1]) for r in runs], "_shas": shas, "_summaries": summ}


def logical_items(db) -> list[dict]:
    """Mantıksal haber = item_key; ilk görülen satırın zamanları (kayıtlar zaten değişmez)."""
    rows = db.execute("SELECT item_key, symbol, published_at, received_at, timestamp_status, headline, event_type, "
                      "content_hash, source_url_hash FROM news_events ORDER BY id").fetchall()
    items: dict[str, dict] = {}
    for k, sym, pub, rec, ts, head, et, ch, uh in rows:
        it = items.setdefault(k, {"item_key": k, "symbols": [], "published_at": pub, "received_at": rec,
                                  "timestamp_status": ts, "headline": head, "event_type": et, "content_hash": ch,
                                  "url_hash": uh})
        it["symbols"].append(sym)
    return list(items.values())


def timestamp_quality(items: list[dict], effective_start: str | None, now: datetime) -> dict:
    n = len(items)
    pub = [i for i in items if i["published_at"]]
    lag = [(_dt(i["received_at"]) - _dt(i["published_at"])).total_seconds() / 60 for i in pub]
    start = _dt(effective_start)
    prosp = [(_dt(i["received_at"]) - _dt(i["published_at"])).total_seconds() / 60 for i in pub
             if start is not None and _dt(i["published_at"]) > start]
    skew = sum(i["timestamp_status"] == "PUBLISHED_AFTER_RECEIVED_CLOCK_SKEW" for i in items)
    future = sum(_dt(i["published_at"]) > now + CLOCK_SKEW_TOLERANCE for i in pub)
    return {"logical_items": n, "published_at_present_pct": _pct(len(pub), n),
            "published_at_missing_pct": _pct(n - len(pub), n), "clock_skew_flagged_pct": _pct(skew, n),
            "future_timestamp_flagged_pct": _pct(future, n),
            "archive_effective_start": effective_start,
            "archival_discovery_lag_minutes_all_items": {"metric_definition": LAG_LABEL, **dist(lag)},
            "archival_discovery_lag_minutes_published_after_start": {
                "metric_definition": LAG_LABEL + "; only items published after the archive began storing (cleaner "
                                     "prospective estimate; 5-min cadence bounds it from above)", **dist(prosp)},
            "initial_backlog_items": len(pub) - len(prosp)}


def _pct(k, n):
    return round(100 * k / n, 2) if n else None


def symbol_resolution(items: list[dict]) -> dict:
    res = [i for i in items if any(s != ad.UNRESOLVED for s in i["symbols"])]
    sym = Counter(s for i in res for s in i["symbols"] if s != ad.UNRESOLVED)
    return {"logical_items": len(items), "resolved_items": len(res), "unresolved_items": len(items) - len(res),
            "resolution_rate_pct": _pct(len(res), len(items)), "unique_resolved_symbols": len(sym),
            "top_resolved_symbols": sym.most_common(15),
            "unresolved_symbol_invented": False}


def unresolved_analysis(items: list[dict], descriptions: dict[str, str], forms: dict[str, dict],
                        universe: set[str]) -> dict:
    unres = [i for i in items if all(s == ad.UNRESOLVED for s in i["symbols"])]
    cats, tiers, examples = Counter(), Counter(), defaultdict(list)
    name_examples = []
    for i in unres:
        text = f"{i['headline']} {descriptions.get(i['item_key'], '')}"
        hits = company_name_match(text, forms)
        cat = classify_unresolved(text, hits)
        cats[cat] += 1
        if len(examples[cat]) < 4:
            examples[cat].append(i["headline"][:110])
        tier = next((t for t in ("FULL_NAME", "SHORT_NAME", "FIRST_TOKEN", "AMBIGUOUS_FIRST_TOKEN") if hits[t]), None)
        tiers[tier or "NONE"] += 1
        if tier and len(name_examples) < 12:
            name_examples.append({"headline": i["headline"][:110], "tier": tier, "symbols": hits[tier],
                                  "in_momentum_universe": [s for s in hits[tier] if s in universe]})
    strict = tiers["FULL_NAME"] + tiers["SHORT_NAME"]
    return {"unresolved_items": len(unres), "taxonomy": {k: cats.get(k, 0) for k in TAXONOMY},
            "taxonomy_examples": dict(examples),
            "company_name_diagnostic": {
                "metadata_source": "scripts/seed_assets.py BIST100 (yfinance legal names; parsed with ast, not "
                                   "executed)", "names_available": len(forms),
                "potentially_resolvable_strict (FULL_NAME/SHORT_NAME)": strict,
                "first_token_only (high false-positive risk)": tiers["FIRST_TOKEN"],
                "ambiguous_first_token": tiers["AMBIGUOUS_FIRST_TOKEN"],
                "still_unresolved": tiers["NONE"], "examples": name_examples,
                "stored_records_mutated": False}}


def duplicate_quality(db, items: list[dict], raw_dir: Path, shas: list[str]) -> dict:
    """Ham yanıtlardan anahtar başına kaç getirmede görüldüğü (yalnız ham yanıtı saklanan getirmeler)."""
    seen = Counter()
    cache = {}
    from app.services.news import foreks_news_provider as fnp
    for h in shas:
        if h not in cache:
            p = raw_dir / h[:2] / f"{h}.xml.gz"
            ents = ad._rss_items(gzip.open(p).read()) if p.exists() else []
            cache[h] = {f"foreks:{fnp._item_id((e.findtext('link') or '').strip(), (e.findtext('guid') or '').strip())}"
                        for e in ents or []}
        seen.update(cache[h])

    def multi(field):
        g = defaultdict(set)
        for i in items:
            if i[field]:
                g[i[field]].add(i["item_key"])
        return sum(len(v) > 1 for v in g.values())
    head = defaultdict(set)
    for i in items:
        head[norm(i["headline"])].add(i["item_key"])
    return {"fetches_with_raw_response": len(shas),
            "item_keys_seen_in_multiple_fetches": sum(c > 1 for c in seen.values()),
            "fetches_per_item_key": dist(list(seen.values())),
            "same_content_hash_different_item_key": multi("content_hash"),
            "same_headline_different_item_key": sum(len(v) > 1 for v in head.values()),
            "same_url_hash_different_item_key": multi("url_hash"),
            "records_rewritten": False}


# ------------------------------------------------------------------ düzenleme / tekrar / depolama çakışması
_LEGACY_RE = re.compile(r"^DUPLICATE_CONFLICT: item_key=(\S+) symbol=(\S+)$")


def revision_quality(db, summaries: list[dict], provider: str = "foreks") -> dict:
    """Üç ayrı durum: DUPLICATE (aynı içerik), SOURCE_REVISION (aynı öğe, sağlayıcı sonradan farklı içerik; normal),
    STORAGE_CONFLICT (depolama/kimlik beklentisini ihlal eden, düzenlemeyle açıklanamayan durum). Eski
    DUPLICATE_CONFLICT satırları denetim kanıtıdır; DEĞİŞTİRİLMEZ, yalnız yorumlanır."""
    legacy = db.execute("SELECT message, raw_hash, received_at FROM source_failures WHERE provider=? AND "
                        "error_type='DUPLICATE_CONFLICT'", (provider,)).fetchall()
    legacy_distinct = {}
    for msg, rh, at in legacy:
        m = _LEGACY_RE.match(msg)
        key = (m.group(1), m.group(2), rh) if m else ("?", "?", rh)
        legacy_distinct.setdefault(key, at)
    revs = db.execute("SELECT item_key, symbol, original_raw_hash, revision_raw_hash, received_at, evidence "
                      "FROM source_revisions WHERE provider=?", (provider,)).fetchall()
    rev_keys = {(k, s_, r) for k, s_, _, r, _, _ in revs}
    distinct = rev_keys | set(legacy_distinct)
    canon = {(k, s_): (rh, rec, uh) for k, s_, rh, rec, uh in db.execute(
        "SELECT item_key, symbol, raw_hash, received_at, source_url_hash FROM news_events WHERE provider=?",
        (provider,)).fetchall()}
    conflicts = []
    by_item = defaultdict(set)
    for (k, _), (rh, _, _) in canon.items():
        by_item[k].add(rh)
    conflicts += [{"type": "SAME_ITEM_DIFFERENT_CANONICAL_CONTENT_ACROSS_SYMBOLS", "item_key": k}
                  for k, v in by_item.items() if len(v) > 1]
    for k, s_, orig, r, rec, _ in revs:
        c = canon.get((k, s_))
        if c is None or c[0] != orig:
            conflicts.append({"type": "REVISION_PROVENANCE_MISMATCH", "item_key": k, "symbol": s_})
        elif _dt(rec) < _dt(c[1]):
            conflicts.append({"type": "REVISION_RECEIVED_BEFORE_ORIGINAL", "item_key": k, "symbol": s_})
    for (k, s_, _r) in legacy_distinct:
        if (k, s_) not in canon:
            conflicts.append({"type": "LEGACY_CONFLICT_WITHOUT_CANONICAL_ROW", "item_key": k, "symbol": s_})
    url = defaultdict(set)
    for (k, _), (_, _, uh) in canon.items():
        if uh:
            url[uh].add(k)
    conflicts += [{"type": "SAME_URL_DIFFERENT_ITEM_KEY", "item_keys": sorted(v)} for v in url.values() if len(v) > 1]
    trig = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    uniq = any("revision_raw_hash" in (sql or "") for (sql,) in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='source_revisions'"))
    dup_rows = db.execute("SELECT COUNT(*) FROM (SELECT provider, item_key, symbol, revision_raw_hash, COUNT(*) c FROM "
                          "source_revisions GROUP BY 1,2,3,4 HAVING c > 1)").fetchone()[0]
    repeats_logged = len(legacy) - len(legacy_distinct)
    # eski özetler known_revision_repeats, yenileri source_revisions_known yazar; ikisi aynı çalıştırmada yok
    repeats_runs = sum((x.get("source_revisions_known") or x.get("known_revision_repeats") or 0)
                       + (x.get("known_conflict_repeats") or 0) for x in summaries)
    write_conflicts = db.execute("SELECT COUNT(*) FROM source_failures WHERE provider=? AND "
                                 "error_type='STORAGE_CONFLICT'", (provider,)).fetchone()[0]
    conflicts += [{"type": "STORAGE_CONFLICT_AT_WRITE"}] * write_conflicts
    return {"duplicates": sum(x.get("duplicates") or 0 for x in summaries),
            "distinct_source_revisions": len(distinct),
            "known_revision_repeats": repeats_logged + repeats_runs,
            "storage_conflicts": len(conflicts), "storage_conflict_examples": conflicts[:5],
            "legacy_conflict_rows": len(legacy),
            "distinct_revision_variants": len(legacy_distinct),
            "legacy_known_revision_repeats": repeats_logged,
            "legacy_revisions_migrated": sum(e == "LEGACY_DUPLICATE_CONFLICT_ROWS" for *_, e in revs),
            "source_revision_rows": len(revs),
            "canonical_rows_immutable": {"news_events_no_update", "news_events_no_delete"} <= trig
            and not any(c["type"].startswith(("SAME_ITEM", "REVISION_PROVENANCE")) for c in conflicts),
            "revision_tracking_deterministic": uniq and dup_rows == 0
            and {"source_revisions_no_update", "source_revisions_no_delete"} <= trig,
            "historical_rows_mutated": False,
            "semantics": {"DUPLICATE": "same logical item, same content hash",
                          "SOURCE_REVISION": "same provider+item_key+symbol, provider later returned different "
                                             "content; canonical row immutable; each distinct revision recorded once",
                          "STORAGE_CONFLICT": "storage/identity expectation violated and not explainable as a "
                                              "provider revision (deterministic checks only; no price data)"}}


def discovery_lag(items: list[dict], runs: list[tuple], max_gap_min: float = 15.0) -> dict:
    """Arşiv keşif gecikmesi iki ayrı nüfusta: toplayıcı çevrimiçiyken yayımlanan (iki ardışık başarılı getirme
    arası <= 15 dk olan aralık içinde) ve toplayıcı/bilgisayar çevrimdışıyken yayımlanan öğeler. Hiçbiri sağlayıcı
    ağ gecikmesi DEĞİLDİR."""
    ok = sorted(_dt(r[0]) for r in runs if r[2] == "COMPLETED")
    online = [(a, b) for a, b in zip(ok, ok[1:]) if (b - a).total_seconds() / 60 <= max_gap_min]
    gaps = [{"from": a.isoformat(), "to": b.isoformat(), "minutes": round((b - a).total_seconds() / 60, 1)}
            for a, b in zip(ok, ok[1:]) if (b - a).total_seconds() / 60 > max_gap_min]
    start = ok[0] if ok else None
    inside, offline = [], []
    for i in items:
        if not i["published_at"]:
            continue
        p, r = _dt(i["published_at"]), _dt(i["received_at"])
        if start is None or p <= start:
            continue  # arşiv başlamadan önceki birikim (ayrı raporlanır)
        lag = (r - p).total_seconds() / 60
        (inside if any(a <= p <= b for a, b in online) else offline).append(lag)
    return {"metric_definition": LAG_LABEL,
            "collection_window_items": {"population": "ARCHIVAL DISCOVERY LAG - published while collector online",
                                        **dist(inside)},
            "offline_discovery_items": {"population": "ARCHIVAL DISCOVERY LAG - published while collector/machine "
                                                 "offline (NOT provider delay)", **dist(offline)},
            "collector_offline_gap_detected": bool(gaps), "offline_gap_count": len(gaps),
            "offline_gap_minutes_total": round(sum(g["minutes"] for g in gaps), 1), "offline_gaps": gaps[-10:]}


def event_types(items: list[dict]) -> dict:
    c = Counter(i["event_type"] for i in items)
    return {"source": "headline-only rule classification (no price information)",
            "counts": {k: c.get(k, 0) for k in EVENT_TYPES}}


def continuity(runs: list[tuple], now: datetime) -> dict:
    """Hafta içi 09:30–18:40 (İstanbul) penceresinde ardışık başarılı getirmeler arası en büyük boşluk; gün sayısı."""
    from app.engines.technical.session_timing import ISTANBUL_TZ
    ok = sorted(_dt(r[0]).astimezone(ISTANBUL_TZ) for r in runs if r[2] == "COMPLETED")
    by_day = defaultdict(list)
    for t in ok:
        if t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) <= (18, 45):
            by_day[t.date()].append(t)
    gaps = {str(d): round(max([(b - a).total_seconds() / 60 for a, b in zip(v, v[1:])] or [0]), 1)
            for d, v in by_day.items()}
    return {"days_with_fetches": len(by_day), "max_gap_minutes_by_day": gaps,
            "first_fetch": ok[0].isoformat() if ok else None, "last_fetch": ok[-1].isoformat() if ok else None}


def scheduler_health(task: str = TASK_NAME) -> dict:
    """Salt okunur: Get-ScheduledTask / Get-ScheduledTaskInfo (görev değiştirilmez)."""
    if sys.platform != "win32":
        return {"status": "NOT_WINDOWS"}
    cmd = (f"$t = Get-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue; if (-not $t) {{ 'null' }} else "
           f"{{ $i = Get-ScheduledTaskInfo -TaskName '{task}'; [ordered]@{{state=[string]$t.State; "
           "last_run=$i.LastRunTime.ToString('o'); last_result=$i.LastTaskResult; next_run=$i.NextRunTime.ToString('o'); "
           "missed_runs=$i.NumberOfMissedRuns} | ConvertTo-Json }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout) or {"status": "TASK_NOT_FOUND"}
    except json.JSONDecodeError:
        return {"status": "UNREADABLE", "stderr": r.stderr[:300]}


def recent_log_failures(log_dir: Path = LOG_DIR, n_files: int = 5) -> dict:
    files = sorted(log_dir.glob("news_archive_*.log"))[-n_files:] if log_dir.exists() else []
    lines = [json.loads(x) for f in files for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    bad = [x for x in lines if x.get("exit_code") not in (0, None) or x.get("status") not in ("COMPLETED",
                                                                                              "SKIPPED_ALREADY_RUNNING")]
    return {"log_lines": len(lines), "non_ok_lines": len(bad), "skipped_already_running":
            sum(x.get("status") == "SKIPPED_ALREADY_RUNNING" for x in lines), "examples": bad[-3:]}


def readiness(coll: dict, ts: dict, rev: dict, res: dict, cont: dict, integrity_ok: bool = True) -> dict:
    gaps_ok = all(g <= READINESS["max_gap_minutes_in_window"] for g in cont["max_gap_minutes_by_day"].values())
    raw_ok = coll["raw_sha_all_present_on_disk"] and coll["raw_response_files"] == coll["raw_response_files_hash_valid"]
    checks = {
        "published_at_quality": (ts["published_at_present_pct"] or 0) >= 100 * READINESS["published_at_present_min"],
        "received_at_quality": (ts["clock_skew_flagged_pct"] or 0) <= 100 * READINESS["clock_skew_max"]
        and ts["future_timestamp_flagged_pct"] == 0,
        # SOURCE_REVISION tek başına başarısızlık DEĞİL; gerçek STORAGE_CONFLICT ve bütünlük ihlali başarısızlık
        "duplicate_revision_handling": rev["canonical_rows_immutable"] and rev["revision_tracking_deterministic"]
        and rev["storage_conflicts"] <= READINESS["storage_conflicts_max"] and integrity_ok,
        "raw_response_preservation": raw_ok,
        "source_continuity_gaps": gaps_ok and coll["failed_fetches"] == 0,
        "source_continuity_days": cont["days_with_fetches"] >= READINESS["continuity_days_min"],
        "symbol_coverage_measured": res["logical_items"] > 0}
    quality = [k for k in checks if k != "source_continuity_days"]
    if all(checks.values()):
        verdict = "READY"
    elif all(checks[k] for k in quality):
        verdict = "PARTIALLY_READY"
    else:
        verdict = "NOT_READY"
    return {"criteria": READINESS, "checks": checks, "verdict": verdict,
            "note": "readiness of DATA only; whether news predicts returns is NOT assessed"}


def report(root: Path = DEFAULT_ROOT, raw_dir: Path = RAW_DIR / "foreks", now: datetime | None = None,
           with_scheduler: bool = True, universe: set[str] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    s = SecondaryStore(root, readonly=True)
    try:
        coll = collection_health(s.db, raw_dir)
        items = logical_items(s.db)
        eff = s.db.execute("SELECT MIN(received_at) FROM news_events").fetchone()[0]
        desc = descriptions_from_raw(raw_dir, coll["_shas"])
        if universe is None:
            from app.research.momentum_collector import manifest as mm
            universe = set(mm.load()["config"]["universe"])
        forms = name_forms(load_company_names())
        ts = timestamp_quality(items, eff, now)
        res = symbol_resolution(items)
        unr = unresolved_analysis(items, desc, forms, universe)
        dup = duplicate_quality(s.db, items, raw_dir, coll["_shas"])
        rev = revision_quality(s.db, coll["_summaries"])
        lag = discovery_lag(items, coll["_runs"])
        cont = continuity(coll["_runs"], now)
        integrity_ok = s.integrity()["ok"]
    finally:
        s.close()
    out = {"generated_at": now.isoformat(), "scope": "DATA QUALITY ONLY (no prices, events, alerts or outcomes)",
           "foreks_health": {k: v for k, v in coll.items() if not k.startswith("_")}, "rss_continuity": cont,
           "timestamp_quality": ts, "discovery_lag": lag, "symbol_resolution": res, "unresolved": unr,
           "duplicate_quality": dup, "revision_quality": rev, "event_type_distribution": event_types(items),
           "catalyst_readiness": readiness(coll, ts, rev, res, cont, integrity_ok)}
    if with_scheduler:
        out["news_scheduler"] = {**scheduler_health(), "log": recent_log_failures()}
    return out


def descriptions_from_raw(raw_dir: Path, shas: list[str]) -> dict[str, str]:
    """Açıklama metni depoda tutulmuyor; ham yanıtlardan (aynı ayrıştırma kuralıyla) yalnız okunur."""
    from app.services.news import foreks_news_provider as fnp
    out = {}
    for h in dict.fromkeys(shas):
        p = raw_dir / h[:2] / f"{h}.xml.gz"
        if not p.exists():
            continue
        for e in ad._rss_items(gzip.open(p).read()) or []:
            k = f"foreks:{fnp._item_id((e.findtext('link') or '').strip(), (e.findtext('guid') or '').strip())}"
            out.setdefault(k, fnp._clean_html(e.findtext("description")))
    return out


def main() -> int:
    print(json.dumps(report(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
