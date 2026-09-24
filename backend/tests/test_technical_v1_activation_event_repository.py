"""HATA 13B — `TechnicalV1ActivationEventRepository`'nin (immutable
activation-event persistence: create-only, `CREATED`/`IDEMPOTENT_REUSE`,
ASLA en-son-kazanır) KENDİ (production) metodlarını, gerçek Firestore/ağ
olmadan, doğrudan çalıştıran testler.

Desen `test_technical_v1_activation_lock_repository.py` İLE AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle
DEĞİŞTİRİYORUZ (constructor'da doğrudan `db` enjekte edilir)."""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_activation_event_repository as repo_module
from app.repositories.technical_v1_activation_event_repository import (
    COLLECTION,
    ActivationEventOutcome,
    PersistedTechnicalV1ActivationEvent,
    TechnicalV1ActivationEventRepository,
)
from app.research.activation_event import (
    TechnicalV1ActivationEvent,
    build_initial_activation_event,
    build_lock_authorized_event,
)
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError

# TECHNICAL V2-R1: V1 olay depolama mekaniği V1 metodolojisiyle eşleşen motor altında test edilir.
pytestmark = pytest.mark.usefixtures("v1_era_engine_version")

# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- activation-lock repository testiyle AYNI
# desen.
# ---------------------------------------------------------------------------


class _FakeDocSnapshot:
    def __init__(self, data, create_time=None):
        self._data = data
        self.create_time = create_time

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, store, key, create_times):
        self._store = store
        self._key = key
        self._create_times = create_times

    def get(self):
        return _FakeDocSnapshot(self._store.get(self._key), self._create_times.get(self._key))

    def create(self, data):
        if self._key in self._store:
            raise AlreadyExists(f"document already exists: {self._key}")
        self._store[self._key] = dict(data)
        self._create_times[self._key] = datetime(2026, 9, 17, 6, 0, 0, tzinfo=timezone.utc)


class _FakeCollection:
    def __init__(self, store, create_times):
        self._store = store
        self._create_times = create_times

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id, self._create_times)


class _FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}
        self._create_times: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(
            self._collections.setdefault(name, {}),
            self._create_times.setdefault(name, {}),
        )

    def raw_store(self, name):
        return self._collections.setdefault(name, {})


@pytest.fixture
def fake_db():
    return _FakeFirestoreClient()


@pytest.fixture
def repo(fake_db):
    return TechnicalV1ActivationEventRepository(db=fake_db)


_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_LOCK_A = "a" * 64
_LOCK_B = "b" * 64


def _seed_existing(fake_db, event: TechnicalV1ActivationEvent) -> dict:
    store = fake_db.raw_store(COLLECTION)
    fields = event.to_document_fields()
    store[event.activation_event_id] = fields
    return fields


def _rehash(raw_fields: dict) -> str:
    return content_sha256({k: v for k, v in raw_fields.items() if k != "record_content_sha256"})


# ---------------------------------------------------------------------------
# create() -- ilk yaratım / idempotent yeniden kullanım (section 33)
# ---------------------------------------------------------------------------


def test_first_create_is_created(repo):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert repo.create(event) == ActivationEventOutcome.CREATED


def test_document_id_is_activation_event_id(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)
    assert event.activation_event_id in fake_db.raw_store(COLLECTION)


def test_second_identical_create_is_idempotent_reuse(repo):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert repo.create(event) == ActivationEventOutcome.CREATED
    assert repo.create(event) == ActivationEventOutcome.IDEMPOTENT_REUSE


def test_second_identical_create_does_not_mutate_stored_document(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)
    stored_before = dict(fake_db.raw_store(COLLECTION)[event.activation_event_id])

    repo.create(event)
    stored_after = fake_db.raw_store(COLLECTION)[event.activation_event_id]
    assert stored_after == stored_before


def test_stored_document_has_exactly_the_six_expected_fields(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)
    stored = fake_db.raw_store(COLLECTION)[event.activation_event_id]
    assert set(stored.keys()) == {
        "activation_event_schema_version",
        "activation_event_id",
        "event_type",
        "protocol_version",
        "activation_lock_id",
        "record_content_sha256",
    }
    for forbidden in ("created_at", "updated_at", "user_id", "actor_email", "notes"):
        assert forbidden not in stored


def test_create_never_calls_set_update_add_or_delete(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    doc_ref = fake_db.collection(COLLECTION).document(event.activation_event_id)
    assert set(dir(doc_ref)) & {"set", "update", "add", "delete"} == set()
    repo.create(event)


# ---------------------------------------------------------------------------
# section 6/30/34 — aynı INITIAL ID, farklı activation_lock_id: provenance
# çakışması (KİLİTLİ, kasıtlı senaryo)
# ---------------------------------------------------------------------------


def test_initial_same_id_different_lock_is_provenance_conflict(repo):
    event_lock_a = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event_lock_a)

    event_lock_b = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)
    assert event_lock_a.activation_event_id == event_lock_b.activation_event_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(event_lock_b)


