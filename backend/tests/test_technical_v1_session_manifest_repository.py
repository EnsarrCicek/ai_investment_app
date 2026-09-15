"""HATA 12N3B — `TechnicalV1SessionManifestRepository`'nin (immutable
session manifest persistence: create-only, `CREATED`/`IDEMPOTENT_REUSE`,
ASLA en-son-kazanır) KENDİ (production) metodlarını, gerçek Firestore/ağ
olmadan, doğrudan çalıştıran testler.

Desen `test_technical_v1_evaluation_repository.py` ile AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle
DEĞİŞTİRİYORUZ (constructor'da doğrudan `db` enjekte edilir) -- BAŞKA
bir "fake repository" sınıfı YOK, testler doğrudan
`TechnicalV1SessionManifestRepository`'nin gerçek `create()`/
`get_verified()` metodlarını (ve dolayısıyla özel `_verify_and_
reconstruct()` boru hattını) egzersiz eder.
"""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_session_manifest_repository as repo_module
from app.repositories.technical_v1_session_manifest_repository import (
    COLLECTION,
    PersistedTechnicalV1SessionManifest,
    SessionManifestOutcome,
    TechnicalV1SessionManifestRepository,
)
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_session_id
from app.research.evidence_models import ProvenanceConflictError
from app.research.session_manifest import (
    TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION,
    TechnicalV1SessionManifest,
    compute_expected_evaluation_ids_sha256,
    compute_final_evaluation_records_sha256,
    derive_expected_evaluation_ids,
)


# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- test_technical_v1_evaluation_repository.py
# ile AYNI desen, artı `create_time` sunucu-metadata desteği.
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
        self._create_times[self._key] = datetime(2026, 9, 10, 10, 15, 0, tzinfo=timezone.utc)


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
    return TechnicalV1SessionManifestRepository(db=fake_db)


# ---------------------------------------------------------------------------
# Ortak test verisi
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_T_SESSION_DATE = "2026-09-09"


def _symbols(n: int = 100) -> tuple[str, ...]:
    return tuple(f"SYM{i:03d}" for i in range(n))


def _make_manifest(
    protocol_version: str = _PROTOCOL_VERSION,
    T_session_date: str = _T_SESSION_DATE,
    protocol_sha256: str = "a" * 64,
    freeze_manifest_sha256: str = "b" * 64,
    capture_status_counts: dict | None = None,
    evaluation_integrity_status_counts: dict | None = None,
    technical_observation_eligible_count: int = 0,
) -> TechnicalV1SessionManifest:
    symbols = _symbols()
    ids = derive_expected_evaluation_ids(protocol_version, T_session_date, symbols)
    expected_hash = compute_expected_evaluation_ids_sha256(ids)
    records_hash = compute_final_evaluation_records_sha256([(id_, id_) for id_ in ids])
    return TechnicalV1SessionManifest(
        manifest_schema_version=TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION,
        session_id=compute_session_id(protocol_version, T_session_date),
        protocol_version=protocol_version,
        T_session_date=T_session_date,
        protocol_sha256=protocol_sha256,
        freeze_manifest_sha256=freeze_manifest_sha256,
        expected_symbol_count=100,
        expected_evaluation_ids_sha256=expected_hash,
        final_evaluation_records_sha256=records_hash,
        capture_status_counts=capture_status_counts
        or {"VALID_CAPTURE_AVAILABLE": 0, "NO_VALID_CAPTURE_AVAILABLE": 100, "INFRASTRUCTURE_BLOCKED": 0},
        evaluation_integrity_status_counts=evaluation_integrity_status_counts
        or {"CLEAN": 0, "AUDIT_INCOMPLETE": 100, "EVIDENCE_INTEGRITY_FAILURE": 0, "PROVENANCE_CONFLICT": 0},
        technical_observation_eligible_count=technical_observation_eligible_count,
    )


def _seed_existing(fake_db, manifest: TechnicalV1SessionManifest) -> dict:
    """Repository BYPASS edilerek, ham store'a dogrudan bir doc yazar --
    boylece "onceden var olan (belki bozulmus) doküman" senaryolari
    kurulabilir."""
    store = fake_db.raw_store(COLLECTION)
    fields = manifest.to_document_fields()
    store[manifest.session_id] = fields
    return fields


