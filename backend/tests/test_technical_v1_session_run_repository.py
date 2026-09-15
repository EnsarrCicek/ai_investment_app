"""HATA 12N3C1 — `TechnicalV1SessionRunRepository`'nin (KASITLI OLARAK
MUTABLE, bilimsel kanıt OLMAYAN operasyonel durum) KENDİ (production)
metodlarını, gerçek Firestore/ağ olmadan, doğrudan çalıştıran testler.

Desen `test_technical_v1_session_manifest_repository.py` ile AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle
DEĞİŞTİRİYORUZ (constructor'da doğrudan `db` enjekte edilir). Bu
repository create-only DEĞİLDİR -- sahte `_FakeDocRef.set()` gerçek
TAM DEĞİŞTİRME (full replacement) semantiğini taklit eder (önceki
içeriği TAMAMEN SİLİP yenisiyle DEĞİŞTİRİR)."""

import hashlib
from datetime import datetime, timezone

import pytest

from app.repositories import technical_v1_session_run_repository as repo_module
from app.repositories.technical_v1_session_run_repository import (
    COLLECTION,
    PersistedTechnicalV1SessionRun,
    TechnicalV1SessionRunRepository,
)
from app.research.evidence_identity import compute_session_id
from app.research.session_run import SessionRunStatus, TechnicalV1SessionRunSnapshot

PROTOCOL = "TECHNICAL_V1_PROTOCOL_V1"
T_DATE = "2026-09-09"


def _h(i: int) -> str:
    return hashlib.sha256(f"eval-{i}".encode()).hexdigest()


def _session_id() -> str:
    return compute_session_id(PROTOCOL, T_DATE)


def _make_snapshot(retry_pending=(), provenance_blocked=()) -> TechnicalV1SessionRunSnapshot:
    return TechnicalV1SessionRunSnapshot(
        session_id=_session_id(),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        retry_pending_evaluation_ids=tuple(retry_pending),
        provenance_blocked_evaluation_ids=tuple(provenance_blocked),
    )


# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- TAM DEĞİŞTİRME (full replacement)
# semantiğini taklit eder; `set(payload, merge=False)` her zaman ÖNCEKİ
# içeriği TAMAMEN SİLER.
# ---------------------------------------------------------------------------

_FAKE_SERVER_TIMESTAMP_SENTINEL = object()


class _FakeDocSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        return _FakeDocSnapshot(self._store.get(self._key))

    def set(self, payload, merge=False):
        if merge:
            raise AssertionError("production kodu merge=True KULLANMAMALI -- bu sahte bunu YAKALAR")
        # Gerçek Firestore SERVER_TIMESTAMP sentinel'ini bir commit sonrası
        # tz-aware bir sunucu zaman damgasına ÇÖZER -- sahte AYNI davranışı
        # taklit eder (sentinel gerçek bir datetime'a dönüşür).
        resolved = dict(payload)
        for key, value in resolved.items():
            if value is _FAKE_SERVER_TIMESTAMP_SENTINEL:
                resolved[key] = datetime.now(timezone.utc)
        self._store[self._key] = resolved  # TAM DEĞİŞTİRME -- önceki tüm alanlar SİLİNİR


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id)


class _FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))

    def raw_store(self, name):
        return self._collections.setdefault(name, {})


@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(repo_module.firestore, "SERVER_TIMESTAMP", _FAKE_SERVER_TIMESTAMP_SENTINEL)
    return _FakeFirestoreClient()


@pytest.fixture
def repo(fake_db):
    return TechnicalV1SessionRunRepository(db=fake_db)


# ---------------------------------------------------------------------------
# upsert() -- full replacement, SERVER_TIMESTAMP injection
# ---------------------------------------------------------------------------


def test_upsert_then_get_round_trips_logical_snapshot(repo):
    snapshot = _make_snapshot(retry_pending=[_h(1)])
    repo.upsert(snapshot)

    persisted = repo.get(snapshot.session_id)
    assert isinstance(persisted, PersistedTechnicalV1SessionRun)
    assert persisted.snapshot == snapshot


def test_upsert_injects_server_timestamp_not_present_in_logical_fields(repo, fake_db):
    snapshot = _make_snapshot()
    repo.upsert(snapshot)

    stored = fake_db.raw_store(COLLECTION)[snapshot.session_id]
    assert "updated_at" in stored
    assert isinstance(stored["updated_at"], datetime)
    assert "updated_at" not in snapshot.to_document_fields()


def test_upsert_uses_set_not_merge(repo, fake_db):
    snapshot = _make_snapshot()
    repo.upsert(snapshot)  # merge=True would raise AssertionError inside the fake
    assert snapshot.session_id in fake_db.raw_store(COLLECTION)


def test_upsert_never_calls_create_update_or_array_union(fake_db, repo):
    snapshot = _make_snapshot()
    doc_ref = fake_db.collection(COLLECTION).document(snapshot.session_id)
    # Sahte `_FakeDocRef` yalnizca `get`/`set` tanimlar -- production kodu
    # baska bir metod cagirmaya calisirsa AttributeError firlar.
    assert set(dir(doc_ref)) & {"create", "update", "array_union", "array_remove"} == set()
    repo.upsert(snapshot)


