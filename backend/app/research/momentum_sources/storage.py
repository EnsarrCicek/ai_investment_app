"""İkincil kaynak deposu (`momentum_secondary/`) — Yahoo tablolarından AYRI, yalnız araştırma, Firestore YOK.

Her tablo provider, source_timestamp (yoksa NULL), received_at, raw_hash ve source_role (= EXPERIMENTAL_SECONDARY,
CHECK kısıtı) taşır. Veri tabloları append-only (UPDATE/DELETE tetikleyiciyle engellenir; yalnız `source_runs`
bitişte güncellenir). Tekrarlayan kayıt: ilk görülen saklanır (deterministik); aynı anahtar farklı içerikle gelirse
`source_failures`'a DUPLICATE_CONFLICT yazılır, orijinal değişmez. Sağlayıcılar tek tabloda bile birleştirilmez:
benzersizlik anahtarı her zaman `provider` içerir.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.research.momentum_collector import manifest as mm
from app.research.momentum_sources.common import SECONDARY_ROLE, SourceContractError, raw_hash

HERE = Path(__file__).parent
DEFAULT_ROOT = HERE / "store" / "momentum_secondary"
DB_NAME = "secondary.sqlite"
NAMESPACE = "momentum_secondary"
YAHOO_STORE = (mm.HERE / "store").resolve()
CONFLICT_KNOWN = "DUPLICATE_CONFLICT_KNOWN"  # daha önce kaydedilmiş aynı çakışmanın tekrar görülmesi
SOURCE_REVISION = "SOURCE_REVISION"  # source_revisions.revision_type satır türü
SOURCE_REVISION_NEW = "SOURCE_REVISION_NEW"  # aynı öğenin (item_key × sembol) ilk kez görülen farklı içeriği
REVISION_KNOWN = "SOURCE_REVISION_KNOWN"  # daha önce kaydedilmiş aynı düzenlemenin tekrar görülmesi
STORAGE_CONFLICT = "STORAGE_CONFLICT"  # kimlik/depolama beklentisi ihlali (düzenlemeyle açıklanamaz)
APPEND_ONLY = ("trade_ticks", "order_flow", "order_book", "news_events", "source_failures", "source_metadata",
               "source_revisions",
               "kap_disclosures", "kap_members", "kap_securities", "kap_attachments_metadata", "kap_failures",
               "kap_checkpoints")
_ROLE = f"source_role TEXT NOT NULL CHECK (source_role = '{SECONDARY_ROLE}')"
_COMMON = ("provider TEXT NOT NULL, source_timestamp TEXT, received_at TEXT NOT NULL, received_ns INTEGER NOT NULL, "
           "timestamp_status TEXT NOT NULL, raw_hash TEXT NOT NULL, identity_status TEXT NOT NULL, " + _ROLE)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_runs(run_id TEXT PRIMARY KEY, provider TEXT NOT NULL, kind TEXT NOT NULL,
  source_timestamp TEXT, received_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, summary TEXT,
  raw_hash TEXT NOT NULL, {_ROLE});
CREATE TABLE IF NOT EXISTS trade_ticks(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, symbol TEXT NOT NULL,
  exchange TEXT, currency TEXT, trade_id TEXT, dedup_key TEXT NOT NULL, provider_latency_ms INTEGER,
  price REAL NOT NULL, quantity REAL NOT NULL, buyer_member TEXT, seller_member TEXT,
  aggressor_side TEXT NOT NULL CHECK (aggressor_side IN ('BUY','SELL','UNKNOWN')), aggressor_provenance TEXT,
  run_id TEXT, UNIQUE(provider, symbol, dedup_key));
CREATE TABLE IF NOT EXISTS order_flow(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, symbol TEXT NOT NULL,
  status TEXT NOT NULL, fields TEXT NOT NULL, run_id TEXT, UNIQUE(provider, symbol, raw_hash));
CREATE TABLE IF NOT EXISTS order_book(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, symbol TEXT NOT NULL,
  depth INTEGER NOT NULL CHECK (depth IN (1,5,10,25)), update_type TEXT NOT NULL, sequence TEXT,
  levels TEXT NOT NULL, run_id TEXT, UNIQUE(provider, symbol, raw_hash));
CREATE TABLE IF NOT EXISTS news_events(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, source TEXT,
  symbol TEXT NOT NULL, company TEXT, published_at TEXT, headline TEXT NOT NULL, event_type TEXT NOT NULL,
  event_importance TEXT, source_url_hash TEXT, content_hash TEXT NOT NULL, published_at_semantics TEXT,
  item_key TEXT NOT NULL, run_id TEXT, UNIQUE(provider, item_key, symbol));
CREATE TABLE IF NOT EXISTS source_revisions(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
  item_key TEXT NOT NULL, symbol TEXT NOT NULL, original_raw_hash TEXT NOT NULL, revision_raw_hash TEXT NOT NULL,
  first_seen_revision_at TEXT NOT NULL, source_timestamp TEXT, received_at TEXT NOT NULL,
  revision_type TEXT NOT NULL CHECK (revision_type = 'SOURCE_REVISION'), headline TEXT, content_hash TEXT,
  evidence TEXT NOT NULL, run_id TEXT, {_ROLE},
  UNIQUE(provider, item_key, symbol, revision_raw_hash));
CREATE TABLE IF NOT EXISTS source_failures(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, provider TEXT NOT NULL,
  source_timestamp TEXT, received_at TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL, raw_hash TEXT,
  {_ROLE});
CREATE TABLE IF NOT EXISTS source_metadata(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
  key TEXT NOT NULL, value TEXT NOT NULL, source_timestamp TEXT, received_at TEXT NOT NULL, raw_hash TEXT NOT NULL,
  {_ROLE});
-- Resmi KAP API (Foreks news_events'ten AYRI; aynı olay iki sağlayıcıda ayrı kayıt olarak kalır)
CREATE TABLE IF NOT EXISTS kap_runs(run_id TEXT PRIMARY KEY, provider TEXT NOT NULL, kind TEXT NOT NULL,
  source_timestamp TEXT, received_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, summary TEXT,
  raw_hash TEXT NOT NULL, {_ROLE});
CREATE TABLE IF NOT EXISTS kap_disclosures(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, disclosure_id TEXT NOT NULL,
  disclosure_index INTEGER, member_code TEXT, member_name TEXT, symbol TEXT, isin TEXT, disclosure_type TEXT,
  subject TEXT, summary TEXT, detail_available INTEGER, attachments_available INTEGER, run_id TEXT,
  UNIQUE(provider, disclosure_id));
CREATE TABLE IF NOT EXISTS kap_members(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, member_id TEXT,
  member_code TEXT, member_name TEXT, run_id TEXT, UNIQUE(provider, raw_hash));
CREATE TABLE IF NOT EXISTS kap_securities(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON}, member_id TEXT,
  member_code TEXT, symbol TEXT, isin TEXT, security_type TEXT, exchange TEXT, run_id TEXT,
  UNIQUE(provider, raw_hash));
CREATE TABLE IF NOT EXISTS kap_attachments_metadata(id INTEGER PRIMARY KEY AUTOINCREMENT, {_COMMON},
  disclosure_id TEXT NOT NULL, attachment_ref TEXT, content_sha256 TEXT, size_bytes INTEGER, run_id TEXT,
  UNIQUE(provider, disclosure_id, raw_hash));
CREATE TABLE IF NOT EXISTS kap_failures(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, provider TEXT NOT NULL,
  source_timestamp TEXT, received_at TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL, raw_hash TEXT,
  {_ROLE});
CREATE TABLE IF NOT EXISTS kap_checkpoints(id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
  disclosure_index INTEGER NOT NULL, run_id TEXT NOT NULL, source_timestamp TEXT, received_at TEXT NOT NULL,
  raw_hash TEXT NOT NULL, {_ROLE});
"""


