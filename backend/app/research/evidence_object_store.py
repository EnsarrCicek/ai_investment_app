"""HATA 12N1 — değişmez (immutable), içerik-adresli evidence nesne deposu
soyutlaması + bellek-içi (fake) implementasyon + GCS adaptörü.

Üç implementasyonun (Protocol, Fake, GCS) TAMAMI AYNI davranış sözleşmesini
sağlamalıdır:
  - create-only: nesne yoksa oluşturulur.
  - AYNI (kind, sha256) + AYNI bayt dizisi -> idempotent başarı (yeniden
    kullanım, hata DEĞİL).
  - AYNI (kind, sha256) + FARKLI bayt dizisi -> `ProvenanceConflictError`
    (sert hata, ASLA üzerine yazma).
  - `expected_sha256`, sağlanan `raw_bytes`'ın GERÇEK SHA-256'sı ile
    eşleşmiyorsa -> `EvidenceIntegrityError`, HİÇBİR depolama çağrısı
    YAPILMADAN (yerel, en başta).
  - `get_verified()` her zaman indirilen HAM baytları yeniden hash'ler ve
    istenen hash ile karşılaştırır -- nesne ADININ kendisi ASLA tek
    başına güvenilir kabul edilmez (bkz. HATA 12Q section 13-16).

Bu modül genel amaçlı bir overwrite/update API'si SUNMAZ -- yalnızca
`put_immutable`/`get_verified`.

Bu modülün import edilmesi HİÇBİR ağ isteği/kimlik doğrulama
GEREKTİRMEZ -- `GCSEvidenceObjectStore`, gerçek `google.cloud.storage`
client'ını yalnızca (ve yalnızca) ilk gerçek kullanımda, tembel
(lazy) biçimde kurar; modül seviyesinde hiçbir client örneği
OLUŞTURULMAZ (HATA 12N1 section 13/19).
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from app.research.evidence_models import (
    EvidenceIntegrityError,
    EvidenceObjectKind,
    EvidenceObjectRef,
    ObjectStoreError,
    ProvenanceConflictError,
    object_name_for,
    validate_sha256_hex,
)


def _verify_local_hash(kind: EvidenceObjectKind, expected_sha256: str, raw_bytes: bytes) -> str:
    """HİÇBİR depolama çağrısı yapmadan ÖNCE, çağıranın verdiği baytların
    GERÇEKTEN iddia edilen hash'e sahip olduğunu doğrular (HATA 12N1
    section 9 -- "pre-upload local hash check"). Object name'i de
    üretip döner (kind+hash'ten dahili üretim -- çağıran ASLA keyfi bir
    yol VEREMEZ)."""
    validate_sha256_hex(expected_sha256)
    actual = hashlib.sha256(raw_bytes).hexdigest()
    if actual != expected_sha256:
        raise EvidenceIntegrityError(
            f"Sağlanan baytların gerçek SHA-256'sı ({actual}) beklenen ({expected_sha256}) ile "
            f"eşleşmiyor (kind={kind.value}) -- depolamaya HİÇ gidilmedi."
        )
    return object_name_for(kind, expected_sha256)


@runtime_checkable
class EvidenceObjectStore(Protocol):
    """HATA 12N1 section 10 soyutlaması. `put_immutable`/`get_verified`
    DIŞINDA hiçbir genel overwrite/update metodu YOKTUR."""

    def put_immutable(
        self, kind: EvidenceObjectKind, expected_sha256: str, raw_bytes: bytes
    ) -> EvidenceObjectRef: ...

    def get_verified(self, kind: EvidenceObjectKind, expected_sha256: str) -> bytes: ...


class FakeEvidenceObjectStore:
    """Testler için bellek-içi implementasyon -- ağ/gerçek bulut erişimi
    YOK. Üretim (GCS) davranışıyla BİREBİR aynı semantiği sağlar (HATA
    12N1 section 12) -- fake'in GCS'ten daha PERMİSİF olması YASAK."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}  # object_name -> raw_bytes

    def put_immutable(
        self, kind: EvidenceObjectKind, expected_sha256: str, raw_bytes: bytes
    ) -> EvidenceObjectRef:
        object_name = _verify_local_hash(kind, expected_sha256, raw_bytes)
        existing = self._objects.get(object_name)
        if existing is None:
            self._objects[object_name] = raw_bytes
        elif existing != raw_bytes:
            raise ProvenanceConflictError(
                f"Nesne zaten var ama içerik UYUŞMUYOR (kind={kind.value}, "
                f"object_name={object_name}) -- ÜZERİNE YAZILMADI."
            )
        # existing == raw_bytes: aynı içerik -- idempotent reuse, hiçbir şey değişmez.
        return EvidenceObjectRef(
            kind=kind, sha256=expected_sha256, object_name=object_name, size_bytes=len(raw_bytes)
        )

    def get_verified(self, kind: EvidenceObjectKind, expected_sha256: str) -> bytes:
        validate_sha256_hex(expected_sha256)
        object_name = object_name_for(kind, expected_sha256)
        raw_bytes = self._objects.get(object_name)
        if raw_bytes is None:
            raise ObjectStoreError(f"Nesne bulunamadı: {object_name}")
        actual = hashlib.sha256(raw_bytes).hexdigest()
        if actual != expected_sha256:
            raise ProvenanceConflictError(
                f"Depolanan nesnenin GERÇEK SHA-256'sı ({actual}) istenen ({expected_sha256}) ile "
                f"eşleşmiyor (object_name={object_name})."
            )
        return raw_bytes


