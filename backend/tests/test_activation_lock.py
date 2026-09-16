"""HATA 12N3C2-B2-A — `app/research/activation_lock.py` saf model ve kimlik
doğrulama testleri (Firestore/GCS/ortam/dosya-sistemi erişimi olmadan)."""

import pytest

from app.research.activation_lock import (
    TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION,
    TechnicalV1ActivationLock,
    compute_activation_lock_id,
    compute_runtime_fingerprint,
)
from app.research.canonical_hash import content_sha256

PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
METHODOLOGY_FINGERPRINT = "a" * 64
PROJECT_ID = "ai-investment-app-2026"
RUNTIME_SERVICE = "backend-api"
RUNTIME_REVISION = "backend-api-00042-xyz"
GIT_SHA = "730ef262f350b97b9290adddbd7c6a38c024729b"


def _base_kwargs():
    activation_lock_id = compute_activation_lock_id(
        protocol_version=PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=METHODOLOGY_FINGERPRINT,
        authorized_project_id=PROJECT_ID,
        authorized_runtime_service=RUNTIME_SERVICE,
        authorized_runtime_revision=RUNTIME_REVISION,
    )
    return dict(
        activation_lock_schema_version=TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION,
        activation_lock_id=activation_lock_id,
        protocol_version=PROTOCOL_VERSION,
        protocol_sha256="b" * 64,
        freeze_manifest_sha256="c" * 64,
        methodology_git_commit=GIT_SHA,
        authorized_methodology_source_fingerprint=METHODOLOGY_FINGERPRINT,
        authorized_project_id=PROJECT_ID,
        authorized_runtime_service=RUNTIME_SERVICE,
        authorized_runtime_revision=RUNTIME_REVISION,
        methodology_approval_reference=GIT_SHA,
    )


def _lock(**overrides) -> TechnicalV1ActivationLock:
    kwargs = {**_base_kwargs(), **overrides}
    return TechnicalV1ActivationLock(**kwargs)


# ---------------------------------------------------------------------------
# Happy path / construction
# ---------------------------------------------------------------------------


def test_accepts_valid_inputs():
    lock = _lock()
    assert lock.protocol_version == PROTOCOL_VERSION
    assert lock.activation_lock_id == _base_kwargs()["activation_lock_id"]


def test_is_frozen():
    lock = _lock()
    with pytest.raises(Exception):
        lock.protocol_version = "OTHER"  # type: ignore[misc]


def test_record_content_sha256_is_derived_not_settable():
    lock = _lock()
    assert not any(f.name == "record_content_sha256" for f in lock.__dataclass_fields__.values())
    assert isinstance(lock.record_content_sha256, str)
    assert len(lock.record_content_sha256) == 64


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_rejects_wrong_schema_version():
    with pytest.raises(ValueError):
        _lock(activation_lock_schema_version="technical_v1_activation_lock_v2")


def test_rejects_empty_schema_version():
    with pytest.raises(ValueError):
        _lock(activation_lock_schema_version="")


# ---------------------------------------------------------------------------
# activation_lock_id independent recomputation
# ---------------------------------------------------------------------------


def test_rejects_tampered_activation_lock_id():
    with pytest.raises(ValueError):
        _lock(activation_lock_id="d" * 64)


def test_rejects_activation_lock_id_bad_format():
    with pytest.raises(ValueError):
        _lock(activation_lock_id="not-a-valid-hash")