def _rehash(content_fields: dict) -> str:
    """Verilen (record_content_sha256 HARIC) icerik alanlari uzerinden
    KANONIK/DOGRU record_content_sha256'yi yeniden hesaplar -- testlerde
    "saldirgan kendi hash'ini dogru hesapladi" senaryosunu simule etmek
    icin kullanilir."""
    return content_sha256({k: v for k, v in content_fields.items() if k != "record_content_sha256"})


# ---------------------------------------------------------------------------
# create() -- ilk yaratım / idempotent yeniden kullanım / gerçek çakışma
# ---------------------------------------------------------------------------


def test_first_create_is_created(repo):
    manifest = _make_manifest()
    assert repo.create(manifest) == SessionManifestOutcome.CREATED


def test_second_identical_create_is_idempotent_reuse(repo):
    manifest = _make_manifest()
    assert repo.create(manifest) == SessionManifestOutcome.CREATED
    assert repo.create(manifest) == SessionManifestOutcome.IDEMPOTENT_REUSE


def test_second_identical_create_does_not_write_or_mutate_stored_document(repo, fake_db):
    manifest = _make_manifest()
    repo.create(manifest)
    stored_before = dict(fake_db.raw_store(COLLECTION)[manifest.session_id])

    repo.create(manifest)
    stored_after = fake_db.raw_store(COLLECTION)[manifest.session_id]
    assert stored_after == stored_before


def test_create_never_calls_set_update_or_add(fake_db, repo):
    manifest = _make_manifest()
    doc_ref = fake_db.collection(COLLECTION).document(manifest.session_id)
    # Sahte `_FakeDocRef` yalnizca `get`/`create` tanimlar -- production
    # kodu baska bir metod cagirmaya calisirsa AttributeError firlar.
    assert set(dir(doc_ref)) & {"set", "update", "add", "delete"} == set()
    repo.create(manifest)


def test_create_rejects_candidate_with_self_inconsistent_session_id(repo, fake_db):
    """`TechnicalV1SessionManifest.__post_init__` session_id tutarliligini
    ZATEN dogrular -- bu senaryo mesru bir constructor cagrisiyla
    KURULAMAZ (aksine `FinalEvaluation`, kendi `__post_init__`'i olmadigi
    icin bu durumu N2B2'de dogal olarak SERGILEYEBILIYORDU). Repository'nin
    KENDI (savunma amacli, ikinci bir katman) create-zamani kontrolunu
    izole test etmek icin, frozen dataclass'in `session_id` alanini
    __post_init__'i TEKRAR TETIKLEMEDEN dogrudan mutate ediyoruz."""
    manifest = _make_manifest()
    object.__setattr__(manifest, "session_id", "d" * 64)

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)

    assert fake_db.raw_store(COLLECTION) == {}


# ---------------------------------------------------------------------------
# Conflict senaryolari -- ayni session_id, farkli icerik
# ---------------------------------------------------------------------------


def test_same_session_id_different_final_evaluation_records_sha256_is_conflict(repo):
    manifest_a = _make_manifest()
    repo.create(manifest_a)

    other_ids = derive_expected_evaluation_ids(_PROTOCOL_VERSION, _T_SESSION_DATE, _symbols())
    different_records_hash = compute_final_evaluation_records_sha256(
        [(id_, ("f" * 64) if i == 0 else id_) for i, id_ in enumerate(other_ids)]
    )
    from dataclasses import replace

    manifest_b = replace(manifest_a, final_evaluation_records_sha256=different_records_hash)
    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest_b)


def test_same_session_id_different_expected_evaluation_ids_sha256_is_conflict(repo):
    manifest_a = _make_manifest()
    repo.create(manifest_a)

    from dataclasses import replace

    manifest_b = replace(manifest_a, expected_evaluation_ids_sha256="e" * 64)
    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest_b)


