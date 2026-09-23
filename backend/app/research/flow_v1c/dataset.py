"""FLOW 1C dış evren veri seti — FLOW 1B dondurma/doğrulama altyapısını
aynen kullanır; yalnızca evren ve dosya yolları farklıdır.

Ham veri YEREL kalır (git/docker-ignored); manifest + hash'ler commit'lenir.
Freeze (AĞ): `python -m app.research.flow_v1c.dataset --freeze`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.research.canonical_hash import content_sha256
from app.research.flow_v1.dataset import freeze_symbols, load_verified_dataset

FLOW_V1C_DIR = Path(__file__).resolve().parent
DATA_DIR = FLOW_V1C_DIR / "data"
FROZEN_DATA_FILE = DATA_DIR / "frozen_ohlcv.json.gz"
DATASET_MANIFEST_FILE = DATA_DIR / "dataset_manifest.json"
PROTOCOL_FILE = FLOW_V1C_DIR.parent / "resources" / "flow_v1c_protocol_v1.json"


def load_protocol() -> tuple[dict, str]:
    protocol = json.loads(PROTOCOL_FILE.read_text(encoding="utf-8"))
    return protocol, content_sha256(protocol)


def load_external_dataset():
    """AĞ YOK. Yerel ham veri yoksa FrozenDatasetMissingError (sessiz yeniden
    çekim yok); her sembolün hash'i doğrulanır."""
    return load_verified_dataset(data_file=FROZEN_DATA_FILE, manifest_file=DATASET_MANIFEST_FILE)


def main() -> None:
    if "--freeze" not in sys.argv:
        print("Kullanım: python -m app.research.flow_v1c.dataset --freeze  (AĞ KULLANIR, bir kez)")
        return
    if FROZEN_DATA_FILE.exists():
        print(f"{FROZEN_DATA_FILE} zaten var — üzerine yazılmaz.")
        return
    if DATASET_MANIFEST_FILE.exists() and "--new-snapshot" not in sys.argv:
        print("Commit'li manifest mevcut; yeni snapshot için --new-snapshot gerekir.")
        return
    from app.research.flow_v1c.universe import load_external_universe

    symbols, artifact = load_external_universe()
    manifest = freeze_symbols(
        symbols,
        data_file=FROZEN_DATA_FILE,
        manifest_file=DATASET_MANIFEST_FILE,
        dataset_id="FLOW_V1C_EXTERNAL_FROZEN_OHLCV",
        extra_manifest={
            "universe_artifact": "app/research/resources/flow_v1c_universe.json",
            "external_symbols_sha256": artifact["external_symbols_sha256"],
            "universe_source_pdf_sha256": artifact["source_pdf_sha256"],
        },
    )
    failed = [s for s, e in manifest["symbols"].items() if e["status"] != "OK"]
    print(json.dumps({"dataset_sha256": manifest["dataset_sha256"], "end": manifest["latest_expected_completed_date"],
                      "ok": len(manifest["symbols"]) - len(failed), "failed": failed}))


if __name__ == "__main__":
    main()