@pytest.mark.parametrize(
    "field",
    [
        "protocol_version",
        "authorized_methodology_source_fingerprint",
        "authorized_project_id",
        "authorized_runtime_service",
        "authorized_runtime_revision",
    ],
)
def test_changing_identity_field_without_recomputing_id_fails(field):
    """Kimlik-taşıyan 5 alandan (şema versiyonu 6.'sı, sabit) herhangi biri
    değişirse ama activation_lock_id ESKİ kalırsa -- reddedilmeli."""
    kwargs = _base_kwargs()
    if field in ("authorized_methodology_source_fingerprint",):
        kwargs[field] = "f" * 64
    else:
        kwargs[field] = kwargs[field] + "-changed"
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock(**kwargs)


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("authorized_methodology_source_fingerprint", "f" * 64),
        ("authorized_project_id", "other-project-id"),
        ("authorized_runtime_service", "other-service"),
        ("authorized_runtime_revision", "other-revision"),
    ],
)
def test_identity_field_change_with_recomputed_id_changes_activation_lock_id(field, new_value):
    kwargs = _base_kwargs()
    kwargs[field] = new_value
    kwargs["activation_lock_id"] = compute_activation_lock_id(
        protocol_version=kwargs["protocol_version"],
        authorized_methodology_source_fingerprint=kwargs["authorized_methodology_source_fingerprint"],
        authorized_project_id=kwargs["authorized_project_id"],
        authorized_runtime_service=kwargs["authorized_runtime_service"],
        authorized_runtime_revision=kwargs["authorized_runtime_revision"],
    )
    new_lock = TechnicalV1ActivationLock(**kwargs)
    assert new_lock.activation_lock_id != _base_kwargs()["activation_lock_id"]


# ---------------------------------------------------------------------------
# Content-only fields: do NOT affect activation_lock_id, DO affect
# record_content_sha256
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("protocol_sha256", "e" * 64),
        ("freeze_manifest_sha256", "f" * 64),
        ("methodology_git_commit", "1234567890abcdef1234567890abcdef12345678"),
        ("methodology_approval_reference", "abcdef1234567890abcdef1234567890abcdef12"),
    ],
)
def test_content_only_field_change_does_not_change_activation_lock_id(field, new_value):
    base_lock = _lock()
    changed_lock = _lock(**{field: new_value})
    assert changed_lock.activation_lock_id == base_lock.activation_lock_id


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("protocol_sha256", "e" * 64),
        ("freeze_manifest_sha256", "f" * 64),
        ("methodology_git_commit", "1234567890abcdef1234567890abcdef12345678"),
        ("methodology_approval_reference", "abcdef1234567890abcdef1234567890abcdef12"),
    ],
)
def test_content_only_field_change_changes_record_content_sha256(field, new_value):
    base_lock = _lock()
    changed_lock = _lock(**{field: new_value})
    assert changed_lock.record_content_sha256 != base_lock.record_content_sha256


# ---------------------------------------------------------------------------
# record_content_sha256 includes activation_lock_id itself
# ---------------------------------------------------------------------------


def test_record_content_sha256_payload_includes_activation_lock_id():
    """Regresyon: record_content_sha256'nın payload'ı, activation_lock_id'yi
    DE içermeli -- yalnızca activation_lock_id doğrulamasına güvenmek yetmez,
    çünkü from_document_fields() dışındaki bir tüketici doğrudan
    record_content_sha256'yı bir bütünlük-kanıtı olarak kullanabilir."""
    lock = _lock()
    expected_payload = lock.to_content_fields()
    assert "activation_lock_id" in expected_payload
    assert expected_payload["activation_lock_id"] == lock.activation_lock_id
    assert lock.record_content_sha256 == content_sha256(expected_payload)

    # Payload'dan activation_lock_id çıkarılırsa hash FARKLI olmalı --
    # bu, activation_lock_id'nin gerçekten hash'e dahil olduğunun kanıtı.
    payload_without_id = dict(expected_payload)
    del payload_without_id["activation_lock_id"]
    assert content_sha256(payload_without_id) != lock.record_content_sha256


# ---------------------------------------------------------------------------
# SHA-256 format fields (protocol_sha256, freeze_manifest_sha256,
# authorized_methodology_source_fingerprint)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["protocol_sha256", "freeze_manifest_sha256"])
@pytest.mark.parametrize(
    "bad_value",
    ["A" * 64, "a" * 63, "a" * 65, "z" * 64, "", " " + "a" * 63],
)
def test_rejects_malformed_sha256_content_fields(field, bad_value):
    with pytest.raises(ValueError):
        _lock(**{field: bad_value})