def _triggers() -> str:
    return "\n".join(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} BEGIN "
                     f"SELECT RAISE(ABORT, 'append-only: {t}'); END;" for t in APPEND_ONLY for op in ("UPDATE", "DELETE"))


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(timezone.utc).isoformat()


def _ns(t: datetime) -> int:
    return int(t.timestamp() * 1e9)


class SecondaryStore:
    def __init__(self, root: Path = DEFAULT_ROOT, readonly: bool = False):
        root = Path(root)
        if YAHOO_STORE in (root.resolve(), *root.resolve().parents):
            raise SourceContractError("ikincil depo Yahoo toplayıcı deposunun içinde olamaz (ayrı ad alanı)")
        self.root = root
        self.path = root / DB_NAME
        if readonly:
            self.db = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
            return
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA + _triggers())
        got = self.db.execute("SELECT value FROM meta WHERE key='namespace'").fetchone()
        if got is None:
            self.db.execute("INSERT INTO meta VALUES ('namespace', ?)", (NAMESPACE,))
        elif got[0] != NAMESPACE:
            raise SourceContractError(f"depo ad alanı {got[0]}; {NAMESPACE} olarak açılamaz")

    def close(self):
        self.db.close()

    # ---- çalıştırma ve hata kaydı
    def begin_run(self, provider: str, kind: str, params: dict, now: datetime) -> str:
        h = raw_hash({"provider": provider, "kind": kind, "params": params})
        run_id = f"{provider}-{kind}-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{h[:8]}"
        self.db.execute("INSERT INTO source_runs(run_id, provider, kind, received_at, status, raw_hash, source_role) "
                        "VALUES (?,?,?,?,?,?,?)", (run_id, provider, kind, _iso(now), "RUNNING", h, SECONDARY_ROLE))
        return run_id

    def finish_run(self, run_id: str, now: datetime, status: str, summary: dict) -> None:
        self.db.execute("UPDATE source_runs SET finished_at=?, status=?, summary=? WHERE run_id=?",
                        (_iso(now), status, json.dumps(summary, sort_keys=True, default=str), run_id))

    def log_failure(self, run_id: str | None, provider: str, now: datetime, error: BaseException | str,
                    source_timestamp: datetime | None = None, rh: str | None = None) -> None:
        etype = type(error).__name__ if isinstance(error, BaseException) else str(error).split(":")[0]
        self.db.execute("INSERT INTO source_failures(run_id, provider, source_timestamp, received_at, error_type, "
                        "message, raw_hash, source_role) VALUES (?,?,?,?,?,?,?,?)",
                        (run_id, provider, _iso(source_timestamp), _iso(now), etype, str(error)[:2000], rh,
                         SECONDARY_ROLE))

    def record_metadata(self, provider: str, key: str, value, now: datetime,
                        source_timestamp: datetime | None = None) -> None:
        v = json.dumps(value, sort_keys=True, default=str)
        self.db.execute("INSERT INTO source_metadata(provider, key, value, source_timestamp, received_at, raw_hash, "
                        "source_role) VALUES (?,?,?,?,?,?,?)",
                        (provider, key, v, _iso(source_timestamp), _iso(now), raw_hash([provider, key, v]),
                         SECONDARY_ROLE))

    # ---- veri yazımı (ilk görülen saklanır)
    def add_trade(self, t, run_id: str | None = None) -> str:
        """'NEW' / 'DUPLICATE' / 'DUPLICATE_CONFLICT'. `t`: matriks.models.TradeTick."""
        key = t.trade_id or t.raw_hash
        lat = t.provider_latency
        cur = self.db.execute(
            "INSERT OR IGNORE INTO trade_ticks(provider, source_timestamp, received_at, received_ns, timestamp_status, "
            "raw_hash, identity_status, source_role, symbol, exchange, currency, trade_id, dedup_key, "
            "provider_latency_ms, price, quantity, buyer_member, seller_member, aggressor_side, aggressor_provenance, "
            "run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.provider, _iso(t.source_timestamp), _iso(t.received_at), _ns(t.received_at), t.timestamp_status,
             t.raw_hash, t.identity_status, t.source_role, t.symbol, t.exchange, t.currency, t.trade_id, key,
             None if lat is None else int(lat.total_seconds() * 1000), t.price, t.quantity, t.buyer_member,
             t.seller_member, t.aggressor_side, t.aggressor_provenance, run_id))
        if cur.rowcount:
            return "NEW"
        old = self.db.execute("SELECT raw_hash FROM trade_ticks WHERE provider=? AND symbol=? AND dedup_key=?",
                              (t.provider, t.symbol, key)).fetchone()[0]
        if old == t.raw_hash:
            return "DUPLICATE"
        msg = f"DUPLICATE_CONFLICT: trade_id={t.trade_id}"
        if self._conflict_known("source_failures", t.provider, msg, t.raw_hash):
            return CONFLICT_KNOWN
        self.log_failure(run_id, t.provider, t.received_at, msg, t.source_timestamp, t.raw_hash)
        return "DUPLICATE_CONFLICT"

    def _conflict_known(self, table: str, provider: str, message: str, rh: str) -> bool:
        """Aynı anahtar + aynı yeni içerik (raw_hash) çakışması zaten kayıtlı mı? Kaynak bir öğeyi bir kez düzenleyip
        sonraki her getirmede aynı düzenlenmiş hali döndürdüğünde çakışma YALNIZ bir kez kaydedilir."""
        return self.db.execute(f"SELECT 1 FROM {table} WHERE provider=? AND error_type='DUPLICATE_CONFLICT' AND "
                               "message=? AND raw_hash=? LIMIT 1", (provider, message, rh)).fetchone() is not None

    def add_order_flow(self, s, run_id: str | None = None) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO order_flow(provider, source_timestamp, received_at, received_ns, timestamp_status, "
            "raw_hash, identity_status, source_role, symbol, status, fields, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.provider, _iso(s.source_timestamp), _iso(s.received_at), _ns(s.received_at), s.timestamp_status,
             s.raw_hash, s.identity_status, s.source_role, s.symbol, s.status,
             json.dumps(s.fields(), sort_keys=True), run_id))
        return bool(cur.rowcount)

    def add_order_book(self, b, run_id: str | None = None) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO order_book(provider, source_timestamp, received_at, received_ns, timestamp_status, "
            "raw_hash, identity_status, source_role, symbol, depth, update_type, sequence, levels, run_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (b.provider, _iso(b.source_timestamp), _iso(b.received_at), _ns(b.received_at), b.timestamp_status,
             b.raw_hash, b.identity_status, b.source_role, b.symbol, b.depth, b.update_type, b.sequence,
             json.dumps([asdict(lv) for lv in b.levels], sort_keys=True), run_id))
        return bool(cur.rowcount)

    def add_news(self, n, run_id: str | None = None) -> str:
        """'NEW' / 'DUPLICATE' / 'SOURCE_REVISION_NEW' / 'SOURCE_REVISION_KNOWN' / 'STORAGE_CONFLICT'. Mantıksal
        anahtar = sağlayıcının
        kalıcı öğe kimliği (`item_key`, yoksa raw_hash) × sembol.

        * DUPLICATE: aynı öğe, aynı içerik (raw_hash).
        * SOURCE_REVISION_NEW: aynı öğe, sağlayıcı sonradan FARKLI içerik döndürdü (ör. başlık düzenlemesi). Kanonik
          `news_events` satırı DEĞİŞMEZ; her farklı düzenleme `source_revisions`'a bir kez yazılır.
        * SOURCE_REVISION_KNOWN: zaten kayıtlı düzenleme tekrar görüldü (yeni satır yok, hata değil).
        * STORAGE_CONFLICT: ekleme yok sayıldı ama kanonik satır bulunamadı ya da düzenleme satırı yazılamadı;
          `source_failures`'a bir kez kaydedilir, hiçbir satır değiştirilmez.
        Eski sürümün `source_failures` DUPLICATE_CONFLICT satırları denetim kanıtıdır, değiştirilmez; böyle bir eski
        kayıt varsa düzenleme ilk görülme zamanı o kayıttan alınarak `source_revisions`'a bir kez taşınır."""
        key = n.item_key or n.raw_hash
        cur = self.db.execute(
            "INSERT OR IGNORE INTO news_events(provider, source_timestamp, received_at, received_ns, timestamp_status, "
            "raw_hash, identity_status, source_role, source, symbol, company, published_at, headline, event_type, "
            "event_importance, source_url_hash, content_hash, published_at_semantics, item_key, run_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (n.provider, _iso(n.published_at), _iso(n.received_at), _ns(n.received_at), n.timestamp_status,
             n.raw_hash, n.identity_status, n.source_role, n.source, n.symbol, n.company, _iso(n.published_at),
             n.headline, n.event_type, n.event_importance, n.source_url_hash, n.content_hash,
             n.published_at_semantics, key, run_id))
        if cur.rowcount:
            return "NEW"
        row = self.db.execute("SELECT raw_hash FROM news_events WHERE provider=? AND item_key=? AND symbol=?",
                              (n.provider, key, n.symbol)).fetchone()
        if row is None:
            return self._storage_conflict(n, key, run_id, "canonical row missing after ignored insert")
        old = row[0]
        if old == n.raw_hash:
            return "DUPLICATE"
        return self._record_revision(n, key, old, run_id)

    def _record_revision(self, n, key: str, original: str, run_id: str | None) -> str:
        if self.db.execute("SELECT 1 FROM source_revisions WHERE provider=? AND item_key=? AND symbol=? AND "
                           "revision_raw_hash=?", (n.provider, key, n.symbol, n.raw_hash)).fetchone():
            return REVISION_KNOWN
        legacy = self.db.execute("SELECT MIN(received_at) FROM source_failures WHERE provider=? AND "
                                 "error_type='DUPLICATE_CONFLICT' AND message=? AND raw_hash=?",
                                 (n.provider, f"DUPLICATE_CONFLICT: item_key={key} symbol={n.symbol}",
                                  n.raw_hash)).fetchone()[0]
        first_seen = legacy or _iso(n.received_at)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO source_revisions(provider, item_key, symbol, original_raw_hash, revision_raw_hash, "
            "first_seen_revision_at, source_timestamp, received_at, revision_type, headline, content_hash, evidence, "
            "run_id, source_role) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (n.provider, key, n.symbol, original, n.raw_hash, first_seen, _iso(n.published_at), _iso(n.received_at),
             SOURCE_REVISION, n.headline, n.content_hash,
             "LEGACY_DUPLICATE_CONFLICT_ROWS" if legacy else "OBSERVED", run_id, SECONDARY_ROLE))
        if not cur.rowcount:
            return self._storage_conflict(n, key, run_id, "revision row not written")
        return REVISION_KNOWN if legacy else SOURCE_REVISION_NEW

    def _storage_conflict(self, n, key: str, run_id: str | None, why: str) -> str:
        msg = f"STORAGE_CONFLICT: item_key={key} symbol={n.symbol} ({why})"
        if not self.db.execute("SELECT 1 FROM source_failures WHERE provider=? AND error_type='STORAGE_CONFLICT' AND "
                               "message=? AND raw_hash IS ?", (n.provider, msg, n.raw_hash)).fetchone():
            self.db.execute("INSERT INTO source_failures(run_id, provider, source_timestamp, received_at, error_type, "
                            "message, raw_hash, source_role) VALUES (?,?,?,?,?,?,?,?)",
                            (run_id, n.provider, _iso(n.published_at), _iso(n.received_at), STORAGE_CONFLICT, msg,
                             n.raw_hash, SECONDARY_ROLE))
        return STORAGE_CONFLICT

    # ---- durum (model metriği YOK)
    # ---- resmi KAP (ayrı tablolar; Foreks ile birleştirme yok)
    def begin_kap_run(self, kind: str, params: dict, now: datetime, provider: str = "kap_official") -> str:
        h = raw_hash({"provider": provider, "kind": kind, "params": params})
        run_id = f"{provider}-{kind}-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{h[:8]}"
        self.db.execute("INSERT INTO kap_runs(run_id, provider, kind, received_at, status, raw_hash, source_role) "
                        "VALUES (?,?,?,?,?,?,?)", (run_id, provider, kind, _iso(now), "RUNNING", h, SECONDARY_ROLE))
        return run_id

    def finish_kap_run(self, run_id: str, now: datetime, status: str, summary: dict) -> None:
        self.db.execute("UPDATE kap_runs SET finished_at=?, status=?, summary=? WHERE run_id=?",
                        (_iso(now), status, json.dumps(summary, sort_keys=True, default=str), run_id))

    def log_kap_failure(self, run_id: str | None, now: datetime, error, provider: str = "kap_official",
                        source_timestamp: datetime | None = None, rh: str | None = None) -> None:
        etype = type(error).__name__ if isinstance(error, BaseException) else str(error).split(":")[0]
        self.db.execute("INSERT INTO kap_failures(run_id, provider, source_timestamp, received_at, error_type, message, "
                        "raw_hash, source_role) VALUES (?,?,?,?,?,?,?,?)",
                        (run_id, provider, _iso(source_timestamp), _iso(now), etype, str(error)[:2000], rh,
                         SECONDARY_ROLE))

    def add_kap_disclosure(self, d, run_id: str | None = None) -> str:
        """Mantıksal anahtar = sağlayıcı + RESMİ bildirim kimliği (semantiği çağıran tarafta doğrulanmış olmalı).
        'NEW' / 'DUPLICATE' / 'DUPLICATE_CONFLICT' (orijinal değişmez)."""
        if not d.disclosure_id:
            raise SourceContractError("resmi bildirim kimliği yok: kayıt anahtarı uydurulmaz")
        cur = self.db.execute(
            "INSERT OR IGNORE INTO kap_disclosures(provider, source_timestamp, received_at, received_ns, "
            "timestamp_status, raw_hash, identity_status, source_role, disclosure_id, disclosure_index, member_code, "
            "member_name, symbol, isin, disclosure_type, subject, summary, detail_available, attachments_available, "
            "run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.provider, _iso(d.source_timestamp), _iso(d.received_at), _ns(d.received_at), d.timestamp_status,
             d.raw_hash, d.identity_status, d.source_role, d.disclosure_id, d.disclosure_index, d.member_code,
             d.member_name, d.symbol, d.isin, d.disclosure_type, d.subject, d.summary, d.detail_available,
             d.attachments_available, run_id))
        if cur.rowcount:
            return "NEW"
        old = self.db.execute("SELECT raw_hash FROM kap_disclosures WHERE provider=? AND disclosure_id=?",
                              (d.provider, d.disclosure_id)).fetchone()[0]
        if old == d.raw_hash:
            return "DUPLICATE"
        msg = f"DUPLICATE_CONFLICT: disclosure_id={d.disclosure_id}"
        if self._conflict_known("kap_failures", d.provider, msg, d.raw_hash):
            return CONFLICT_KNOWN
        self.log_kap_failure(run_id, d.received_at, msg, d.provider, d.source_timestamp, d.raw_hash)
        return "DUPLICATE_CONFLICT"

    def add_kap_checkpoint(self, index: int, run_id: str, now: datetime, provider: str = "kap_official") -> None:
        self.db.execute("INSERT INTO kap_checkpoints(provider, disclosure_index, run_id, received_at, raw_hash, "
                        "source_role) VALUES (?,?,?,?,?,?)",
                        (provider, int(index), run_id, _iso(now), raw_hash([provider, int(index), run_id]),
                         SECONDARY_ROLE))

    def kap_checkpoint(self, provider: str = "kap_official") -> int | None:
        return self.db.execute("SELECT MAX(disclosure_index) FROM kap_checkpoints WHERE provider=?",
                               (provider,)).fetchone()[0]

    def integrity(self) -> dict:
        trig = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        need = {f"{t}_no_{op}" for t in APPEND_ONLY for op in ("update", "delete")}
        bad_role = sum(self.db.execute(f"SELECT COUNT(*) FROM {t} WHERE source_role != ?", (SECONDARY_ROLE,))
                       .fetchone()[0] for t in (*APPEND_ONLY, "source_runs", "kap_runs"))
        return {"sqlite_integrity": self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                "append_only_triggers": need <= trig, "non_secondary_rows": bad_role,
                "ok": self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and need <= trig
                and bad_role == 0}

    def stats(self) -> dict:
        out = {}
        for t in ("trade_ticks", "order_flow", "order_book", "news_events"):
            rows = self.db.execute(f"SELECT provider, COUNT(*), MAX(received_at) FROM {t} GROUP BY provider").fetchall()
            per = {}
            for prov, n, last in rows:
                ident = dict(self.db.execute(f"SELECT identity_status, COUNT(*) FROM {t} WHERE provider=? GROUP BY 1",
                                             (prov,)).fetchall())
                ts = dict(self.db.execute(f"SELECT timestamp_status, COUNT(*) FROM {t} WHERE provider=? GROUP BY 1",
                                          (prov,)).fetchall())
                lat = [(datetime.fromisoformat(r) - datetime.fromisoformat(s)).total_seconds()
                       for s, r in self.db.execute(f"SELECT source_timestamp, received_at FROM {t} WHERE provider=? "
                                                   "AND source_timestamp IS NOT NULL", (prov,)).fetchall()]
                per[prov] = {"rows": n, "last_received_at": last, "identity_status": ident,
                             "timestamp_status": ts, "latency_seconds": _lat(lat)}
            out[t] = per
        out["failures"] = dict(self.db.execute("SELECT provider || ':' || error_type, COUNT(*) FROM source_failures "
                                               "GROUP BY 1").fetchall())
        out["runs"] = dict(self.db.execute("SELECT status, COUNT(*) FROM source_runs GROUP BY 1").fetchall())
        out["kap"] = {"disclosures": self.db.execute("SELECT COUNT(*) FROM kap_disclosures").fetchone()[0],
                      "last_received_at": self.db.execute("SELECT MAX(received_at) FROM kap_disclosures").fetchone()[0],
                      "checkpoint": self.kap_checkpoint(),
                      "runs": dict(self.db.execute("SELECT status, COUNT(*) FROM kap_runs GROUP BY 1").fetchall()),
                      "failures": dict(self.db.execute("SELECT error_type, COUNT(*) FROM kap_failures GROUP BY 1")
                                       .fetchall())}
        return out


def _lat(v: list[float]) -> dict:
    if not v:
        return {"n": 0}
    a = np.asarray(v, float)
    return {"n": int(len(a)), "median": round(float(np.median(a)), 3), "p90": round(float(np.percentile(a, 90)), 3),
            "min": round(float(a.min()), 3), "max": round(float(a.max()), 3)}