def test_same_session_id_different_counts_is_conflict(repo):
    manifest_a = _make_manifest()
    repo.create(manifest_a)

    manifest_b = _make_manifest(
        capture_status_counts={"VALID_CAPTURE_AVAILABLE": 1, "NO_VALID_CAPTURE_AVAILABLE": 99, "INFRASTRUCTURE_BLOCKED": 0},
        technical_observation_eligible_count=1,
    )
    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest_b)


# ---------------------------------------------------------------------------
# HATA 12N3B -- ADVERSARIAL "hash-consistent ama kanonik DEGIL" senaryolari
# (N2B2-F ile ayni tasarim: saldirgan govdeyi degistirir VE hash'i o
# DEGISTIRILMIS govde uzerinden DOGRU yeniden hesaplar).
# ---------------------------------------------------------------------------


def test_top_level_extra_field_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    tampered["unexpected_field"] = "x"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(manifest.session_id)


def test_count_map_extra_key_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    tampered["capture_status_counts"] = {**tampered["capture_status_counts"], "UNKNOWN": 0}
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_missing_zero_capture_count_key_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)
    assert stored["capture_status_counts"]["INFRASTRUCTURE_BLOCKED"] == 0

    tampered = dict(stored)
    counts = dict(tampered["capture_status_counts"])
    del counts["INFRASTRUCTURE_BLOCKED"]
    tampered["capture_status_counts"] = counts
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_missing_zero_integrity_count_key_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)
    assert stored["evaluation_integrity_status_counts"]["EVIDENCE_INTEGRITY_FAILURE"] == 0

    tampered = dict(stored)
    counts = dict(tampered["evaluation_integrity_status_counts"])
    del counts["EVIDENCE_INTEGRITY_FAILURE"]
    tampered["evaluation_integrity_status_counts"] = counts
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_existing_document_with_stale_hash_after_body_tamper_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)
    stale_hash = stored["record_content_sha256"]

    tampered = dict(stored)
    tampered["expected_symbol_count"] = 99  # icerik degisti
    tampered["record_content_sha256"] = stale_hash  # hash ESKI kaldi
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_existing_document_with_hash_replaced_by_another_valid_hash_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    other_valid_hash = content_sha256({"unrelated": "payload"})
    tampered = dict(stored)
    tampered["record_content_sha256"] = other_valid_hash
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