class GCSEvidenceObjectStore:
    """Google Cloud Storage tabanlı implementasyon.

    HATA 12N1 section 13: `bucket_name` constructor'a AÇIKÇA verilir --
    var OLMAYAN bir production bucket'ı hard-code EDİLMEZ. Modül import
    ANINDA hiçbir GCS client'ı oluşturulmaz/kullanılmaz -- `client`
    parametresi verilmezse gerçek `google.cloud.storage.Client()`
    yalnızca bu sınıfın bir metodunun GERÇEKTEN çağrıldığı anda, tembel
    biçimde kurulur. Testler `client` parametresine bir sahte/mock nesne
    vererek GERÇEK ağ erişimi OLMADAN bu sınıfı egzersiz eder.
    """

    def __init__(self, bucket_name: str, client=None) -> None:
        self._bucket_name = bucket_name
        self._client = client

    def _get_bucket(self):
        if self._client is None:
            from google.cloud import storage  # gecikmeli import -- test-zamanında ZORUNLU DEĞİL

            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def put_immutable(
        self, kind: EvidenceObjectKind, expected_sha256: str, raw_bytes: bytes
    ) -> EvidenceObjectRef:
        object_name = _verify_local_hash(kind, expected_sha256, raw_bytes)
        bucket = self._get_bucket()

        from google.api_core.exceptions import PreconditionFailed

        try:
            bucket.blob(object_name).upload_from_string(
                raw_bytes, content_type="application/json", if_generation_match=0
            )
        except PreconditionFailed:
            # HATA 12Q/12N1: nesne ADI TEK BAŞINA ASLA güvenilmez -- var
            # olan nesnenin HAM baytları indirilip yeniden hash'lenir.
            # GCS'in kendi MD5/CRC32C'si KULLANILMAZ (Technical V1'in
            # kanonik kimliği DEĞİLDİR).
            existing_bytes = bucket.blob(object_name).download_as_bytes()
            existing_actual = hashlib.sha256(existing_bytes).hexdigest()
            if existing_actual != expected_sha256 or existing_bytes != raw_bytes:
                raise ProvenanceConflictError(
                    f"GCS nesnesi zaten var ama içerik UYUŞMUYOR (kind={kind.value}, "
                    f"object_name={object_name}, bucket={self._bucket_name}) -- ÜZERİNE YAZILMADI."
                ) from None
            # existing_bytes == raw_bytes: aynı içerik -- idempotent reuse.
        except Exception as exc:  # ağ/transport/servis hatası -- ASLA idempotent BAŞARI sayılmaz
            raise ObjectStoreError(
                f"GCS yükleme başarısız (kind={kind.value}, object_name={object_name}): {exc}"
            ) from exc

        return EvidenceObjectRef(
            kind=kind,
            sha256=expected_sha256,
            object_name=object_name,
            size_bytes=len(raw_bytes),
            bucket_name=self._bucket_name,
        )

    def get_verified(self, kind: EvidenceObjectKind, expected_sha256: str) -> bytes:
        validate_sha256_hex(expected_sha256)
        object_name = object_name_for(kind, expected_sha256)
        bucket = self._get_bucket()
        try:
            raw_bytes = bucket.blob(object_name).download_as_bytes()
        except Exception as exc:
            raise ObjectStoreError(f"GCS indirme başarısız (object_name={object_name}): {exc}") from exc

        actual = hashlib.sha256(raw_bytes).hexdigest()
        if actual != expected_sha256:
            raise ProvenanceConflictError(
                f"GCS'ten indirilen nesnenin GERÇEK SHA-256'sı ({actual}) istenen ({expected_sha256}) "
                f"ile eşleşmiyor (object_name={object_name})."
            )
        return raw_bytes
