"""İleriye dönük (prospective) momentum çalışması manifesti — veri görülmeden ÖNCE dondurulur (YALNIZ araştırma).

* Evren: Round 2 `REFERENCE_ASSETS` ∪ `UNTOUCHED_ASSETS` (sıralı, tekil). KTLEV yalnız `descriptive_only_symbols`.
* Etiket: MOMENTUM_EVENT_LABEL_V2 FINAL manifestinin TAM 64 karakterlik SHA-256'sı.
* Durum DRAFT iken `prospective_start_session` boştur; START kararı ayrı komutla verilir (`start_study`). START
  sonrası manifest değiştirilemez; evren/tanım değişikliği yeni `study_version` ister.
* Kanonik JSON (sıralı anahtar, sabit ayraç, NaN yok) → SHA-256; yazım geçici dosya → `os.replace` (atomik).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.momentum_final import candidate as cd
from app.research.momentum_label_v2 import experiment as lx
from app.research.momentum_label_v2 import labels as lv
from app.research.momentum_round2 import dataset as ds2

HERE = Path(__file__).parent
MANIFEST_PATH = HERE / "momentum_prospective_manifest.json"
STUDY_VERSION = "MOMENTUM_PROSPECTIVE_V1"
COLLECTOR_VERSION = "momentum-collector-1.0.0"
SOURCE = "yahoo_finance"
TIMEZONE = "Europe/Istanbul"
BENCHMARK = "XU100"
INTERVALS = ("5m", "1m")
DESCRIPTIVE_ONLY_SYMBOLS = ("KTLEV",)
MIN_FULL_SESSIONS = 20
MIN_SESSIONS_PER_PRIMARY_ASSET = 18  # her birincil varlıkta ayrı ayrı (evrenden çıkarma yok)
TARGET_SESSIONS = 25
ASSET_SESSION_COVERAGE = 0.90  # minimum asset-session = ⌈0.90 × evren × 20⌉
PROBE_SUBSET_SIZE = 10
PROBE_1M_SUBSET_SIZE = 4
PROBE_CADENCE_SECONDS = 300
FINAL_AFTER_LOCAL = time(18, 30)  # yerel bu saatten sonra alınan yanıtta o günün son barı da tamamlanmış sayılır
START_CUTOFF_LOCAL = time(9, 40)  # açılış seansı başlangıcı: bu saatten önce FINAL olursa aynı gün başlangıç olabilir
CONSUMED_FINAL_RANGE = (date(2026, 9, 28), date(2026, 10, 15))  # tüketilmiş final tarihleri: asla doğrulama verisi
DRAFT, FINAL = "DRAFT", "FINAL"


class StudyManifestError(RuntimeError):
    pass


def primary_universe() -> list[str]:
    u = sorted(set(ds2.REFERENCE_ASSETS) | set(ds2.UNTOUCHED_ASSETS))
    assert not set(u) & set(DESCRIPTIVE_ONLY_SYMBOLS) and BENCHMARK not in u
    return u


def universe_sha256(universe: list[str]) -> str:
    return cd.sha256_of(sorted(universe))


def probe_subset(universe: list[str], k: int = PROBE_SUBSET_SIZE) -> list[str]:
    """Deterministik, sonuçtan bağımsız alt küme: SHA-256(study_version|sembol) sırası."""
    key = lambda s: hashlib.sha256(f"{STUDY_VERSION}|{s}".encode()).hexdigest()  # noqa: E731
    return sorted(sorted(universe, key=key)[:k])


def verified_label_sha() -> str:
    """Label V2 FINAL manifesti: dosya SHA'sı = kodun kanonik hash'i, 64 hex, FINAL. Aksi halde hata."""
    m = lx.load_manifest()
    sha = cd.sha256_of(lv.MANIFEST_CONFIG)
    if m["sha256"] != sha or m["config"].get("manifest_status") != FINAL:
        raise StudyManifestError("Label V2 manifesti FINAL değil ya da kodla uyuşmuyor")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise StudyManifestError("Label SHA-256 64 hex karakter değil")
    return sha


def build_draft(created_at: datetime) -> dict:
    u = primary_universe()
    probe = probe_subset(u)
    n_min_asset_sessions = math.ceil(round(ASSET_SESSION_COVERAGE * len(u) * MIN_FULL_SESSIONS, 6))
    return {
        "study_version": STUDY_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "manifest_status": DRAFT,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "frozen_at": None,
        "prospective_start_session": None,
        "label_version": lv.LABEL_VERSION,
        "label_manifest_sha256": verified_label_sha(),
        "label_alert_unit": lv.FIRST_ALERT,
        "universe": u,
        "universe_count": len(u),
        "universe_sha256": universe_sha256(u),
        "universe_source": "momentum_round2.dataset REFERENCE_ASSETS ∪ UNTOUCHED_ASSETS (sorted, unique)",
        "descriptive_only_symbols": list(DESCRIPTIVE_ONLY_SYMBOLS),
        "benchmark": BENCHMARK,
        "intervals": list(INTERVALS),
        "source": SOURCE,
        "source_note": "existing Yahoo intraday access via research collector adapter; not a production "
                       "recommendation",
        "timezone": TIMEZONE,
        "consumed_final_days_excluded": [str(d) for d in CONSUMED_FINAL_RANGE],
        "collection_policy": {
            "eod_archive": "after 18:30 Europe/Istanbul on each weekday: universe + benchmark + descriptive-only "
                           "symbols, intervals 5m (period 5d) and 1m (period 5d); append only missing finalized bars",
            "storage": "local SQLite archive (append-only tables enforced by triggers) + content-addressed raw "
                       "responses; never Firestore",
            "failure_policy": "failed/empty fetch -> logged in fetch_failures, no bars written; no forward fill, "
                              "no fabricated zero-volume bars; missing data stays MISSING",
            "pacing_seconds_between_requests": 0.5,
        },
        "visibility_probe_policy": {
            "subset_5m": probe,
            "subset_1m": probe[:PROBE_1M_SUBSET_SIZE],
            "subset_rule": "first k symbols by sha256(study_version|symbol), then sorted; benchmark always included",
            "cadence_seconds": PROBE_CADENCE_SECONDS,
            "window_local": "weekdays 09:55-18:30 Europe/Istanbul",
            "request": "period 1d per symbol and interval; provider retry helper only; exponential backoff on "
                       "consecutive failures (max 1800 s)",
            "latency_definition": "first_seen_at - bar_end for each finalized bar first seen by a probe run",
        },
        "minimum_full_sessions": MIN_FULL_SESSIONS,
        "target_sessions": TARGET_SESSIONS,
        "minimum_asset_sessions": n_min_asset_sessions,
        "minimum_sessions_per_primary_asset": MIN_SESSIONS_PER_PRIMARY_ASSET,
        "coverage_policy": "DATASET READY requires ALL of: full prospective sessions >= minimum_full_sessions; valid "
                           "primary asset-sessions >= minimum_asset_sessions; EVERY primary-universe asset has >= "
                           "minimum_sessions_per_primary_asset valid sessions. Missing data is never filled; an asset "
                           "below the minimum keeps the study incomplete; assets are never removed from the universe",
        "full_session_definition": "weekday on/after prospective_start_session whose benchmark finalized 5m bars "
                                   "start <= 10:05 and end with a bar starting >= 17:50 (observed bars, no assumed "
                                   "close); shorter observed sessions are SHORT_SESSION and do not count",
        "asset_session_definition": "primary-universe asset in a full session with finalized 5m bars >= 80% of the "
                                    "benchmark's bar count and identity_check == MATCH",
        "start_policy": "prospective_start_session = first weekday whose opening auction (09:40 local) starts "
                        "strictly after frozen_at; if no bars are observed on that date (holiday) the first later "
                        "date with observed bars is the effective start (recorded, not chosen). Data stored before "
                        "it is WARMUP_ONLY / PRE_START; preflight data lives in a separate store and is never "
                        "validation data",
        "end_policy": "DATASET READY FOR PROSPECTIVE AUDIT once coverage_policy is met; collection continues to target_sessions; no early stopping on results; the "
                      "collector computes no outcomes, models or PASS/FAIL",
        "revision_policy": "first-seen finalized bar is immutable (unique symbol, interval, bar_start); later "
                           "differing provider values go to bar_revision with original_hash, previous_hash, "
                           "new_hash, observed_at, changed_fields; evaluators use first-seen values unless they "
                           "explicitly request revisions observed <= evaluation time",
        "partial_bar_policy": "a bar is partial if bar_end > retrieved_at, or if it is the last bar of the response "
                              "for the current local session date and retrieved before 18:30 local; partial "
                              "observations go only to partial_bars (append-only); the finalized bar is stored once "
                              "in bars and linked in bar_finalization; partial data never feeds labels/features",
        "identity_policy": "provider symbol/exchange/currency from the same response metadata vs expected "
                           "<SYMBOL>.IS/IST/TRY; MATCH only when all reported and equal; missing -> UNVERIFIED; "
                           "conflict -> MISMATCH (stored, never in primary analysis); no defaults are written",
        "no_lookahead_policy": "every bar carries first_seen_at (UTC); an evaluator at time T may only read bars "
                               "with first_seen_at <= T and bar_end <= T, and revisions with observed_at <= T",
    }


def manifest_sha(config: dict) -> str:
    return cd.sha256_of(config)


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path: Path = MANIFEST_PATH) -> dict:
    if not path.exists():
        raise StudyManifestError("prospective manifest yok")
    m = json.loads(path.read_text(encoding="utf-8"))
    if manifest_sha(m["config"]) != m.get("sha256"):
        raise StudyManifestError("prospective manifest bozulmuş (SHA uyuşmuyor)")
    c = m["config"]
    if c["universe_sha256"] != universe_sha256(c["universe"]) or c["universe_count"] != len(c["universe"]):
        raise StudyManifestError("evren hash'i uyuşmuyor")
    return m


def write_draft(path: Path = MANIFEST_PATH, now: datetime | None = None, regenerate: bool = False) -> dict:
    """Taslak yoksa yazar; varsa olduğu gibi döner — taslak sessizce yeniden üretilmez. `regenerate=True` yalnız
    DRAFT'ı (START öncesi) açıkça yeniden üretir; FINAL asla değiştirilmez."""
    if path.exists():
        existing = load(path)
        if not regenerate:
            return existing
        if existing["config"]["manifest_status"] != DRAFT:
            raise StudyManifestError("çalışma başlatıldı; manifest yeniden üretilemez (yeni study_version gerekir)")
    config = build_draft(now or datetime.now(timezone.utc))
    m = {"config": config, "sha256": manifest_sha(config)}
    atomic_write_json(path, m)
    return m


