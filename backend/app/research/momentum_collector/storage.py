"""İleriye dönük momentum arşivi — yerel SQLite + içerik adresli ham yanıtlar (YALNIZ araştırma; Firestore YOK).

Tasarım:
* `bars`: tamamlanmış barın İLK görülen hali (FIRST_SEEN). Anahtar (symbol, interval, bar_start). UPDATE/DELETE
  tetikleyiciyle engellenir (append-only); tekrar görülen aynı bar yazılmaz.
* `bar_revision`: sağlayıcı sonradan farklı OHLCV verirse (orijinal satır değişmez) — original/previous/new hash,
  observed_at, changed_fields.
* `partial_bars`: oluşmakta olan barın her farklı gözlemi (append-only); `bar_finalization` tamamlanmış barla ilişki.
* `requests` / `fetch_failures` / `probe_observations` / `runs`: denetim izi. Başarısız istek bar YAZMAZ.
* Her yanıt tek SQLite işleminde (BEGIN IMMEDIATE … COMMIT) yazılır; çökme → geri alma, arşiv bozulmaz. Ham yanıt
  önce içerik hash'iyle geçici dosya → `os.replace` ile yazılır (yetim dosya zararsız, yeniden çalıştırma idempotent).
* Önyargısızlık: değerlendirici T anında yalnız first_seen_at ≤ T ve bar_end ≤ T barlarını (ve observed_at ≤ T
  revizyonlarını) okuyabilir (`bars_as_of`).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_collector import manifest as mm

STORE = mm.HERE / "store"
PRIMARY_ROOT = STORE / "primary"
PREFLIGHT_ROOT = STORE / "preflight"
INTERVAL_NS = {"1m": 60_000_000_000, "5m": 300_000_000_000}
FIELDS = ("open", "high", "low", "close", "volume")
APPEND_ONLY = ("requests", "bars", "partial_bars", "bar_revision", "bar_finalization", "fetch_failures",
               "probe_observations", "eod_verifications")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, summary TEXT);
CREATE TABLE IF NOT EXISTS requests(request_hash TEXT PRIMARY KEY, run_id TEXT NOT NULL, symbol TEXT NOT NULL,
  interval TEXT NOT NULL, provider_symbol TEXT, params TEXT NOT NULL, retrieved_at TEXT NOT NULL,
  response_hash TEXT NOT NULL, n_bars INTEGER NOT NULL, currency TEXT, exchange TEXT, identity_check TEXT NOT NULL,
  source TEXT NOT NULL, raw_path TEXT);
CREATE TABLE IF NOT EXISTS bars(symbol TEXT NOT NULL, interval TEXT NOT NULL, bar_start_ns INTEGER NOT NULL,
  bar_start TEXT NOT NULL, bar_end_ns INTEGER NOT NULL, bar_end TEXT NOT NULL, bar_start_local TEXT NOT NULL,
  timezone TEXT NOT NULL, session_date TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
  close REAL NOT NULL, volume REAL, bar_hash TEXT NOT NULL, study_version TEXT NOT NULL,
  collector_version TEXT NOT NULL, provider_symbol TEXT, source TEXT NOT NULL, exchange TEXT, currency TEXT,
  identity_check TEXT NOT NULL, is_partial INTEGER NOT NULL CHECK (is_partial = 0), retrieved_at_utc TEXT NOT NULL,
  first_seen_at TEXT NOT NULL, first_seen_ns INTEGER NOT NULL, request_hash TEXT NOT NULL,
  response_hash TEXT NOT NULL, collection_run_id TEXT NOT NULL, collection_mode TEXT NOT NULL,
  data_phase TEXT NOT NULL, universe_role TEXT NOT NULL, PRIMARY KEY (symbol, interval, bar_start_ns));
CREATE TABLE IF NOT EXISTS partial_bars(symbol TEXT NOT NULL, interval TEXT NOT NULL, bar_start_ns INTEGER NOT NULL,
  bar_start TEXT NOT NULL, bar_end_ns INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL,
  bar_hash TEXT NOT NULL, observed_at TEXT NOT NULL, observed_ns INTEGER NOT NULL, request_hash TEXT NOT NULL,
  response_hash TEXT NOT NULL, run_id TEXT NOT NULL, identity_check TEXT NOT NULL,
  UNIQUE (symbol, interval, bar_start_ns, bar_hash));
CREATE TABLE IF NOT EXISTS bar_revision(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
  interval TEXT NOT NULL, bar_start_ns INTEGER NOT NULL, bar_start TEXT NOT NULL, original_hash TEXT NOT NULL,
  previous_hash TEXT NOT NULL, new_hash TEXT NOT NULL, observed_at TEXT NOT NULL, observed_ns INTEGER NOT NULL,
  changed_fields TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, volume REAL,
  request_hash TEXT NOT NULL, response_hash TEXT NOT NULL, run_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bar_finalization(symbol TEXT NOT NULL, interval TEXT NOT NULL,
  bar_start_ns INTEGER NOT NULL, partial_first_seen_at TEXT NOT NULL, partial_observations INTEGER NOT NULL,
  last_partial_hash TEXT NOT NULL, final_hash TEXT NOT NULL, finalized_first_seen_at TEXT NOT NULL,
  PRIMARY KEY (symbol, interval, bar_start_ns));
CREATE TABLE IF NOT EXISTS fetch_failures(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  symbol TEXT NOT NULL, interval TEXT NOT NULL, attempted_at TEXT NOT NULL, error_type TEXT NOT NULL,
  error_message TEXT NOT NULL, request_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eod_verifications(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  verified_at TEXT NOT NULL, ok INTEGER NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS probe_observations(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  probe_time TEXT NOT NULL, probe_ns INTEGER NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
  latest_bar_start TEXT, latest_bar_end TEXT, latest_is_partial INTEGER, latest_final_bar_start TEXT,
  latest_final_bar_end TEXT, latest_final_latency_seconds REAL, new_final_bars INTEGER NOT NULL,
  new_final_latency_median_seconds REAL, identity_check TEXT NOT NULL, response_hash TEXT NOT NULL);
"""


