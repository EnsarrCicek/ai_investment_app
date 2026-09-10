"""HATA 12N1 — değişmez, içerik-adresli evidence nesne deposu testleri.

Kapsam: `app/research/evidence_models.py` (kind/isim/hata modelleri) ve
`app/research/evidence_object_store.py` (`FakeEvidenceObjectStore`,
`GCSEvidenceObjectStore`). GCS tarafı TAMAMEN MOCK'lanır -- bu dosyadaki
HİÇBİR test gerçek ağ/`gcloud auth`/ADC/bucket/Firestore erişimi
GEREKTİRMEZ; modülü import etmek serbesttir, gerçek buluta dokunmak
DEĞİLDİR.
"""

import hashlib
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import PreconditionFailed

from app.research.evidence_models import (
    EvidenceIntegrityError,
    EvidenceObjectKind,
    EvidenceObjectRef,
    ObjectStoreError,
    ProvenanceConflictError,
    object_name_for,
    validate_sha256_hex,
)
from app.research.evidence_object_store import FakeEvidenceObjectStore, GCSEvidenceObjectStore


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Nesne adı / kind / SHA doğrulama (HATA 12N1 section 7/8/23)
# ---------------------------------------------------------------------------


def test_object_name_is_deterministic_type_separated_hash_addressed():
    digest = "a" * 64
    asset_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    assert asset_name == f"technical-v1/evidence/asset/sha256/{digest}.json"


def test_object_name_same_hash_different_kind_produces_different_paths():
    digest = "b" * 64
    asset_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    benchmark_name = object_name_for(EvidenceObjectKind.BENCHMARK_SNAPSHOT, digest)
    output_name = object_name_for(EvidenceObjectKind.TECHNICAL_OUTPUT, digest)
    assert len({asset_name, benchmark_name, output_name}) == 3


def test_object_name_contains_no_symbol_user_or_timestamp_fields():
    digest = "c" * 64
    name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    # Nesne kimligi SADECE tur+hash'ten gelir -- rastgele bir sembol/tarih
    # stringi (ornegin "AKBNK"/"2026-09-10") yolun HICBIR yerinde olamaz.
    assert "AKBNK" not in name
    assert "2026" not in name


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,  # buyuk harf -- reddedilir (kanonik kucuk-harf hex)
        "g" * 64,  # hex olmayan karakter
        "a" * 63 + "!",
        None,
        123,
    ],
)
def test_object_name_rejects_malformed_sha256(malformed):
    with pytest.raises(EvidenceIntegrityError):
        object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, malformed)


@pytest.mark.parametrize(
    "malformed",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None],
)
def test_validate_sha256_hex_rejects_malformed(malformed):
    with pytest.raises(EvidenceIntegrityError):
        validate_sha256_hex(malformed)


def test_validate_sha256_hex_accepts_canonical_form():
    validate_sha256_hex("a" * 64)  # raise etmemeli


# ---------------------------------------------------------------------------
# FakeEvidenceObjectStore -- HATA 12N1 section 12'nin A-F semantikleri
# ---------------------------------------------------------------------------


def test_fake_store_absent_object_with_valid_hash_creates():
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)

    ref = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)

    assert isinstance(ref, EvidenceObjectRef)
    assert ref.kind == EvidenceObjectKind.ASSET_SNAPSHOT
    assert ref.sha256 == digest
    assert ref.size_bytes == len(raw)
    assert ref.object_name == object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)


def test_fake_store_same_identity_same_bytes_is_idempotent():
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)

    ref1 = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)
    ref2 = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)  # ikinci kez -- idempotent

    assert ref1 == ref2


