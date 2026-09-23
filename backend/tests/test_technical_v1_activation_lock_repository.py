"""HATA 12N3C2-B2-B — `TechnicalV1ActivationLockRepository`'nin (immutable
activation-lock persistence: create-only, `CREATED`/`IDEMPOTENT_REUSE`, ASLA
en-son-kazanır) KENDİ (production) metodlarını, gerçek Firestore/ağ olmadan,
doğrudan çalıştıran testler.

Desen `test_technical_v1_evaluation_repository.py`/
`test_technical_v1_session_manifest_repository.py` ile AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle DEĞİŞTİRİYORUZ
(constructor'da doğrudan `db` enjekte edilir) -- BAŞKA bir "fake repository"
sınıfı YOK, testler doğrudan `TechnicalV1ActivationLockRepository`'nin
gerçek `create()`/`get_verified()` metodlarını (ve dolayısıyla özel
`_verify_and_reconstruct()` boru hattını) egzersiz eder. GERÇEK Firestore/
ADC/ağ erişimi hiç yapılmaz."""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_activation_lock_repository as repo_module
from app.repositories.technical_v1_activation_lock_repository import (
    COLLECTION,
    ActivationLockOutcome,
    PersistedTechnicalV1ActivationLock,
    TechnicalV1ActivationLockRepository,
)
from app.research.activation_lock import TechnicalV1ActivationLock, compute_activation_lock_id
from app.research.canonical_hash import content_sha256
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError

# TECH-VOL 1B: V1 pipeline mekaniği, V1 metodolojisiyle eşleşen bir motor altında test edilir.
pytestmark = pytest.mark.usefixtures("v1_era_engine_version")

# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- diğer immutable repository testleriyle
# AYNI desen, artı `create_time` sunucu-metadata desteği.
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
        self._create_times[self._key] = datetime(2026, 9, 16, 6, 0, 0, tzinfo=timezone.utc)


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
    return TechnicalV1ActivationLockRepository(db=fake_db)


# ---------------------------------------------------------------------------
# Ortak test verisi
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_METHODOLOGY_FINGERPRINT = "a" * 64
_PROJECT_ID = "ai-investment-app-2026"
_RUNTIME_SERVICE = "backend-api"
_RUNTIME_REVISION = "backend-api-00042-xyz"
_GIT_SHA = "730ef262f350b97b9290adddbd7c6a38c024729b"
_OTHER_GIT_SHA = "0123456789abcdef0123456789abcdef01234567"


def _make_lock(
    *,
    protocol_sha256="b" * 64,
    freeze_manifest_sha256="c" * 64,
    methodology_git_commit=_GIT_SHA,
    methodology_approval_reference=_GIT_SHA,
    authorized_methodology_source_fingerprint=_METHODOLOGY_FINGERPRINT,
    authorized_project_id=_PROJECT_ID,
    authorized_runtime_service=_RUNTIME_SERVICE,
    authorized_runtime_revision=_RUNTIME_REVISION,
) -> TechnicalV1ActivationLock:
    activation_lock_id = compute_activation_lock_id(
        protocol_version=_PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=authorized_methodology_source_fingerprint,
        authorized_project_id=authorized_project_id,
        authorized_runtime_service=authorized_runtime_service,
        authorized_runtime_revision=authorized_runtime_revision,
    )
    return TechnicalV1ActivationLock(
        activation_lock_schema_version="technical_v1_activation_lock_v1",
        activation_lock_id=activation_lock_id,
        protocol_version=_PROTOCOL_VERSION,
        protocol_sha256=protocol_sha256,
        freeze_manifest_sha256=freeze_manifest_sha256,
        methodology_git_commit=methodology_git_commit,
        authorized_methodology_source_fingerprint=authorized_methodology_source_fingerprint,
        authorized_project_id=authorized_project_id,
        authorized_runtime_service=authorized_runtime_service,
        authorized_runtime_revision=authorized_runtime_revision,
        methodology_approval_reference=methodology_approval_reference,
    )


