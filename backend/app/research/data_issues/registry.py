"""Araştırma veri-sorunu kaydı ve girdi uygunluk kontrolü (yerel; üretime bağlı DEĞİL).

Kayıt dosya kimliğine (SHA-256) bağlıdır:
  * Girdi dosyasının hash'i kayıtlı bir sorunla eşleşirse   -> BLOCKED (sorun durumu ile).
  * Sorun kaydı olan sembolün dosyası FARKLI hash'liyse      -> BLOCKED (REVIEW_REQUIRED);
    hash değişikliği kendiliğinden "düzeldi/doğrulandı" sayılmaz. Açık bir `reviews`
    kaydı (symbol, sha256, status="REVIEWED_NO_KNOWN_ISSUE") gerekir.
  * Diğer dosyalar -> engellenmez; bu, verinin doğru olduğunu KANITLAMAZ.
Sabit yüzde eşiğiyle "hatalı düşüş" filtresi UYGULANMAZ.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("known_issues.json")
NO_MATCH_LIMIT = ("Kayıtlı bilinen sorunla eşleşme yok; bu yalnızca incelenmiş sorunların bulunmadığını gösterir, "
                  "verinin doğru olduğunu KANITLAMAZ.")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_input_files(files: dict[str, Path], registry: dict | None = None) -> dict:
    """files: {symbol: csv_path}. Saf okuma; dosyaları değiştirmez."""
    registry = registry if registry is not None else load_registry()
    by_hash = {i["file"]["sha256"]: i for i in registry["issues"]}
    issue_symbols = {i["symbol"] for i in registry["issues"]}
    reviewed = {(r["symbol"], r["sha256"]) for r in registry.get("reviews", [])
                if r.get("status") == "REVIEWED_NO_KNOWN_ISSUE"}
    blocked = []
    for symbol, path in sorted(files.items()):
        digest = sha256_file(path)
        issue = by_hash.get(digest)
        if issue is not None:
            blocked.append({"symbol": symbol, "file": str(path), "sha256": digest, "issue_id": issue["issue_id"],
                            "reason": issue["status"]})
        elif symbol in issue_symbols and (symbol, digest) not in reviewed:
            blocked.append({"symbol": symbol, "file": str(path), "sha256": digest, "issue_id": None,
                            "reason": "REVIEW_REQUIRED: sembolde doğrulanmış sorun kaydı var; bu dosya kimliği incelenmedi"})
    return {"status": "BLOCKED" if blocked else "NO_KNOWN_ISSUE_MATCH", "blocked": blocked,
            "checked_files": len(files), "limit": NO_MATCH_LIMIT}