@pytest.mark.parametrize(
    "bad_value",
    ["A" * 64, "a" * 63, "a" * 65, "z" * 64, "", " " + "a" * 63],
)
def test_rejects_malformed_methodology_fingerprint(bad_value):
    kwargs = _base_kwargs()
    kwargs["authorized_methodology_source_fingerprint"] = bad_value
    # activation_lock_id doğrulamasından ÖNCE format hatası yakalanmalı.
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock(**kwargs)


# ---------------------------------------------------------------------------
# Git-SHA format fields (methodology_git_commit, methodology_approval_reference)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["methodology_git_commit", "methodology_approval_reference"])
@pytest.mark.parametrize(
    "bad_value",
    [
        "A" * 40,  # uppercase
        "a" * 39,  # too short
        "a" * 41,  # too long
        "z" * 40,  # non-hex char
        "",  # empty
        " " + "a" * 39,  # whitespace-padded
        "a" * 39 + " ",
    ],
)
def test_rejects_malformed_git_sha_fields(field, bad_value):
    with pytest.raises(ValueError):
        _lock(**{field: bad_value})


def test_valid_git_sha_accepted_without_verifying_existence():
    """Bu saf şema katmanı, commit'in GERÇEKTEN var olup olmadığını veya
    onaylanıp onaylanmadığını KONTROL ETMEZ -- yalnızca format. Bu test git
    çalıştırmadan yalnızca formatın kabul edildiğini doğrular."""
    lock = _lock(methodology_approval_reference="0123456789abcdef0123456789abcdef01234567")
    assert lock.methodology_approval_reference == "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Runtime identity components (authorized_project_id/service/revision)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["authorized_project_id", "authorized_runtime_service", "authorized_runtime_revision"]
)
@pytest.mark.parametrize("bad_value", ["", " project", "project ", "proj/ect", "/", "a/b/c"])
def test_rejects_malformed_runtime_component(field, bad_value):
    kwargs = _base_kwargs()
    kwargs[field] = bad_value
    if field != "activation_lock_id":
        # activation_lock_id, bozuk bileşen ile uyuşmayacağından zaten
        # ValueError fırlatılacak -- ama önce bileşen formatı kontrol edilmeli.
        pass
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock(**kwargs)


# ---------------------------------------------------------------------------
# protocol_version format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["", " TECHNICAL_V1_PROTOCOL_V1", "TECHNICAL_V1_PROTOCOL_V1 "])
def test_rejects_malformed_protocol_version(bad_value):
    with pytest.raises(ValueError):
        _lock(protocol_version=bad_value)


# ---------------------------------------------------------------------------
# to_document_fields / from_document_fields round trip
# ---------------------------------------------------------------------------


def test_document_fields_round_trip():
    lock = _lock()
    doc = lock.to_document_fields()
    assert set(doc.keys()) == {
        "activation_lock_schema_version",
        "activation_lock_id",
        "protocol_version",
        "protocol_sha256",
        "freeze_manifest_sha256",
        "methodology_git_commit",
        "authorized_methodology_source_fingerprint",
        "authorized_project_id",
        "authorized_runtime_service",
        "authorized_runtime_revision",
        "methodology_approval_reference",
        "record_content_sha256",
    }
    reconstructed = TechnicalV1ActivationLock.from_document_fields(doc)
    assert reconstructed == lock
    assert reconstructed.to_document_fields() == doc


def test_from_document_fields_rejects_missing_field():
    doc = _lock().to_document_fields()
    del doc["methodology_approval_reference"]
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock.from_document_fields(doc)


def test_from_document_fields_rejects_unknown_field():
    doc = _lock().to_document_fields()
    doc["unexpected_extra_field"] = "surprise"
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock.from_document_fields(doc)