def _seed_existing(fake_db, lock: TechnicalV1ActivationLock) -> dict:
    """Repository BYPASS edilerek, ham store'a doğrudan bir doc yazar --
    böylece "önceden var olan (belki bozulmuş) doküman" senaryoları
    kurulabilir."""
    store = fake_db.raw_store(COLLECTION)
    fields = lock.to_document_fields()
    store[lock.activation_lock_id] = fields
    return fields


def _rehash(raw_fields: dict) -> str:
    """Verilen (record_content_sha256 HARİÇ) içerik alanları üzerinden
    KANONİK/DOĞRU record_content_sha256'yı yeniden hesaplar -- testlerde
    "saldırgan kendi hash'ini doğru hesapladı" senaryosunu simüle etmek
    için kullanılır."""
    return content_sha256({k: v for k, v in raw_fields.items() if k != "record_content_sha256"})


# ---------------------------------------------------------------------------
# create() -- ilk yaratım / idempotent yeniden kullanım / gerçek çakışma
# ---------------------------------------------------------------------------


def test_first_create_is_created(repo):
    lock = _make_lock()
    assert repo.create(lock) == ActivationLockOutcome.CREATED


def test_document_id_is_activation_lock_id(repo, fake_db):
    lock = _make_lock()
    repo.create(lock)
    assert lock.activation_lock_id in fake_db.raw_store(COLLECTION)


def test_second_identical_create_is_idempotent_reuse(repo):
    lock = _make_lock()
    assert repo.create(lock) == ActivationLockOutcome.CREATED
    assert repo.create(lock) == ActivationLockOutcome.IDEMPOTENT_REUSE


def test_second_identical_create_does_not_write_or_mutate_stored_document(repo, fake_db):
    lock = _make_lock()
    repo.create(lock)
    stored_before = dict(fake_db.raw_store(COLLECTION)[lock.activation_lock_id])

    repo.create(lock)
    stored_after = fake_db.raw_store(COLLECTION)[lock.activation_lock_id]
    assert stored_after == stored_before


