"""İleriye dönük momentum toplayıcısı CLI (YALNIZ araştırma; Firestore/üretim YOK).

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py manifest [--regenerate]  # DRAFT manifest
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py verify       # etiket/manifest/arşiv denetimi
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py preflight    # 2 varlık + XU100, ayrı depo
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py start --confirm   # START kararı (DRAFT → FINAL)
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py eod          # gün sonu arşivi (tek sefer, kilitli)
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py probe        # TEK sonda turu (zamanlayıcı)
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py probe --loop # yalnız elle/hata ayıklama
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py status
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py health       # yalnız toplama sağlığı
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py snapshot     # kod anlık görüntüsü (bir kez)
    .venv\\Scripts\\python.exe -X utf8 scripts\\momentum_collect.py ping         # komut satırı/çalışma dizini sınaması

`eod`/`probe` birincil depoya yalnız manifest FINAL iken ve yerel tarih ≥ prospective_start_session iken yazar.
Çıkış kodları: 0 tamam/atlandı, 1 hata, 2 bütünlük/kayma, 3 EOD'de bazı semboller başarısız (yeniden denenir).
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines.technical.session_timing import ISTANBUL_TZ  # noqa: E402
from app.research.momentum_collector import collector as col  # noqa: E402
from app.research.momentum_collector import integrity as ig  # noqa: E402
from app.research.momentum_collector import manifest as mm  # noqa: E402
from app.research.momentum_collector import ops  # noqa: E402
from app.research.momentum_collector import snapshot as sn  # noqa: E402
from app.research.momentum_collector import storage as st  # noqa: E402
from app.research.momentum_collector import visibility_probe as vp  # noqa: E402


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _final_manifest() -> dict:
    m = mm.load()
    if m["config"]["manifest_status"] != mm.FINAL:
        raise SystemExit("manifest DRAFT: birincil toplama START kararından önce çalışmaz")
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["manifest", "verify", "preflight", "start", "eod", "probe", "status", "health",
                                        "snapshot", "ping"])
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--regenerate", action="store_true")  # yalnız DRAFT
    args = ap.parse_args(argv)
    if args.command == "manifest":
        m = mm.write_draft(regenerate=args.regenerate)
        _print({"status": m["config"]["manifest_status"], "sha256": m["sha256"],
                "universe_count": m["config"]["universe_count"], "universe_sha256": m["config"]["universe_sha256"],
                "label_manifest_sha256": m["config"]["label_manifest_sha256"],
                "coverage": {k: m["config"][k] for k in ("minimum_full_sessions", "target_sessions",
                                                         "minimum_asset_sessions",
                                                         "minimum_sessions_per_primary_asset")}})
    elif args.command == "verify":
        m = mm.load()
        out = {"label": ig.verify_label(), "study_manifest": ig.verify_study_manifest(m)}
        for role, root in (("primary", st.PRIMARY_ROOT), ("preflight", st.PREFLIGHT_ROOT)):
            if (root / "archive.sqlite").exists():
                a = st.Archive(root, role)
                out[f"archive_{role}"] = ig.verify_archive(a, m if role == "primary" else None)
                a.close()
        _print(out)
        return 0 if all(v.get("ok", True) for v in out.values() if isinstance(v, dict)) else ops.EXIT_INTEGRITY
    elif args.command == "preflight":
        a = st.Archive(st.PREFLIGHT_ROOT, "preflight")
        _print(col.run_preflight(a, col.YahooCollectorSource()))
        _print(ig.verify_archive(a))
        a.close()
    elif args.command == "start":
        if not args.confirm:
            raise SystemExit("START geri alınamaz: --confirm gerekir")
        m = mm.start_study()
        _print({"status": m["config"]["manifest_status"], "frozen_at": m["config"]["frozen_at"],
                "prospective_start_session": m["config"]["prospective_start_session"], "sha256": m["sha256"]})
    elif args.command in ("eod", "probe") and not args.loop:
        code, rec = ops.scheduled_run(args.command)
        _print(rec)
        return code
    elif args.command == "probe":  # --loop: elle/hata ayıklama; başlangıç sınırı yine geçerli
        m = _final_manifest()
        if datetime.now(ISTANBUL_TZ).date() < date.fromisoformat(m["config"]["prospective_start_session"]):
            raise SystemExit("prospective_start_session öncesi birincil sonda çalışmaz")
        a = st.Archive(st.PRIMARY_ROOT, "primary")
        _print({"probe_runs": vp.probe_loop(a, col.YahooCollectorSource(), m)})
        a.close()
    elif args.command == "status":
        m = mm.load()
        if not (st.PRIMARY_ROOT / "archive.sqlite").exists():
            _print({"status": "NO PRIMARY ARCHIVE", "manifest_status": m["config"]["manifest_status"]})
            return 0
        a = st.Archive(st.PRIMARY_ROOT, "primary")
        _print(ig.dataset_status(a, m))
        a.close()
    elif args.command == "health":
        h = ops.health()
        ops.log_line(ops.LOG_DIR, "scheduler_health.log", {"timestamp": datetime.now(timezone.utc).isoformat(), **h})
        _print(h)
        return ops.EXIT_INTEGRITY if h["archive_integrity"] is False or h["anchors_ok"] is False else 0
    elif args.command == "snapshot":
        s = sn.write_once()
        _print({"snapshot_sha256": s["snapshot_sha256"], **{k: v for k, v in s["snapshot"].items()
                                                             if k not in ("tracked_file_hashes", "file_git_state")},
                "files": len(s["snapshot"]["tracked_file_hashes"])})
    elif args.command == "ping":
        _print({"ok": True, "cwd": os.getcwd(), "python": sys.executable})
    return 0


if __name__ == "__main__":
    sys.exit(main())