def test_fake_store_same_identity_different_bytes_is_provenance_conflict():
    """`_verify_local_hash()` her cagrida `sha256(raw_bytes) == expected_
    sha256` sartini zaten dayattigindan, GERCEKTEN farkli icerikli iki
    cagri hicbir zaman AYNI expected_sha256'yi ORGANIK olarak paylasamaz
    (bu, gercek bir SHA-256 çakışması gerektirirdi -- hesaplanamaz).
    Bu yuzden bu path'i (depoda ONCEDEN VAR olan icerigin, YENI gelen ve
    KENDI ICINDE tutarli bir kayitla CELISMESI) gerceklestirmenin tek
    dogru yolu, bir depolama-katmani corruption/wiring-bug senaryosunu
    DOGRUDAN simule etmektir -- `test_fake_store_get_verified_detects_
    internal_content_corruption` ile AYNI desen."""
    store = FakeEvidenceObjectStore()
    raw_a = b'{"a":1}'
    digest_a = _sha256_hex(raw_a)
    store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest_a, raw_a)

    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest_a)
    store._objects[object_name] = b'{"a":999}'  # digest_a ile ARTIK tutarsiz (corruption simulasyonu)

    with pytest.raises(ProvenanceConflictError):
        store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest_a, raw_a)


def test_fake_store_expected_hash_mismatch_fails_before_create():
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    wrong_digest = _sha256_hex(b"not the same bytes")

    with pytest.raises(EvidenceIntegrityError):
        store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, wrong_digest, raw)

    # Hicbir sey yazilmamis olmali -- object store hala bostur.
    real_digest = _sha256_hex(raw)
    with pytest.raises(ObjectStoreError):
        store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, real_digest)


def test_fake_store_get_verified_returns_stored_matching_bytes():
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)

    result = store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    assert result == raw


def test_fake_store_get_verified_detects_internal_content_corruption():
    """F senaryosu: depolanan baytlar, istenen hash ile TUTARSIZ hale
    gelmis (ornegin depolama katmanindaki bir bug) -- `get_verified()`
    nesne ADINA GUVENMEZ, HER ZAMAN yeniden hash'ler."""
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)

    # Depoyu dogrudan (API'nin ASLA izin vermeyecegi bir sekilde) bozuyoruz --
    # gercek bir depolama-katmani corruption'ini simule etmek icin.
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    store._objects[object_name] = b'{"a":999}'  # digest ile artik TUTARSIZ

    with pytest.raises(ProvenanceConflictError):
        store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)


def test_fake_store_get_verified_missing_object_raises_object_store_error():
    store = FakeEvidenceObjectStore()
    digest = "d" * 64
    with pytest.raises(ObjectStoreError):
        store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)


def test_fake_store_different_kinds_do_not_collide_even_with_same_bytes():
    store = FakeEvidenceObjectStore()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)

    ref_asset = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)
    ref_output = store.put_immutable(EvidenceObjectKind.TECHNICAL_OUTPUT, digest, raw)

    assert ref_asset.object_name != ref_output.object_name
    assert store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest) == raw
    assert store.get_verified(EvidenceObjectKind.TECHNICAL_OUTPUT, digest) == raw


# ---------------------------------------------------------------------------
# GCSEvidenceObjectStore -- tamamen mock'lanmis client (gercek GCS YOK)
# ---------------------------------------------------------------------------


def _make_mock_bucket():
    """Her `bucket.blob(name)` cagrisi icin AYRI bir MagicMock dondurur,
    ama AYNI `name` icin AYNI mock'u -- boylece test, `upload_from_string`/
    `download_as_bytes` cagrilarini dogru blob uzerinden izleyebilir."""
    blobs: dict[str, MagicMock] = {}

    def _blob(name):
        if name not in blobs:
            blobs[name] = MagicMock(name=f"blob:{name}")
        return blobs[name]

    bucket = MagicMock()
    bucket.blob.side_effect = _blob
    bucket._blobs = blobs  # test'lerin dogrudan erisimi icin
    return bucket


def _make_store_with_mock_bucket():
    bucket = _make_mock_bucket()
    client = MagicMock()
    client.bucket.return_value = bucket
    store = GCSEvidenceObjectStore(bucket_name="fake-bucket-not-real", client=client)
    return store, bucket