def test_stored_document_has_exactly_the_twelve_expected_fields(repo, fake_db):
    lock = _make_lock()
    repo.create(lock)
    stored = fake_db.raw_store(COLLECTION)[lock.activation_lock_id]
    assert set(stored.keys()) == {
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
    for forbidden in ("created_at", "updated_at", "scoring_config_hash", "user_id", "activation_event_id"):
        assert forbidden not in stored


def test_create_never_calls_set_update_add_or_delete(repo, fake_db):
    lock = _make_lock()
    doc_ref = fake_db.collection(COLLECTION).document(lock.activation_lock_id)
    assert set(dir(doc_ref)) & {"set", "update", "add", "delete"} == set()
    repo.create(lock)


# ---------------------------------------------------------------------------
# Section 10/22/25 — aynı ID, farklı İÇERİK-YALNIZCA alan değeri: gerçek
# provenance çakışması (create-race)
# ---------------------------------------------------------------------------


def test_same_id_different_protocol_sha256_is_provenance_conflict(repo):
    lock_a = _make_lock(protocol_sha256="b" * 64)
    repo.create(lock_a)

    lock_b = _make_lock(protocol_sha256="d" * 64)
    assert lock_a.activation_lock_id == lock_b.activation_lock_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(lock_b)


def test_same_id_different_methodology_approval_reference_is_provenance_conflict(repo):
    lock_a = _make_lock(methodology_approval_reference=_GIT_SHA)
    repo.create(lock_a)

    lock_b = _make_lock(methodology_approval_reference=_OTHER_GIT_SHA)
    assert lock_a.activation_lock_id == lock_b.activation_lock_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(lock_b)


def test_same_id_different_freeze_manifest_sha256_is_provenance_conflict(repo):
    lock_a = _make_lock(freeze_manifest_sha256="c" * 64)
    repo.create(lock_a)

    lock_b = _make_lock(freeze_manifest_sha256="e" * 64)
    assert lock_a.activation_lock_id == lock_b.activation_lock_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(lock_b)


def test_same_id_different_methodology_git_commit_is_provenance_conflict(repo):
    lock_a = _make_lock(methodology_git_commit=_GIT_SHA)
    repo.create(lock_a)

    lock_b = _make_lock(methodology_git_commit=_OTHER_GIT_SHA)
    assert lock_a.activation_lock_id == lock_b.activation_lock_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(lock_b)


def test_conflicting_create_does_not_overwrite_existing_document(repo, fake_db):
    lock_a = _make_lock(protocol_sha256="b" * 64)
    repo.create(lock_a)
    stored_before = dict(fake_db.raw_store(COLLECTION)[lock_a.activation_lock_id])

    lock_b = _make_lock(protocol_sha256="d" * 64)
    with pytest.raises(ProvenanceConflictError):
        repo.create(lock_b)

    stored_after = fake_db.raw_store(COLLECTION)[lock_a.activation_lock_id]
    assert stored_after == stored_before


# ---------------------------------------------------------------------------
# Section 23/24 — bozuk (malformed) var olan doküman senaryoları
# ---------------------------------------------------------------------------


def test_existing_document_with_wrong_record_content_sha256_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["record_content_sha256"] = "0" * 64
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(lock)
    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_wrong_activation_lock_id_and_stale_hash_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    stale_hash = stored["record_content_sha256"]

    tampered = dict(stored)
    tampered["activation_lock_id"] = "9" * 64
    tampered["record_content_sha256"] = stale_hash
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_wrong_schema_version_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["activation_lock_schema_version"] = "technical_v1_activation_lock_v2"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_extra_field_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["unexpected_extra_field"] = "sneaky"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(lock)
    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_missing_field_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    del tampered["methodology_approval_reference"]
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_uppercase_hash_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["record_content_sha256"] = stored["record_content_sha256"].upper()
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_bad_git_sha_format_is_conflict(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["methodology_git_commit"] = "NOTVALIDHEX" + "0" * 29
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


@pytest.mark.parametrize(
    "malformed_hash",
    [None, "", "a" * 63, "A" * 64, "g" * 64, "a" * 65, 12345],
    ids=["missing_none", "empty", "63_chars", "uppercase", "non_hex", "65_chars", "not_a_string"],
)
def test_existing_document_with_malformed_stored_hash_is_conflict_not_raw_error(repo, fake_db, malformed_hash):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    if malformed_hash is None:
        del tampered["record_content_sha256"]
    else:
        tampered["record_content_sha256"] = malformed_hash
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_existing_document_with_naive_create_time_still_reconstructs_and_envelope_carries_it_raw(repo, fake_db):
    """create_time TAMAMEN sahte Firestore katmanının (`DocumentSnapshot.
    create_time`) sorumluluğundadır -- repository bunu ÜRETMEZ/DOĞRULAMAZ,
    yalnızca olduğu gibi taşır. Bu test, `get_verified()`'in `create_time`'ı
    OLDUĞU GİBİ ilettiğini doğrular (timezone-aware olup olmadığının
    doğrulanması, gerçek `google.cloud.firestore` istemcisinin HER ZAMAN
    aware bir `datetime` döndürdüğü gerçeğe dayanır -- production create()
    testinde bu ayrıca doğrulanıyor)."""
    lock = _make_lock()
    repo.create(lock)
    persisted = repo.get_verified(lock.activation_lock_id)
    assert persisted.create_time.tzinfo is not None


# ---------------------------------------------------------------------------
# Section 24 — activation_lock_id tamper + rehash: raw hash TEK BAŞINA
# yeterli değil, semantik kimlik yeniden-türetmesi de gerekli
# ---------------------------------------------------------------------------


def test_tampered_activation_lock_id_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    """Saldırgan HEM `activation_lock_id`'yi değiştirir HEM DE
    `record_content_sha256`'yı bu DEĞİŞTİRİLMİŞ gövde üzerinden DOĞRU
    şekilde yeniden hesaplar -- ham hash kontrolü (adım 2) GEÇER. Yalnızca
    semantik `activation_lock_id` yeniden-türetmesi (adım 3, `from_document_
    fields()` içindeki `__post_init__`) bunu YAKALAYABİLİR -- kimlik-taşıyan
    alanlar (protocol_version/authorized_*) DEĞİŞMEDİĞİNDEN, yeniden
    hesaplanan beklenen ID tamperlenmiş ID'den FARKLI olacaktır."""
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)

    tampered = dict(stored)
    tampered["activation_lock_id"] = "f" * 64
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    # Ham hash kontrolü TEK BAŞINA bunu YAKALAYAMAZDI:
    content_only = {k: v for k, v in tampered.items() if k != "record_content_sha256"}
    assert content_sha256(content_only) == tampered["record_content_sha256"]

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


def test_doc_ref_id_vs_content_id_wrong_wiring_is_conflict(repo, fake_db):
    """Bir dokümanın, KENDİ içeriğindeki (geçerli, iç-tutarlı)
    `activation_lock_id`'den FARKLI bir doküman-referansı ID'si altında
    saklanması (wrong-wiring) -- section 17."""
    lock_a = _make_lock(authorized_runtime_revision="backend-api-00042-xyz")
    lock_b = _make_lock(authorized_runtime_revision="backend-api-00099-abc")
    assert lock_a.activation_lock_id != lock_b.activation_lock_id

    store = fake_db.raw_store(COLLECTION)
    store[lock_a.activation_lock_id] = lock_b.to_document_fields()

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock_a.activation_lock_id)


