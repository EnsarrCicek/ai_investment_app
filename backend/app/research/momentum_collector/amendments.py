"""Çalışma kodu anlık görüntüsü için EKLEMELİ kusur düzeltme kayıtları (amendment). Asıl anlık görüntü
(`study_code_snapshot.json`) DEĞİŞMEZ ve yeniden üretilmez.

* Kayıtlar `store/snapshots/amendments/` altında (Git dışı, anlık görüntü kapsamı dışı); bir kez yazılır, aynı kimlikle
  farklı içerik → hata. Her kayıt öncekinin SHA'sına bağlanır (zincir).
* `verify_chain`: anlık görüntüden farklı (değişmiş/eklenmiş) HER dosyanın güncel SHA'sı, onu kapsayan en son kaydın
  `new_file_sha256`'sına eşitse zincir geçerlidir. Kaydı olmayan herhangi bir fark → geçersiz.
* `original_snapshot_matches` ham eşleşmeyi DÜRÜSTÇE raporlar (değişiklik varsa false).

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_collector.amendments status
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_collector.amendments validate   (salt okunur)
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_collector.amendments record     (kaydı yazar)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.research.momentum_collector import manifest as mm
from app.research.momentum_collector import snapshot as sn
from app.research.momentum_collector import storage as st

AMEND_DIR = st.STORE / "snapshots" / "amendments"
PREFIX = "backend/app/research/momentum_collector/"

# Tek tanımlı düzeltme: EOD ↔ Probe doğrulama yarışı
AMENDMENT_ID = "AMD-001-EOD-PROBE-VALIDATION-RACE"
REASON = "EOD_PROBE_VALIDATION_RACE"
AFFECTED_FILES = (PREFIX + "ops.py", PREFIX + "amendments.py")
EXPLANATION = ("Integrity validator changed to use a consistent read boundary; prospective collection/data "
               "semantics unchanged. EOD post-run check now opens an SQLite read snapshot first and takes its "
               "wall-clock boundary afterwards (plus a visible rowid high-watermark), so rows committed later by "
               "the independently locked Probe are not misread as future first_seen; genuinely impossible future "
               "first_seen rows inside the snapshot still fail. Health reports original_snapshot_matches and "
               "approved_amendment_chain_valid separately. New file amendments.py holds this record logic.")


# İkinci düzeltme: EOD kurtarma çalıştırması ↔ hedef seans kimliği
AMD002_ID = "AMD-002-EOD-RECOVERY-SESSION-IDENTITY"
AMD002 = {"amendment_id": AMD002_ID, "reason": "EOD_RECOVERY_SESSION_IDENTITY",
          "affected_files": (PREFIX + "ops.py", PREFIX + "amendments.py"),
          "flags": {"semantic_change": False, "data_collection_change": False, "data_rewrite": False,
                    "bar_value_change": False, "first_seen_change": False, "schedule_change": False,
                    "idempotency_fix": True},
          "explanation": ("Completion check now keys successful EOD state to the target market session rather than "
                          "execution calendar date. A verified, failure-free EOD started before FINAL_AFTER_LOCAL "
                          "(18:30 Europe/Istanbul) on day D (e.g. a morning recovery run finalizing D-1) no longer "
                          "marks session D as completed, so the evening EOD for D is not skipped; a run started at or "
                          "after 18:30 on D still makes later EOD triggers for D SKIPPED_ALREADY_COMPLETED. Bars, "
                          "first_seen, raw hashes, revisions, partial-bar rules, FULL/SHORT definition, universe, "
                          "coverage thresholds, Probe cadence and EOD schedule are unchanged. amendments.py gains "
                          "the generic record builder for this amendment.")}


class AmendmentError(RuntimeError):
    pass


def build_record(snap: dict, created_at: str, previous_sha256: str | None, spec: dict | None = None,
                 base_hashes: dict | None = None) -> dict:
    """`spec` yoksa AMD-001 (geriye uyumlu). `base_hashes`: zincirde önceki kayıtların bıraktığı dosya SHA'ları
    (yoksa asıl anlık görüntü) — her dosyanın old_file_sha256'sı buradan alınır."""
    old = snap["snapshot"]["tracked_file_hashes"]
    base = dict(old) if base_hashes is None else base_hashes
    now = sn.file_hashes()
    files = []
    for f in (spec["affected_files"] if spec else AFFECTED_FILES):
        if f not in now:
            raise AmendmentError(f"etkilenen dosya yok: {f}")
        files.append({"path": f, "change_type": "MODIFIED" if f in base else "ADDED",
                      "old_file_sha256": base.get(f), "new_file_sha256": now[f]})
    flags = spec["flags"] if spec else {"semantic_change": False, "data_collection_change": False,
                                        "data_rewrite": False, "first_seen_change": False, "schedule_change": False}
    record = {"amendment_id": spec["amendment_id"] if spec else AMENDMENT_ID, "timestamp": created_at,
              "reason": spec["reason"] if spec else REASON, "affected_files": files,
              "old_snapshot_sha256": snap["snapshot_sha256"],
              "prospective_manifest_sha256": snap["snapshot"]["study_manifest_sha256"],
              "previous_amendment_sha256": previous_sha256, **flags,
              "explanation": spec["explanation"] if spec else EXPLANATION}
    return {"record": record, "record_sha256": sn.cd.sha256_of(record)}


