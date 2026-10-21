"""Çalışma kodu anlık görüntüsü — ilk ileriye dönük bar yazılmadan önce kullanılan araştırma kodunun dosya hash'leri.

Çalışma anlamını DEĞİŞTİRMEZ; yalnız denetim kaydıdır. Bir kez yazılır (üzerine yazılamaz). Zamanlanmış çalıştırmalar
manifest/etiket/evren SHA'larını bu kayda karşı denetler (`anchors_ok`).
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.research.momentum_collector import manifest as mm
from app.research.momentum_final import candidate as cd

SNAPSHOT_PATH = mm.HERE / "study_code_snapshot.json"
BACKEND = mm.HERE.parents[2]
REPO = BACKEND.parent
RESEARCH = mm.HERE.parent
EXCLUDE_PARTS = {"__pycache__", "runs", "store"}
EXTRA_FILES = ("scripts/momentum_collect.py", "scripts/install_momentum_collection_tasks.ps1",
               "app/research/momentum_round2/dataset.py", "app/research/momentum_feasibility/audit.py",
               "tests/test_momentum_label_v2.py", "tests/test_momentum_collector.py", "tests/test_momentum_ops.py",
               "tests/test_momentum_final.py", "tests/test_momentum_postmortem.py")


class SnapshotError(RuntimeError):
    pass


def snapshot_files() -> list[Path]:
    out = []
    for pkg in (RESEARCH / "momentum_label_v2", RESEARCH / "momentum_collector"):
        for p in sorted(pkg.rglob("*")):
            if p.is_file() and not EXCLUDE_PARTS & set(p.relative_to(pkg).parts) and p != SNAPSHOT_PATH \
                    and p.suffix not in (".pyc", ".tmp"):
                out.append(p)
    out += [BACKEND / f for f in EXTRA_FILES if (BACKEND / f).exists()]
    return out


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def file_hashes() -> dict[str, str]:
    return {p.relative_to(REPO).as_posix(): file_sha256(p) for p in snapshot_files()}


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


def build(now: datetime) -> dict:
    m = mm.load()
    c = m["config"]
    if c["manifest_status"] != mm.FINAL:
        raise SnapshotError("çalışma başlatılmadan anlık görüntü yok")
    porcelain = _git("status", "--porcelain", "--", "backend").splitlines()
    hashes = file_hashes()
    git_state = {}
    changed = {line[3:].strip().strip('"'): line[:2] for line in porcelain}
    for f in hashes:
        st = next((v for k, v in changed.items() if f == k or (k.endswith("/") and f.startswith(k))), None)
        git_state[f] = "clean" if st is None else ("untracked" if st == "??" else "modified")
    return {"study_manifest_sha256": m["sha256"], "label_manifest_sha256": c["label_manifest_sha256"],
            "universe_sha256": c["universe_sha256"], "prospective_start_session": c["prospective_start_session"],
            "git_head": _git("rev-parse", "HEAD").strip(), "working_tree_dirty": bool(porcelain),
            "tracked_file_hashes": hashes, "file_git_state": git_state,
            "snapshot_created_at": now.astimezone(timezone.utc).isoformat(),
            "note": "file hashes are of working-tree bytes; study semantics unchanged"}


def write_once(path: Path = SNAPSHOT_PATH, now: datetime | None = None) -> dict:
    if path.exists():
        return load(path)
    snap = build(now or datetime.now(timezone.utc))
    out = {"snapshot": snap, "snapshot_sha256": cd.sha256_of(snap)}
    mm.atomic_write_json(path, out)
    return out


def load(path: Path = SNAPSHOT_PATH) -> dict:
    if not path.exists():
        raise SnapshotError("çalışma kodu anlık görüntüsü yok")
    import json
    s = json.loads(path.read_text(encoding="utf-8"))
    if cd.sha256_of(s["snapshot"]) != s.get("snapshot_sha256"):
        raise SnapshotError("anlık görüntü bozulmuş (SHA uyuşmuyor)")
    return s


def anchors(m: dict, snap: dict) -> dict:
    """Manifest/etiket/evren SHA'ları anlık görüntüyle VE kodla aynı mı (kayma tespiti)."""
    s = snap["snapshot"]
    c = m["config"]
    checks = {"manifest_sha_unchanged": m["sha256"] == s["study_manifest_sha256"] == mm.manifest_sha(c),
              "label_sha_unchanged": c["label_manifest_sha256"] == s["label_manifest_sha256"]
              == _safe(mm.verified_label_sha),
              "universe_sha_unchanged": c["universe_sha256"] == s["universe_sha256"]
              == mm.universe_sha256(mm.primary_universe())}
    return {"ok": all(checks.values()), **checks}


def code_matches(snap: dict) -> dict:
    now = file_hashes()
    old = snap["snapshot"]["tracked_file_hashes"]
    changed = sorted(f for f in old if now.get(f) != old[f])
    added = sorted(set(now) - set(old))
    return {"code_matches_snapshot": not changed and not added, "changed_files": changed, "added_files": added}


def _safe(fn):
    try:
        return fn()
    except Exception:  # bozuk etiket manifesti = kayma
        return None