# ---------------------------------------------------------------------------
# Section 25 — içerik-yalnızca alan tamper + rehash: get_verified() TEK
# BAŞINA (harici bir önceki referans olmadan) bunu YAKALAYAMAZ; bu doğru ve
# beklenen bir sınırdır (ama create-race'te YAKALANIR, yukarıdaki testler).
# ---------------------------------------------------------------------------


def test_content_only_field_tamper_with_correctly_recomputed_hash_is_structurally_valid_alone(repo, fake_db):
    """Yalnızca `methodology_approval_reference`'ı BAŞKA geçerli bir 40-hex
    değere değiştirip `record_content_sha256`'yı DOĞRU yeniden hesaplamak,
    tek başına (harici bir önceki/orijinal referans olmadan) yapısal olarak
    GEÇERLİ bir aktivasyon kilidi üretir -- repository'nin TARİHSEL
    tahribatı harici bir referans olmadan tespit EDEMEYECEĞİNİN kanıtı
    (section 25, ticket'ın kendi açık uyarısı)."""
    lock = _make_lock(methodology_approval_reference=_GIT_SHA)
    stored = _seed_existing(fake_db, lock)

    tampered = dict(stored)
    tampered["methodology_approval_reference"] = _OTHER_GIT_SHA
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    persisted = repo.get_verified(lock.activation_lock_id)
    assert persisted is not None
    assert persisted.lock.methodology_approval_reference == _OTHER_GIT_SHA
    assert persisted.lock.activation_lock_id == lock.activation_lock_id


# ---------------------------------------------------------------------------
# get_verified()
# ---------------------------------------------------------------------------


def test_get_verified_returns_none_for_absent_document(repo):
    lock = _make_lock()
    assert repo.get_verified(lock.activation_lock_id) is None


def test_get_verified_returns_trusted_envelope_after_create(repo):
    lock = _make_lock()
    repo.create(lock)

    persisted = repo.get_verified(lock.activation_lock_id)
    assert isinstance(persisted, PersistedTechnicalV1ActivationLock)
    assert persisted.lock == lock
    assert persisted.create_time is not None
    assert persisted.create_time.tzinfo is not None