def _triggers() -> str:
    out = []
    for t in APPEND_ONLY:
        for op in ("UPDATE", "DELETE"):
            out.append(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                       f"BEGIN SELECT RAISE(ABORT, 'append-only: {t}'); END;")
    return "\n".join(out)


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    """Sağlayıcının tek yanıtı (aynı yanıtın kimlik meta bilgisiyle). `bars` index: tz-aware bar BAŞLANGIÇLARI."""

    symbol: str
    interval: str
    provider_symbol: str | None
    request: dict
    retrieved_at: datetime
    bars: pd.DataFrame
    currency: str | None
    exchange: str | None
    identity_check: str  # MATCH / UNVERIFIED / MISMATCH
    source: str = mm.SOURCE


@dataclass
class IngestCounts:
    new_bars: int = 0
    duplicate_bars: int = 0
    revisions: int = 0
    partial_observations: int = 0
    finalizations: int = 0
    invalid_rows: int = 0
    new_keys: list = field(default_factory=list)  # (bar_start_ns, bar_end_ns) yeni FIRST_SEEN barlar

    def add(self, o: "IngestCounts"):
        for k in ("new_bars", "duplicate_bars", "revisions", "partial_observations", "finalizations",
                  "invalid_rows"):
            setattr(self, k, getattr(self, k) + getattr(o, k))


# ------------------------------------------------------------------ saf yardımcılar
def utc_iso(ns: int) -> str:
    return pd.Timestamp(int(ns), tz="UTC").isoformat()


def ts_ns(t: datetime) -> int:
    return pd.Timestamp(t).tz_convert("UTC").value if pd.Timestamp(t).tzinfo else pd.Timestamp(t, tz="UTC").value


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                     allow_nan=False).encode()).hexdigest()