def chain_file_hashes(snap: dict, chain: list[dict]) -> dict:
    """Asıl anlık görüntü + zincirdeki kayıtların sırayla uyguladığı yeni dosya SHA'ları."""
    out = dict(snap["snapshot"]["tracked_file_hashes"])
    for d in chain:
        for f in d["record"]["affected_files"]:
            out[f["path"]] = f["new_file_sha256"]
    return out


def _check(doc: dict) -> dict:
    if sn.cd.sha256_of(doc["record"]) != doc.get("record_sha256"):
        raise AmendmentError("değişiklik kaydı bozulmuş (SHA uyuşmuyor)")
    return doc


def write_record(doc: dict, directory: Path = AMEND_DIR) -> dict:
    """Bir kez yazılır; aynı kimlikte farklı içerik reddedilir (ekleme-yalnız)."""
    doc = {"record": doc["record"], "record_sha256": sn.cd.sha256_of(doc["record"])}
    path = Path(directory) / f"{doc['record']['amendment_id']}.json"
    if path.exists():
        got = _check(json.loads(path.read_text(encoding="utf-8")))
        if got["record_sha256"] != doc["record_sha256"]:
            raise AmendmentError("değişiklik kaydı zaten var ve farklı; yeni kimlikle yeni kayıt gerekir")
        return got
    path.parent.mkdir(parents=True, exist_ok=True)
    mm.atomic_write_json(path, doc)
    return doc


def load_chain(directory: Path = AMEND_DIR) -> list[dict]:
    docs = [_check(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(Path(directory).glob("*.json"))] \
        if Path(directory).exists() else []
    prev = None
    for d in docs:
        if d["record"]["previous_amendment_sha256"] != prev:
            raise AmendmentError(f"zincir kopuk: {d['record']['amendment_id']}")
        prev = d["record_sha256"]
    return docs


def verify_chain(snap: dict, directory: Path = AMEND_DIR) -> dict:
    old = snap["snapshot"]["tracked_file_hashes"]
    now = sn.file_hashes()
    diffs = sorted({f for f in old if now.get(f) != old[f]} | (set(now) - set(old)))
    try:
        chain = load_chain(directory)
    except AmendmentError as e:
        return {"original_snapshot_matches": not diffs, "approved_amendment_chain_valid": False,
                "amendments": [], "unapproved_changes": diffs, "error": str(e)}
    latest: dict[str, str] = {}
    expected_old: dict[str, str | None] = dict(old)
    ok_links = True
    for d in chain:
        r = d["record"]
        if r["old_snapshot_sha256"] != snap["snapshot_sha256"]:
            ok_links = False
        for f in r["affected_files"]:
            if f["old_file_sha256"] != expected_old.get(f["path"]):
                ok_links = False
            latest[f["path"]] = f["new_file_sha256"]
            expected_old[f["path"]] = f["new_file_sha256"]
    unapproved = [f for f in diffs if latest.get(f) != now.get(f)]
    return {"original_snapshot_matches": not diffs, "approved_amendment_chain_valid": ok_links and not unapproved,
            "amendments": [d["record"]["amendment_id"] for d in chain], "unapproved_changes": unapproved,
            "changed_or_added_files": diffs}


def readonly_archive(root: Path = st.PRIMARY_ROOT) -> st.Archive:
    """Şema/rol yazımı yapmayan salt okunur arşiv görünümü (`mode=ro`)."""
    a = object.__new__(st.Archive)
    a.root, a.role = Path(root), "primary"
    a.db = sqlite3.connect(f"file:{(Path(root) / 'archive.sqlite').as_posix()}?mode=ro", uri=True,
                           isolation_level=None)
    return a


def validate_readonly(root: Path = st.PRIMARY_ROOT) -> dict:
    """Son EOD çalıştırması için tutarlı-sınır bütünlük denetimi; HİÇBİR yazım yapmaz."""
    from app.research.momentum_collector import ops
    a = readonly_archive(root)
    try:
        row = a.db.execute("SELECT run_id FROM runs WHERE mode='EOD' ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            return {"status": "NO_EOD_RUN"}
        return {"run_id": row[0], **ops.consistent_integrity_check(a, mm.load(), row[0], sn.load())}
    finally:
        a.db.close()


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    snap = sn.load()
    if cmd == "record-amd002":
        chain = load_chain()
        done = [d for d in chain if d["record"]["amendment_id"] == AMD002_ID]
        if done:
            print(json.dumps(done[0], ensure_ascii=False, indent=1))
            return 0
        if [d["record"]["amendment_id"] for d in chain] != [AMENDMENT_ID]:
            raise AmendmentError("AMD-002 yalnız AMD-001'den sonra kaydedilir")
        doc = write_record(build_record(snap, datetime.now(timezone.utc).isoformat(), chain[-1]["record_sha256"],
                                        AMD002, chain_file_hashes(snap, chain)))
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    elif cmd == "record":
        chain = load_chain()
        prev = chain[-1]["record_sha256"] if chain else None
        if any(d["record"]["amendment_id"] == AMENDMENT_ID for d in chain):
            existing = next(d for d in chain if d["record"]["amendment_id"] == AMENDMENT_ID)
            prev = existing["record"]["previous_amendment_sha256"]
            doc = write_record(build_record(snap, existing["record"]["timestamp"], prev))
        else:
            doc = write_record(build_record(snap, datetime.now(timezone.utc).isoformat(), prev))
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    elif cmd == "validate":
        print(json.dumps(validate_readonly(), ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps(verify_chain(snap), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