def test_gcs_store_does_not_touch_network_at_construction():
    # client=None birakilsa bile constructor'in kendisi network'e GITMEMELI
    # (yalnizca ilk gercek metod cagrisinda tembel kurulum yapilir).
    store = GCSEvidenceObjectStore(bucket_name="fake-bucket-not-real")
    assert store is not None  # yalnizca olusturulabildigini kanitlar, hicbir agi cagrisi yapilmadi


def test_gcs_store_upload_uses_if_generation_match_zero():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)

    store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)

    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    blob = bucket._blobs[object_name]
    blob.upload_from_string.assert_called_once()
    _, kwargs = blob.upload_from_string.call_args
    assert kwargs.get("if_generation_match") == 0


def test_gcs_store_successful_create_returns_ref():
    store, _bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)

    ref = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)

    assert ref.sha256 == digest
    assert ref.size_bytes == len(raw)
    assert ref.bucket_name == "fake-bucket-not-real"


def test_gcs_store_precondition_failed_with_matching_bytes_is_idempotent():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)

    blob = bucket.blob(object_name)
    blob.upload_from_string.side_effect = PreconditionFailed("already exists")
    blob.download_as_bytes.return_value = raw  # AYNI icerik zaten orada

    ref = store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)
    assert ref.sha256 == digest  # idempotent basari, hata YOK


def test_gcs_store_precondition_failed_with_mismatching_bytes_is_conflict():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)

    blob = bucket.blob(object_name)
    blob.upload_from_string.side_effect = PreconditionFailed("already exists")
    blob.download_as_bytes.return_value = b'{"a":999}'  # FARKLI icerik zaten orada

    with pytest.raises(ProvenanceConflictError):
        store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)


def test_gcs_store_transport_exception_does_not_become_idempotent_success():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)

    blob = bucket.blob(object_name)
    blob.upload_from_string.side_effect = ConnectionError("network blip")

    with pytest.raises(ObjectStoreError):
        store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, digest, raw)


def test_gcs_store_wrong_expected_hash_fails_before_upload_call():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    wrong_digest = _sha256_hex(b"different bytes entirely")

    with pytest.raises(EvidenceIntegrityError):
        store.put_immutable(EvidenceObjectKind.ASSET_SNAPSHOT, wrong_digest, raw)

    # upload_from_string HICBIR blob uzerinde cagrilmamis olmali.
    for blob in bucket._blobs.values():
        blob.upload_from_string.assert_not_called()


def test_gcs_store_get_verified_validates_sha256():
    store, bucket = _make_store_with_mock_bucket()
    raw = b'{"a":1}'
    digest = _sha256_hex(raw)
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    bucket.blob(object_name).download_as_bytes.return_value = raw

    result = store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    assert result == raw


def test_gcs_store_get_verified_mismatch_raises_provenance_conflict():
    store, bucket = _make_store_with_mock_bucket()
    digest = _sha256_hex(b'{"a":1}')
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    bucket.blob(object_name).download_as_bytes.return_value = b'{"a":999}'  # istenenle TUTARSIZ

    with pytest.raises(ProvenanceConflictError):
        store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)


def test_gcs_store_get_verified_transport_exception_raises_object_store_error():
    store, bucket = _make_store_with_mock_bucket()
    digest = "e" * 64
    object_name = object_name_for(EvidenceObjectKind.ASSET_SNAPSHOT, digest)
    bucket.blob(object_name).download_as_bytes.side_effect = ConnectionError("network blip")

    with pytest.raises(ObjectStoreError):
        store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, digest)


def test_gcs_store_never_calls_generic_update_or_set_methods():
    """HATA 12N1 section 10: bu soyutlama genel amacli bir overwrite/
    update API'si SUNMAZ -- `GCSEvidenceObjectStore`'un herkese acik
    metotlari yalnizca `put_immutable`/`get_verified`'dir."""
    public_methods = {name for name in dir(GCSEvidenceObjectStore) if not name.startswith("_")}
    assert public_methods == {"put_immutable", "get_verified"}


def test_fake_store_never_calls_generic_update_or_set_methods():
    public_methods = {name for name in dir(FakeEvidenceObjectStore) if not name.startswith("_")}
    assert public_methods == {"put_immutable", "get_verified"}
