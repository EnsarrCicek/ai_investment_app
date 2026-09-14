"""HATA 12N2A — research persistence katmanı için TEK, paylaşılan kanonik
JSON-bayt/SHA-256 içerik-hash ilkeli (primitive).

`evidence_serialization.py`'nin `_canonical_json()`/`_sha256_of()` çiftiyle
AYNI desen (`json.dumps(sort_keys=True, separators=(",", ":"))` + UTF-8 +
`hashlib.sha256`) — ama o modülün private (alt çizgili) yardımcılarına
dışarıdan bağımlılık kurmak yerine, evaluation_id/attempt_id kimlik
hash'leri VE attempt-result içerik-hash'i gibi research persistence
metadata'sının TÜMÜ için TEK, paylaşılan, halka açık bir ilkel olarak
buraya çıkarılmıştır (HATA 12N2A section 16/17: "Do not duplicate
canonical hashing logic across repositories").

Kasıtlı olarak `default=str` gibi bir dönüştürme YAPILMAZ -- desteklenmeyen
bir tip (ör. çıplak `datetime`/`Enum` nesnesi) verilirse `json.dumps` kendi
`TypeError`'ını fırlatır; bu SESSİZCE bir string'e "onarılmaz" -- çağıran
taraf tüm alanları ÖNCEDEN JSON-güvenli ilkellere (str/int/float/bool/None/
iç içe dict/list) çevirmekle yükümlüdür.
"""

from __future__ import annotations

import hashlib
import json


def canonical_document_bytes(payload: dict) -> bytes:
    """`payload`'ın (yalnızca JSON-güvenli ilkellerden oluşan bir dict)
    kanonik, dict ekleme sırasından bağımsız UTF-8 bayt temsili."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_document_bytes(payload)).hexdigest()