def test_from_document_fields_rejects_tampered_record_content_sha256():
    """record_content_sha256, gerçek içerikle uyuşmadığında -- körü körüne
    güvenilmemeli, ValueError fırlatılmalı."""
    doc = _lock().to_document_fields()
    doc["record_content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock.from_document_fields(doc)


def test_from_document_fields_rejects_tampered_activation_lock_id_even_if_record_hash_recomputed():
    """activation_lock_id tek başına bozulursa (record_content_sha256
    tutarsız hale gelmesi BEKLENDİĞİ için) -- reconstruct sırasında ÖNCE
    __post_init__'in kendi activation_lock_id yeniden-türetme kontrolü
    başarısız olmalı."""
    doc = _lock().to_document_fields()
    doc["activation_lock_id"] = "9" * 64
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock.from_document_fields(doc)


def test_from_document_fields_no_schema_repair():
    """Bilinmeyen alanlar sessizce yok sayılmaz, eksik alanlar sessizce
    varsayılan bir değerle doldurulmaz -- katı reddetme."""
    doc = _lock().to_document_fields()
    doc.pop("protocol_sha256")
    doc["totally_unrelated"] = "x"
    with pytest.raises(ValueError):
        TechnicalV1ActivationLock.from_document_fields(doc)


# ---------------------------------------------------------------------------
# compute_runtime_fingerprint
# ---------------------------------------------------------------------------


def test_runtime_fingerprint_format():
    fingerprint = compute_runtime_fingerprint("proj-1", "svc-1", "rev-1")
    assert fingerprint == "proj-1/svc-1/rev-1"


@pytest.mark.parametrize(
    "project_id,service,revision",
    [
        ("a/b", "svc", "rev"),
        ("proj", "s/vc", "rev"),
        ("proj", "svc", "r/ev"),
    ],
)
def test_runtime_fingerprint_rejects_component_containing_slash(project_id, service, revision):
    with pytest.raises(ValueError):
        compute_runtime_fingerprint(project_id, service, revision)


@pytest.mark.parametrize(
    "project_id,service,revision",
    [
        ("", "svc", "rev"),
        ("proj", "", "rev"),
        ("proj", "svc", ""),
        (" proj", "svc", "rev"),
        ("proj ", "svc", "rev"),
    ],
)
def test_runtime_fingerprint_rejects_empty_or_whitespace_padded_component(project_id, service, revision):
    with pytest.raises(ValueError):
        compute_runtime_fingerprint(project_id, service, revision)


def test_runtime_fingerprint_different_inputs_produce_different_outputs():
    base = compute_runtime_fingerprint("proj", "svc", "rev")
    assert compute_runtime_fingerprint("other-proj", "svc", "rev") != base
    assert compute_runtime_fingerprint("proj", "other-svc", "rev") != base
    assert compute_runtime_fingerprint("proj", "svc", "other-rev") != base


# ---------------------------------------------------------------------------
# compute_activation_lock_id determinism / sensitivity
# ---------------------------------------------------------------------------


def test_compute_activation_lock_id_deterministic():
    kwargs = dict(
        protocol_version=PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=METHODOLOGY_FINGERPRINT,
        authorized_project_id=PROJECT_ID,
        authorized_runtime_service=RUNTIME_SERVICE,
        authorized_runtime_revision=RUNTIME_REVISION,
    )
    assert compute_activation_lock_id(**kwargs) == compute_activation_lock_id(**kwargs)


def test_compute_activation_lock_id_is_64_hex():
    lock_id = compute_activation_lock_id(
        protocol_version=PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=METHODOLOGY_FINGERPRINT,
        authorized_project_id=PROJECT_ID,
        authorized_runtime_service=RUNTIME_SERVICE,
        authorized_runtime_revision=RUNTIME_REVISION,
    )
    assert len(lock_id) == 64
    assert all(c in "0123456789abcdef" for c in lock_id)