@pytest.mark.parametrize(
    "malformed_hash",
    [None, "", "a" * 63, "A" * 64, "g" * 64, "a" * 65, 12345],
    ids=["missing_none", "empty", "63_chars", "uppercase", "non_hex", "65_chars", "not_a_string"],
)
def test_existing_document_with_malformed_stored_hash_is_conflict_not_raw_valueerror(repo, fake_db, malformed_hash):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    if malformed_hash is None:
        del tampered["record_content_sha256"]
    else:
        tampered["record_content_sha256"] = malformed_hash
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_hash_consistent_but_semantically_invalid_manifest_is_conflict(repo, fake_db):
    """Ham hash GECERLI (saldirgan dogru hesapladi) ama semantik olarak
    imkansiz: expected_symbol_count=99 -- from_document_fields()'in
    __post_init__'i bunu reddeder."""
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    tampered["expected_symbol_count"] = 99
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_hash_consistent_but_eligible_count_invariant_violated_is_conflict(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    tampered["technical_observation_eligible_count"] = 1  # VALID_CAPTURE_AVAILABLE hala 0
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(manifest)


def test_wrong_stored_session_identity_is_conflict(repo, fake_db):
    """Doküman ID'si bir oturuma (T_DATE) ait, ama gövde İÇERİĞİ BAŞKA bir
    oturuma (farklı T_session_date) ait -- gövde KENDİ İÇİNDE tamamen
    tutarlı/hash-gecerli olsa BILE, doküman ID'sinden farklı bir
    session_id'ye işaret ettiği için reddedilmelidir."""
    wrong_session_manifest = _make_manifest(T_session_date="2026-09-10")
    wrong_body = wrong_session_manifest.to_document_fields()

    right_session_manifest = _make_manifest()  # sadece dogru session_id'yi elde etmek icin
    fake_db.raw_store(COLLECTION)[right_session_manifest.session_id] = wrong_body

    with pytest.raises(ProvenanceConflictError):
        repo.create(right_session_manifest)


# ---------------------------------------------------------------------------
# get_verified()
# ---------------------------------------------------------------------------


def test_get_verified_returns_none_for_absent_session(repo):
    manifest = _make_manifest()
    assert repo.get_verified(manifest.session_id) is None


def test_get_verified_returns_trusted_envelope_after_create(repo):
    manifest = _make_manifest()
    repo.create(manifest)

    persisted = repo.get_verified(manifest.session_id)
    assert isinstance(persisted, PersistedTechnicalV1SessionManifest)
    assert persisted.manifest == manifest
    assert persisted.create_time is not None
    assert persisted.create_time.tzinfo is not None


def test_get_verified_raises_provenance_conflict_for_tampered_document(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)

    tampered = dict(stored)
    tampered["expected_symbol_count"] = 99
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(manifest.session_id)


def test_get_verified_does_not_leak_raw_valueerror_on_malformed_hash(repo, fake_db):
    manifest = _make_manifest()
    stored = _seed_existing(fake_db, manifest)
    tampered = dict(stored)
    tampered["record_content_sha256"] = "not-hex-at-all"
    fake_db.raw_store(COLLECTION)[manifest.session_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(manifest.session_id)


def test_get_verified_never_exposes_create_time_inside_document_fields(repo):
    manifest = _make_manifest()
    repo.create(manifest)
    persisted = repo.get_verified(manifest.session_id)

    doc_fields = persisted.manifest.to_document_fields()
    assert "create_time" not in doc_fields
    assert "update_time" not in doc_fields
    assert "finalized_at" not in doc_fields
    assert "created_at" not in doc_fields


def test_get_verified_trusted_manifest_count_maps_are_deeply_immutable(repo):
    """HATA 12N3B-F section 13: gercek `get_verified()` yolundan donen
    GUVENILIR manifest'in sayim eslemeleri uzerinde dogrudan mutasyon
    denemesi sessizce basarili OLMAMALI -- deterministik bir `TypeError`
    firlatmalidir."""
    manifest = _make_manifest()
    repo.create(manifest)
    persisted = repo.get_verified(manifest.session_id)

    hash_before = persisted.manifest.record_content_sha256
    with pytest.raises(TypeError):
        persisted.manifest.capture_status_counts["VALID_CAPTURE_AVAILABLE"] += 1
    with pytest.raises(TypeError):
        persisted.manifest.evaluation_integrity_status_counts["CLEAN"] += 1
    assert persisted.manifest.record_content_sha256 == hash_before


# ---------------------------------------------------------------------------
# Regresyon: candidate'in kendi hash'i her zaman gecerlidir
# ---------------------------------------------------------------------------


def test_content_hash_regression_matches_record_content_sha256():
    manifest = _make_manifest()
    content_only = manifest.to_document_fields()
    stored_hash = content_only.pop("record_content_sha256")
    assert content_sha256(content_only) == manifest.record_content_sha256 == stored_hash


def test_manifest_round_trip_is_exact_and_hash_preserving():
    manifest = _make_manifest()
    doc1 = manifest.to_document_fields()
    reconstructed = TechnicalV1SessionManifest.from_document_fields(
        {k: v for k, v in doc1.items() if k != "record_content_sha256"}
    )
    doc2 = reconstructed.to_document_fields()

    assert doc1 == doc2
    assert reconstructed.record_content_sha256 == manifest.record_content_sha256
    assert reconstructed == manifest


# ---------------------------------------------------------------------------
# Trust boundary -- repository ne import EDER ne de EDEMEZ
# ---------------------------------------------------------------------------


def test_repository_does_not_import_evaluation_repository_or_builder():
    module_names = set(vars(repo_module))
    forbidden_names = {
        "TechnicalV1EvaluationRepository",
        "PersistedFinalEvaluation",
        "build_session_manifest",
        "FinalEvaluation",
    }
    assert forbidden_names.isdisjoint(module_names)

    forbidden_modules = {
        "app.repositories.technical_v1_evaluation_repository",
        "app.repositories.technical_v1_attempt_repository",
        "app.research.evidence_object_store",
        "app.research.final_evaluation_selector",
        "app.research.final_evaluation_models",
    }
    for name, value in vars(repo_module).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"