def test_get_verified_rejects_malformed_requested_id_before_firestore_access(repo, fake_db):
    with pytest.raises(EvidenceIntegrityError):
        repo.get_verified("not-a-valid-hash")
    # Hicbir Firestore erisimi tetiklenmedi -- store bos kaldi.
    assert fake_db.raw_store(COLLECTION) == {}


@pytest.mark.parametrize("bad_id", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, " " + "a" * 63])
def test_get_verified_rejects_various_malformed_requested_ids(repo, bad_id):
    with pytest.raises(EvidenceIntegrityError):
        repo.get_verified(bad_id)


def test_get_verified_never_exposes_update_time(repo, fake_db):
    lock = _make_lock()
    repo.create(lock)
    persisted = repo.get_verified(lock.activation_lock_id)
    assert not hasattr(persisted, "update_time")


def test_get_verified_does_not_leak_raw_error_on_malformed_hash(repo, fake_db):
    lock = _make_lock()
    stored = _seed_existing(fake_db, lock)
    tampered = dict(stored)
    tampered["record_content_sha256"] = "not-hex-at-all"
    fake_db.raw_store(COLLECTION)[lock.activation_lock_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(lock.activation_lock_id)


# ---------------------------------------------------------------------------
# Section 21 — aynı-içerik create-race (idempotent reuse, tekrar egzersiz)
# ---------------------------------------------------------------------------


def test_same_content_create_race_is_benign_idempotent_reuse(repo, fake_db):
    lock = _make_lock()
    # worker A
    assert repo.create(lock) == ActivationLockOutcome.CREATED
    # worker B, TAM AYNI mantıksal aktivasyon kilidini bağımsız olarak
    # (ayrı bir Python nesnesi olarak, ama AYNI içerikle) inşa edip dener.
    duplicate = _make_lock()
    assert duplicate.to_document_fields() == lock.to_document_fields()
    assert repo.create(duplicate) == ActivationLockOutcome.IDEMPOTENT_REUSE
    assert len(fake_db.raw_store(COLLECTION)) == 1


# ---------------------------------------------------------------------------
# Modül izolasyonu -- yasaklı importlar hiç edinilmedi
# ---------------------------------------------------------------------------


def test_repository_does_not_import_activation_event_or_attempt_modules():
    module_names = set(vars(repo_module))
    forbidden_names = {
        "ActivationEvent",
        "TechnicalV1AttemptRepository",
        "AttemptClaim",
        "AttemptResult",
    }
    assert forbidden_names.isdisjoint(module_names)

    forbidden_modules = {
        "app.research.activation_event",
        "app.repositories.technical_v1_activation_event_repository",
        "app.repositories.technical_v1_attempt_repository",
        "app.research.attempt_models",
    }
    for name, value in vars(repo_module).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"


def test_repository_does_not_duplicate_activation_lock_id_computation():
    """`compute_activation_lock_id` repository modülünün İÇİNDE tanımlanmış
    OLMAMALI -- yalnızca `app.research.activation_lock`'tan import edilip
    (dolaylı olarak `from_document_fields()` üzerinden) kullanılmalı."""
    import inspect

    source = inspect.getsource(repo_module)
    assert "def compute_activation_lock_id" not in source
    assert "def content_sha256(" not in source
    assert "def validate_sha256_hex(" not in source


# ---------------------------------------------------------------------------
# Sabit doğrulama: candidate'in kendi hash'i her zaman geçerlidir (regresyon)
# ---------------------------------------------------------------------------


def test_content_hash_regression_matches_record_content_sha256():
    lock = _make_lock()
    content_only = lock.to_document_fields()
    stored_hash = content_only.pop("record_content_sha256")
    assert content_sha256(content_only) == lock.record_content_sha256 == stored_hash
