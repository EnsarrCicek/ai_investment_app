"""HATA 12N1 — Technical V1 immutable evidence nesnesi kimlik/hata modelleri.

Bu modül yalnızca SAF veri yapıları (Enum/dataclass) ve istisna sınıflarını
içerir — HİÇBİR I/O yapmaz (ağ isteği, dosya sistemi, GCS/Firestore erişimi
YOK). `evidence_object_store.py`'nin hem gerçek (GCS) hem sahte (in-memory)
implementasyonları bu modeller üzerinden konuşur.

Kapsam KASITLI OLARAK dardır (HATA 12N1, section 6/25/26): yalnızca üç
evidence nesnesi türü (asset/benchmark/technical-output anlık-görüntüleri).
attempt/session/outcome ile ilgili HİÇBİR model burada YOKTUR — bunlar N2/N3
ve sonraki, ayrı ticket'ların kapsamıdır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceIntegrityError(ValueError):
    """Çağıranın verdiği (kind, expected_sha256, raw_bytes) üçlüsü kendi
    içinde TUTARSIZ -- ör. verilen `raw_bytes`'ın GERÇEK SHA-256'sı, iddia
    edilen `expected_sha256` ile eşleşmiyor, ya da `expected_sha256` kanonik
    (64 küçük-harf hex karakter) formatında değil. HİÇBİR depolama çağrısı
    YAPILMADAN, tamamen yerel olarak fırlatılır (HATA 12N1 section 9)."""


class ProvenanceConflictError(ValueError):
    """Aynı içerik-adresli kimlikte (aynı kind+hash) ÖNCEDEN VAR olan bir
    nesnenin, YENİ sağlanan bayt dizisinden FARKLI bir GERÇEK SHA-256
    taşıdığı KANITLANDI -- bu bir yazılım hatasının/yanlış wiring'in
    kanıtıdır (kriptografik SHA-256 çakışması pratikte OLANAKSIZDIR).
    ASLA sessizce üzerine yazılmaz/en-son-kazanır uygulanmaz -- sert hata."""


class ObjectStoreError(RuntimeError):
    """Altta yatan depolama transport/servis hatası (ağ, yetkilendirme,
    geçici GCS arızası vb.) -- `EvidenceIntegrityError`/
    `ProvenanceConflictError`'dan KASITLI OLARAK AYRI bir kategori: biri
    çağıranın YANLIŞ veri verdiğini, diğeri depolanan içerikle GERÇEK bir
    çelişki olduğunu, bu ise depolama katmanının KENDİSİNİN (geçici veya
    kalıcı) başarısız olduğunu gösterir -- üçü de FARKLI kurtarma/retry
    semantikleri gerektirir, bu yüzden ASLA aynı istisna sınıfına
    indirgenmez. Bir transport hatası ASLA idempotent başarı sayılmaz."""


class EvidenceObjectKind(str, Enum):
    """Kapalı (closed) küme -- HATA 12N1 kapsamı YALNIZCA bu üç türle
    sınırlıdır."""

    ASSET_SNAPSHOT = "ASSET_SNAPSHOT"
    BENCHMARK_SNAPSHOT = "BENCHMARK_SNAPSHOT"
    TECHNICAL_OUTPUT = "TECHNICAL_OUTPUT"


_KIND_PATH_SEGMENT: dict[EvidenceObjectKind, str] = {
    EvidenceObjectKind.ASSET_SNAPSHOT: "asset",
    EvidenceObjectKind.BENCHMARK_SNAPSHOT: "benchmark",
    EvidenceObjectKind.TECHNICAL_OUTPUT: "output",
}


def validate_sha256_hex(expected_sha256: str) -> None:
    """Tam olarak 64 küçük-harf hex karakter mi -- fail-fast, ASLA
    coerce/normalize etmez (ör. büyük harf otomatik küçültülmez)."""
    if not isinstance(expected_sha256, str) or not _SHA256_HEX_RE.match(expected_sha256):
        raise EvidenceIntegrityError(
            f"Beklenen SHA-256 tam olarak 64 küçük-harf hex karakter değil: {expected_sha256!r}"
        )


def object_name_for(kind: EvidenceObjectKind, expected_sha256: str) -> str:
    """HATA 12N1 section 7/8: deterministik, tür-ayrılmış, versiyonlu,
    hash-adresli nesne yolu. Sembol/kullanıcı/zaman damgası/portfolio
    bilgisi ASLA içermez -- kimlik SADECE içerikten (hash) ve türden
    gelir. Çağıran taraf hiçbir zaman keyfi bir GCS yolu VEREMEZ -- yol
    her zaman burada, dahili olarak üretilir."""
    validate_sha256_hex(expected_sha256)
    segment = _KIND_PATH_SEGMENT[kind]
    return f"technical-v1/evidence/{segment}/sha256/{expected_sha256}.json"


@dataclass(frozen=True)
class EvidenceObjectRef:
    """HATA 12N1 section 11: minimal, değişmez (immutable) nesne-referans
    şeması. Signed URL/credential/token/geçici erişim URL'si ASLA İÇERMEZ
    -- bu SALT bir kimlik+boyut kaydıdır, Firestore evaluation şeması
    DEĞİLDİR (o, ayrı ve sonraki bir ticket'ın kapsamıdır)."""

    kind: EvidenceObjectKind
    sha256: str
    object_name: str
    size_bytes: int
    bucket_name: str | None = None