def test_full_replacement_removes_stale_fields(repo, fake_db):
    first = _make_snapshot(retry_pending=[_h(1)])
    repo.upsert(first)

    # Onceki gecisten kalmis, artik gecersiz/bayat bir alani KASITLI OLARAK
    # dogrudan store'a enjekte ediyoruz -- upsert() TAM DEGISTIRME
    # semantigiyle bunu SILMELIDIR.
    store = fake_db.raw_store(COLLECTION)
    stored = dict(store[first.session_id])
    stored["stale_obsolete_field"] = "leftover"
    store[first.session_id] = stored

    second = _make_snapshot(retry_pending=[])  # eval_1 cozuldu
    repo.upsert(second)

    final_raw = fake_db.raw_store(COLLECTION)[second.session_id]
    assert "stale_obsolete_field" not in final_raw
    assert final_raw["retry_pending_evaluation_ids"] == []

    persisted = repo.get(second.session_id)
    assert persisted.snapshot.retry_pending_evaluation_ids == ()


def test_repeated_identical_upsert_preserves_logical_snapshot(repo):
    snapshot = _make_snapshot(retry_pending=[_h(1)])
    repo.upsert(snapshot)
    first_read = repo.get(snapshot.session_id)

    repo.upsert(snapshot)
    second_read = repo.get(snapshot.session_id)

    assert first_read.snapshot == second_read.snapshot == snapshot
    # updated_at DEGISMESI BEKLENIR/kabul edilebilir -- byte-bir-byte
    # persistence ESITLIGI ASLA iddia edilmez.


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


def test_get_returns_none_for_absent_session(repo):
    assert repo.get(_session_id()) is None


def test_get_rejects_unexpected_stored_field(repo, fake_db):
    snapshot = _make_snapshot()
    repo.upsert(snapshot)
    store = fake_db.raw_store(COLLECTION)
    stored = dict(store[snapshot.session_id])
    stored["unexpected_field"] = "x"
    store[snapshot.session_id] = stored

    with pytest.raises(ValueError):
        repo.get(snapshot.session_id)


def test_get_rejects_missing_stored_field(repo, fake_db):
    snapshot = _make_snapshot()
    repo.upsert(snapshot)
    store = fake_db.raw_store(COLLECTION)
    stored = dict(store[snapshot.session_id])
    del stored["status"]
    store[snapshot.session_id] = stored

    with pytest.raises(ValueError):
        repo.get(snapshot.session_id)


def test_get_rejects_wrong_document_identity(repo, fake_db):
    other_snapshot = _make_snapshot()
    other_fields = other_snapshot.to_document_fields()
    # Baska bir (kendi icinde tutarli) oturumun icerigini, YANLIS bir
    # doküman ID'si altina dogrudan yerlestiriyoruz.
    wrong_key = "d" * 64
    fake_db.raw_store(COLLECTION)[wrong_key] = {**other_fields, "updated_at": datetime.now(timezone.utc)}

    with pytest.raises(ValueError):
        repo.get(wrong_key)


@pytest.mark.parametrize(
    "malformed_updated_at",
    [None, "2026-09-09T10:15:00+00:00", 1757000000, datetime(2026, 9, 9, 10, 15, 0)],
    ids=["missing_none", "string", "int_epoch", "naive_datetime"],
)
def test_get_rejects_malformed_updated_at(repo, fake_db, malformed_updated_at):
    snapshot = _make_snapshot()
    repo.upsert(snapshot)
    store = fake_db.raw_store(COLLECTION)
    stored = dict(store[snapshot.session_id])
    if malformed_updated_at is None:
        del stored["updated_at"]
    else:
        stored["updated_at"] = malformed_updated_at
    store[snapshot.session_id] = stored

    with pytest.raises(ValueError):
        repo.get(snapshot.session_id)


def test_get_rejects_stored_status_inconsistent_with_id_lists(repo, fake_db):
    snapshot = _make_snapshot(retry_pending=[_h(1)])
    repo.upsert(snapshot)
    store = fake_db.raw_store(COLLECTION)
    stored = dict(store[snapshot.session_id])
    stored["status"] = SessionRunStatus.INCOMPLETE.value  # retry_pending dolu ama status INCOMPLETE
    store[snapshot.session_id] = stored

    with pytest.raises(ValueError):
        repo.get(snapshot.session_id)


# ---------------------------------------------------------------------------
# Trust boundary -- repository ne import EDER ne de EDEMEZ
# ---------------------------------------------------------------------------


def test_repository_does_not_import_immutable_repository_write_layers():
    module_names = set(vars(repo_module))
    forbidden_names = {
        "TechnicalV1EvaluationRepository",
        "TechnicalV1SessionManifestRepository",
        "TechnicalV1AttemptRepository",
        "EvidenceObjectStore",
        "FinalEvaluation",
        "TechnicalV1SessionManifest",
    }
    assert forbidden_names.isdisjoint(module_names)

    forbidden_modules = {
        "app.repositories.technical_v1_evaluation_repository",
        "app.repositories.technical_v1_session_manifest_repository",
        "app.repositories.technical_v1_attempt_repository",
        "app.research.evidence_object_store",
        "app.research.final_evaluation_models",
        "app.research.session_manifest",
    }
    for name, value in vars(repo_module).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"


def test_persisted_run_has_no_scientific_hash():
    snapshot = _make_snapshot()
    persisted = PersistedTechnicalV1SessionRun(snapshot=snapshot, updated_at=datetime.now(timezone.utc))
    assert not hasattr(persisted, "record_content_sha256")
    assert not hasattr(persisted.snapshot, "record_content_sha256")


def test_no_user_data_fields_anywhere_in_schema():
    snapshot = _make_snapshot(retry_pending=[_h(1)], provenance_blocked=[_h(2)])
    doc_fields = snapshot.to_document_fields()
    forbidden_substrings = ("user", "uid", "email", "portfolio", "watchlist", "notification")
    for key in doc_fields:
        lowered = key.lower()
        assert not any(term in lowered for term in forbidden_substrings), key