def _num(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def bar_values(row) -> tuple:
    return tuple(_num(row[k]) for k in ("Open", "High", "Low", "Close", "Volume"))


def bar_hash(vals: tuple) -> str:
    return sha(list(vals))


def response_hash(res: FetchResult) -> str:
    rows = [[int(ns), *bar_values(r)] for ns, (_, r) in zip(_starts_ns(res.bars), res.bars.iterrows())]
    return sha({"symbol": res.symbol, "provider_symbol": res.provider_symbol, "interval": res.interval,
                "currency": res.currency, "exchange": res.exchange, "identity_check": res.identity_check,
                "source": res.source, "bars": rows})


def request_hash(res: FetchResult, run_id: str) -> str:
    return sha({"run_id": run_id, "symbol": res.symbol, "interval": res.interval, "request": res.request,
                "retrieved_at": res.retrieved_at.astimezone(timezone.utc).isoformat()})


def _starts_ns(bars: pd.DataFrame) -> np.ndarray:
    idx = pd.DatetimeIndex(bars.index)
    if idx.tz is None:
        raise ArchiveError("bar zaman damgası saat dilimsiz (varsayılan TSİ/UTC yazılmaz)")
    return idx.tz_convert("UTC").as_unit("ns").asi8


def partial_flags(starts_ns: np.ndarray, interval: str, retrieved_at: datetime) -> np.ndarray:
    """Oluşmakta olan bar: bitişi alım anından sonra, ya da alım günün yerel 18:30'undan önce yapıldıysa ve bar o
    yerel seans gününün yanıttaki SON barıysa (gecikmeli sağlayıcıda son bar hâlâ dolabilir)."""
    if not len(starts_ns):
        return np.zeros(0, dtype=bool)
    r_ns = ts_ns(retrieved_at)
    out = starts_ns + INTERVAL_NS[interval] > r_ns
    local_r = retrieved_at.astimezone(ISTANBUL_TZ)
    last = int(np.argmax(starts_ns))
    last_day = pd.Timestamp(int(starts_ns[last]), tz="UTC").tz_convert(ISTANBUL_TZ).date()
    if last_day == local_r.date() and local_r.time() < mm.FINAL_AFTER_LOCAL:
        out[last] = True
    return out


# ------------------------------------------------------------------ arşiv
class Archive:
    """`role`: "primary" veya "preflight" — aynı kök iki rolde açılamaz (smoke verisi doğrulamaya karışmaz)."""

    def __init__(self, root: Path, role: str):
        if role not in ("primary", "preflight"):
            raise ArchiveError(f"bilinmeyen depo rolü: {role}")
        self.root, self.role = Path(root), role
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "archive.sqlite", isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA + _triggers())
        got = self.db.execute("SELECT value FROM meta WHERE key='role'").fetchone()
        if got is None:
            self.db.execute("INSERT INTO meta(key, value) VALUES ('role', ?)", (role,))
        elif got[0] != role:
            raise ArchiveError(f"depo rolü '{got[0]}', '{role}' olarak açılamaz")

    def close(self):
        self.db.close()

    # ---- çalıştırma kaydı
    def begin_run(self, mode: str, params: dict, now: datetime) -> str:
        started = now.astimezone(timezone.utc)
        run_id = f"{mode}-{started.strftime('%Y%m%dT%H%M%S%fZ')}-{sha(params)[:8]}"
        self.db.execute("INSERT INTO runs(run_id, mode, started_at, status) VALUES (?,?,?,?)",
                        (run_id, mode, started.isoformat(), "RUNNING"))
        return run_id

    def finish_run(self, run_id: str, summary: dict, now: datetime, status: str = "COMPLETED") -> dict:
        finished = now.astimezone(timezone.utc).isoformat()
        payload = {**summary, "run_id": run_id, "finished_at": finished, "status": status}
        self.db.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE run_id=?",
                        (finished, status, json.dumps(payload, sort_keys=True), run_id))
        mm.atomic_write_json(self.root / "runs" / f"{run_id}.json", payload)
        return payload

    # ---- ham yanıt (içerik adresli, atomik)
    def write_raw(self, res: FetchResult, rhash: str) -> str:
        rel = Path("raw") / rhash[:2] / f"{rhash}.json.gz"
        path = self.root / rel
        if path.exists():
            return rel.as_posix()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"symbol": res.symbol, "interval": res.interval, "provider_symbol": res.provider_symbol,
                "currency": res.currency, "exchange": res.exchange, "identity_check": res.identity_check,
                "source": res.source, "request": res.request,
                "bars": [[utc_iso(ns), *bar_values(r)] for ns, (_, r) in zip(_starts_ns(res.bars),
                                                                               res.bars.iterrows())]}
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(json.dumps(body, sort_keys=True))
        os.replace(tmp, path)
        return rel.as_posix()

    def log_failure(self, run_id: str, symbol: str, interval: str, request: dict, now: datetime,
                    error: BaseException | str) -> None:
        etype = type(error).__name__ if isinstance(error, BaseException) else "EMPTY_RESPONSE"
        at = now.astimezone(timezone.utc).isoformat()
        rh = sha({"run_id": run_id, "symbol": symbol, "interval": interval, "request": request, "at": at})
        self.db.execute("INSERT INTO fetch_failures(run_id, symbol, interval, attempted_at, error_type, "
                        "error_message, request_hash) VALUES (?,?,?,?,?,?,?)",
                        (run_id, symbol, interval, at, etype, str(error)[:2000], rh))

    # ---- alım
    def ingest(self, res: FetchResult, run_id: str, *, mode: str, universe_role: str,
               manifest: dict | None) -> IngestCounts:
        if res.interval not in INTERVAL_NS:
            raise ArchiveError(f"desteklenmeyen aralık: {res.interval}")
        if self.role == "preflight" and mode != "PREFLIGHT" or self.role == "primary" and mode == "PREFLIGHT":
            raise ArchiveError("preflight verisi yalnız preflight deposuna yazılır")
        bars = res.bars.sort_index()
        starts = _starts_ns(bars)
        partial = partial_flags(starts, res.interval, res.retrieved_at)
        rhash = response_hash(res)
        qhash = request_hash(res, run_id)
        raw_rel = self.write_raw(res, rhash)  # işlemden ÖNCE; yetim dosya zararsız
        seen = res.retrieved_at.astimezone(timezone.utc)
        seen_iso, seen_ns = seen.isoformat(), ts_ns(seen)
        step = INTERVAL_NS[res.interval]
        c = IngestCounts()
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (qhash, run_id, res.symbol, res.interval, res.provider_symbol,
                        json.dumps(res.request, sort_keys=True, default=str), seen_iso, rhash, len(bars),
                        res.currency, res.exchange, res.identity_check, res.source, raw_rel))
            for ns, is_partial, (_, row) in zip(starts, partial, bars.iterrows()):
                vals = bar_values(row)
                if any(v is None for v in vals[:4]):
                    c.invalid_rows += 1  # eksik OHLC: uydurma yok, yazılmaz
                    continue
                h = bar_hash(vals)
                ns = int(ns)
                key = (res.symbol, res.interval, ns)
                if is_partial:
                    cur = db.execute("INSERT OR IGNORE INTO partial_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (*key, utc_iso(ns), ns + step, *vals, h, seen_iso, seen_ns, qhash, rhash,
                                      run_id, res.identity_check))
                    c.partial_observations += cur.rowcount
                    continue
                existing = db.execute("SELECT bar_hash, open, high, low, close, volume FROM bars WHERE symbol=? "
                                      "AND interval=? AND bar_start_ns=?", key).fetchone()
                if existing is None:
                    local = pd.Timestamp(ns, tz="UTC").tz_convert(ISTANBUL_TZ)
                    db.execute("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                               "?)",
                               (*key, utc_iso(ns), ns + step, utc_iso(ns + step), local.isoformat(), mm.TIMEZONE,
                                str(local.date()), *vals, h, mm.STUDY_VERSION, mm.COLLECTOR_VERSION,
                                res.provider_symbol, res.source, res.exchange, res.currency, res.identity_check, 0,
                                seen_iso, seen_iso, seen_ns, qhash, rhash, run_id, mode,
                                mm.data_phase(local.date(), manifest, preflight=mode == "PREFLIGHT"), universe_role))
                    c.new_bars += 1
                    c.new_keys.append((ns, ns + step))
                    p = db.execute("SELECT MIN(observed_at), COUNT(*), (SELECT bar_hash FROM partial_bars WHERE "
                                   "symbol=? AND interval=? AND bar_start_ns=? ORDER BY observed_ns DESC LIMIT 1) "
                                   "FROM partial_bars WHERE symbol=? AND interval=? AND bar_start_ns=?",
                                   (*key, *key)).fetchone()
                    if p[1]:
                        db.execute("INSERT OR IGNORE INTO bar_finalization VALUES (?,?,?,?,?,?,?,?)",
                                   (*key, p[0], p[1], p[2], h, seen_iso))
                        c.finalizations += 1
                    continue
                last = db.execute("SELECT new_hash, open, high, low, close, volume FROM bar_revision WHERE symbol=? "
                                  "AND interval=? AND bar_start_ns=? ORDER BY id DESC LIMIT 1", key).fetchone()
                prev = last or existing
                if prev[0] == h:
                    c.duplicate_bars += 1
                    continue
                changed = [f for f, a, b in zip(FIELDS, prev[1:], vals) if a != b]
                db.execute("INSERT INTO bar_revision(symbol, interval, bar_start_ns, bar_start, original_hash, "
                           "previous_hash, new_hash, observed_at, observed_ns, changed_fields, open, high, low, close, "
                           "volume, request_hash, response_hash, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (*key, utc_iso(ns), existing[0], prev[0], h, seen_iso, seen_ns, json.dumps(changed),
                            *vals, qhash, rhash, run_id))
                c.revisions += 1
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return c

    def raw_hash_valid(self, raw_rel: str, expected: str) -> bool:
        """Ham dosyadan yanıt hash'ini yeniden hesaplar (dosya adı + içerik)."""
        path = self.root / raw_rel
        if not path.exists() or Path(raw_rel).name != f"{expected}.json.gz":
            return False
        with gzip.open(path, "rt", encoding="utf-8") as f:
            body = json.load(f)
        rows = [[pd.Timestamp(r[0]).value, *r[1:]] for r in body["bars"]]
        got = sha({**{k: body[k] for k in ("symbol", "provider_symbol", "interval", "currency", "exchange",
                                           "identity_check", "source")}, "bars": rows})
        return got == expected

    def record_probe(self, row: dict) -> None:
        cols = ("run_id", "probe_time", "probe_ns", "symbol", "interval", "latest_bar_start", "latest_bar_end",
                "latest_is_partial", "latest_final_bar_start", "latest_final_bar_end", "latest_final_latency_seconds",
                "new_final_bars", "new_final_latency_median_seconds", "identity_check", "response_hash")
        self.db.execute(f"INSERT INTO probe_observations({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        tuple(row.get(k) for k in cols))

    # ---- okuyucular (önyargısız)
    def bars_as_of(self, symbol: str, interval: str, t: datetime, with_revisions: bool = False) -> pd.DataFrame:
        """T anında bilinebilen tamamlanmış barlar: first_seen_at ≤ T ve bar_end ≤ T. Revizyonlar yalnız istenirse
        ve observed_at ≤ T ise uygulanır (sonradan gelen değer geçmişe sızmaz)."""
        t_ns = ts_ns(t)
        rows = self.db.execute("SELECT bar_start_ns, bar_end_ns, open, high, low, close, volume, first_seen_ns, "
                               "identity_check FROM bars WHERE symbol=? AND interval=? AND first_seen_ns<=? AND "
                               "bar_end_ns<=? ORDER BY bar_start_ns", (symbol, interval, t_ns, t_ns)).fetchall()
        df = pd.DataFrame(rows, columns=["bar_start_ns", "bar_end_ns", "open", "high", "low", "close", "volume",
                                         "first_seen_ns", "identity_check"])
        if with_revisions and len(df):
            rev = self.db.execute("SELECT bar_start_ns, open, high, low, close, volume FROM bar_revision WHERE "
                                  "symbol=? AND interval=? AND observed_ns<=? ORDER BY id",
                                  (symbol, interval, t_ns)).fetchall()
            pos = {int(s): i for i, s in enumerate(df["bar_start_ns"])}
            for s, *vals in rev:
                if s in pos:
                    df.loc[pos[s], ["open", "high", "low", "close", "volume"]] = vals
        return df

    def visibility(self, symbol: str | None = None, interval: str | None = None,
                   collection_mode: str | None = None) -> pd.DataFrame:
        """Bar başına görünürlük gecikmesi (s) = first_seen_at − bar_end."""
        q = ("SELECT symbol, interval, bar_start_ns, bar_end_ns, first_seen_ns, collection_mode, "
             "(first_seen_ns - bar_end_ns) / 1e9 AS visibility_latency_seconds FROM bars WHERE 1=1")
        args = []
        for col, v in (("symbol", symbol), ("interval", interval), ("collection_mode", collection_mode)):
            if v is not None:
                q += f" AND {col}=?"
                args.append(v)
        return pd.read_sql_query(q, self.db, params=args)

    def validation_rows(self, manifest: dict, interval: str = "5m") -> pd.DataFrame:
        """İleriye dönük birincil analize girebilecek barlar: FINAL manifest, PROSPECTIVE, gün ≥ başlangıç,
        birincil evren, kimlik MATCH, tüketilmiş final tarihi değil. (Bu bir sonuç üretmez.)"""
        c = manifest["config"]
        if c["manifest_status"] != mm.FINAL or not c["prospective_start_session"]:
            return pd.DataFrame()
        q = ("SELECT * FROM bars WHERE interval=? AND data_phase='PROSPECTIVE' AND universe_role IN "
             "('PRIMARY','BENCHMARK') AND identity_check='MATCH' AND session_date>=? ORDER BY symbol, bar_start_ns")
        df = pd.read_sql_query(q, self.db, params=(interval, c["prospective_start_session"]))
        if len(df):
            keep = df["symbol"].isin(set(c["universe"]) | {c["benchmark"]})
            keep &= ~df["session_date"].map(lambda d: mm.in_consumed_final(date.fromisoformat(d)))
            df = df[keep]
        return df