def test_initial_conflict_does_not_overwrite_existing_document(repo, fake_db):
    event_lock_a = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event_lock_a)
    stored_before = dict(fake_db.raw_store(COLLECTION)[event_lock_a.activation_event_id])

    event_lock_b = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)
    with pytest.raises(ProvenanceConflictError):
        repo.create(event_lock_b)

    stored_after = fake_db.raw_store(COLLECTION)[event_lock_a.activation_event_id]
    assert stored_after == stored_before


# ---------------------------------------------------------------------------
# section 31 — LOCK_AUTHORIZED: farklı kilit -> farklı ID (çakışma DEĞİL,
# ayrı bağımsız kayıtlar)
# ---------------------------------------------------------------------------


def test_lock_authorized_different_locks_create_two_independent_events(repo):
    event_lock_a = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_lock_b = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)
    assert event_lock_a.activation_event_id != event_lock_b.activation_event_id
    assert repo.create(event_lock_a) == ActivationEventOutcome.CREATED
    assert repo.create(event_lock_b) == ActivationEventOutcome.CREATED


# ---------------------------------------------------------------------------
# section 32/34 — bozuk (malformed) var olan doküman senaryoları
# ---------------------------------------------------------------------------


def test_existing_document_with_wrong_record_content_sha256_is_conflict(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    tampered = dict(stored)
    tampered["record_content_sha256"] = "0" * 64
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(event)
    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(event.activation_event_id)


def test_existing_document_with_wrong_activation_event_id_and_stale_hash_is_conflict(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    stale_hash = stored["record_content_sha256"]

    tampered = dict(stored)
    tampered["activation_event_id"] = "9" * 64
    tampered["record_content_sha256"] = stale_hash
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(event.activation_event_id)


def test_existing_document_with_correctly_recomputed_hash_but_wrong_event_id_is_conflict(repo, fake_db):
    """Semantik yeniden-türetme, doğru-ama-tamperlenmiş bir kimliği yakalar:
    tamperlenmiş `activation_event_id` + KENDİ İÇİNDE doğru yeniden
    hesaplanmış `record_content_sha256`, yine de doc-ID vs content-ID
    kontrolünde YAKALANIR."""
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    tampered = dict(stored)
    tampered["activation_event_id"] = "9" * 64
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(event.activation_event_id)


def test_existing_document_with_unknown_event_type_is_conflict(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    tampered = dict(stored)
    tampered["event_type"] = "REVOKED"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(event.activation_event_id)


def test_existing_document_with_extra_field_is_conflict(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    tampered = dict(stored)
    tampered["actor_email"] = "someone@example.com"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(event)


def test_existing_document_with_missing_field_is_conflict(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    stored = _seed_existing(fake_db, event)
    tampered = dict(stored)
    del tampered["activation_lock_id"]
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[event.activation_event_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(event.activation_event_id)


# ---------------------------------------------------------------------------
# get_verified() (section 15)
# ---------------------------------------------------------------------------


def test_get_verified_returns_none_for_absent_document(repo):
    assert repo.get_verified("a" * 64) is None


def test_get_verified_returns_trusted_envelope_after_create(repo):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)

    envelope = repo.get_verified(event.activation_event_id)
    assert isinstance(envelope, PersistedTechnicalV1ActivationEvent)
    assert envelope.event == event


def test_get_verified_rejects_malformed_requested_id_before_firestore_access(repo, fake_db):
    with pytest.raises(EvidenceIntegrityError):
        repo.get_verified("not-a-sha256")
    # Hiçbir Firestore okuması yapılmadı -- collection hiç dokunulmadı.
    assert fake_db.raw_store(COLLECTION) == {}


# ---------------------------------------------------------------------------
# section 16/35 -- Firestore create_time
# ---------------------------------------------------------------------------


def test_get_verified_exposes_timezone_aware_create_time(repo):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)

    envelope = repo.get_verified(event.activation_event_id)
    assert envelope.create_time.tzinfo is not None


def test_create_time_is_not_part_of_domain_object_or_hash(repo):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    repo.create(event)
    envelope = repo.get_verified(event.activation_event_id)

    assert not hasattr(envelope.event, "create_time")
    assert envelope.event.record_content_sha256 == event.record_content_sha256


# ---------------------------------------------------------------------------
# Dependency isolation (mirrors activation-lock repository's own lock)
# ---------------------------------------------------------------------------


def test_repository_does_not_import_attempt_or_activation_lock_modules():
    import inspect

    source = inspect.getsource(repo_module)
    import_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    forbidden_substrings = (
        "technical_v1_attempt_repository",
        "attempt_models",
        "technical_v1_activation_lock_repository",
        "app.research.activation_lock",
        "preclaim_authorization",
    )
    for line in import_lines:
        for forbidden in forbidden_substrings:
            assert forbidden not in line, f"yasaklı bağımlılık bulundu: {line!r}"


def test_same_content_create_race_is_benign_idempotent_reuse(repo, fake_db):
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    _seed_existing(fake_db, event)  # repository BYPASS -- "eş-zamanlı ikinci yazar" simülasyonu
    assert repo.create(event) == ActivationEventOutcome.IDEMPOTENT_REUSE