def next_session_after(frozen_at: datetime) -> date:
    local = frozen_at.astimezone(ISTANBUL_TZ)
    d = local.date() if local.time() < START_CUTOFF_LOCAL else local.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def start_study(path: Path = MANIFEST_PATH, now: datetime | None = None) -> dict:
    """START kararı: DRAFT → FINAL (tek sefer). Bu görevde ÇAĞRILMAZ."""
    m = load(path)
    c = dict(m["config"])
    if c["manifest_status"] == FINAL:
        raise StudyManifestError("çalışma zaten başlatıldı; manifest değiştirilemez (yeni study_version gerekir)")
    if c["label_manifest_sha256"] != verified_label_sha():
        raise StudyManifestError("Label SHA taslaktan sonra değişmiş")
    if c["universe"] != primary_universe():
        raise StudyManifestError("evren taslaktan sonra değişmiş")
    now = now or datetime.now(timezone.utc)
    c.update({"manifest_status": FINAL, "frozen_at": now.astimezone(timezone.utc).isoformat(),
              "prospective_start_session": str(next_session_after(now))})
    new = {"config": c, "sha256": manifest_sha(c), "draft_sha256": m["sha256"]}
    atomic_write_json(path, new)
    return new


def start_date(m: dict) -> date | None:
    s = m["config"]["prospective_start_session"]
    return date.fromisoformat(s) if s else None


def data_phase(bar_day: date, m: dict | None, preflight: bool = False) -> str:
    """PREFLIGHT (ayrı depo) / PRE_START (çalışma başlamadı) / WARMUP_ONLY (< başlangıç) / PROSPECTIVE."""
    if preflight:
        return "PREFLIGHT"
    start = start_date(m) if m is not None and m["config"]["manifest_status"] == FINAL else None
    if start is None:
        return "PRE_START"
    return "PROSPECTIVE" if bar_day >= start else "WARMUP_ONLY"


def in_consumed_final(day: date) -> bool:
    return CONSUMED_FINAL_RANGE[0] <= day <= CONSUMED_FINAL_RANGE[1]
