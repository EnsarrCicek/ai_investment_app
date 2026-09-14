"""HATA 12N2B2 — `TechnicalV1EvaluationRepository`'nin (immutable final
evaluation persistence: create-only, `CREATED`/`IDEMPOTENT_REUSE`, ASLA
en-son-kazanır) KENDİ (production) metodlarını, gerçek Firestore/ağ
olmadan, doğrudan çalıştıran testler.

Desen `test_technical_v1_attempt_repository.py` ile AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle DEĞİŞTİRİYORUZ
(constructor'da doğrudan `db` enjekte edilir) -- BAŞKA bir "fake repository"
sınıfı YOK, testler doğrudan `TechnicalV1EvaluationRepository`'nin gerçek
`create()`/`get_verified()` metodlarını (ve dolayısıyla özel
`_verify_and_reconstruct()` boru hattını) egzersiz eder.
"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_evaluation_repository as repo_module
from app.repositories.technical_v1_evaluation_repository import (
    COLLECTION,
    FinalEvaluationOutcome,
    PersistedFinalEvaluation,
    TechnicalV1EvaluationRepository,
)
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_evaluation_id
from app.research.evidence_models import ProvenanceConflictError
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    AttemptSummary,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalEvaluation,
    OrchestrationAnomalyCode,
    ResultState,
    VerificationState,
)


# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- test_technical_v1_attempt_repository.py
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
        self._create_times[self._key] = datetime(2026, 9, 10, 6, 0, 0, tzinfo=timezone.utc)


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
    return TechnicalV1EvaluationRepository(db=fake_db)


# ---------------------------------------------------------------------------
# Ortak test verisi
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_T_SESSION_DATE = "2026-09-09"
_SYMBOL = "AKBNK"


def _evaluation_id() -> str:
    return compute_evaluation_id(_PROTOCOL_VERSION, _T_SESSION_DATE, _SYMBOL)


def _make_summary(attempt_number: int) -> AttemptSummary:
    return AttemptSummary(
        attempt_number=attempt_number,
        attempt_id=f"{'a' if attempt_number == 1 else 'b'}" * 64,
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NO_RESULT,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )


def _make_final_evaluation(anomaly_codes=frozenset()) -> FinalEvaluation:
    return FinalEvaluation(
        evaluation_id=_evaluation_id(),
        protocol_version=_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_SYMBOL,
        protocol_sha256="a" * 64,
        methodology_git_commit="c1f0d439d40a709d55007bd8ff34b4a8b2347f95",
        freeze_manifest_sha256="b" * 64,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        E1_date="2026-09-10",
        formal_cutoff_timestamp="2026-09-10T06:45:00+00:00",
        capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
        evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
        technical_observation_eligible=False,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=_make_summary(1),
        attempt_2_summary=_make_summary(2),
        orchestration_anomaly_codes=anomaly_codes,
    )


# ---------------------------------------------------------------------------
# create() -- ilk yaratım / idempotent yeniden kullanım / gerçek çakışma
# ---------------------------------------------------------------------------


def test_first_create_is_created(repo):
    evaluation = _make_final_evaluation()
    assert repo.create(evaluation) == FinalEvaluationOutcome.CREATED


def test_second_identical_create_is_idempotent_reuse(repo):
    evaluation = _make_final_evaluation()
    assert repo.create(evaluation) == FinalEvaluationOutcome.CREATED
    assert repo.create(evaluation) == FinalEvaluationOutcome.IDEMPOTENT_REUSE


def test_second_identical_create_does_not_write_or_mutate_stored_document(repo, fake_db):
    evaluation = _make_final_evaluation()
    repo.create(evaluation)
    stored_before = dict(fake_db.raw_store(COLLECTION)[evaluation.evaluation_id])

    repo.create(evaluation)
    stored_after = fake_db.raw_store(COLLECTION)[evaluation.evaluation_id]
    assert stored_after == stored_before


def test_same_evaluation_id_different_content_is_provenance_conflict(repo):
    evaluation_a = _make_final_evaluation()
    repo.create(evaluation_a)

    evaluation_b = _make_final_evaluation(
        anomaly_codes=frozenset({OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED})
    )
    # evaluation_id, protocol_version/T_session_date/symbol'den turetildigi
    # icin degismez -- ayni ID, FARKLI icerik (capture_status/anomaly vb.)
    assert evaluation_a.evaluation_id == evaluation_b.evaluation_id
    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation_b)


def test_same_evaluation_id_different_capture_status_is_provenance_conflict(repo):
    evaluation_a = _make_final_evaluation()
    repo.create(evaluation_a)

    evaluation_b = replace(evaluation_a, capture_status=CaptureStatus.INFRASTRUCTURE_BLOCKED)
    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation_b)


def test_create_never_calls_set_update_or_add(repo, fake_db, monkeypatch):
    evaluation = _make_final_evaluation()

    doc_ref = fake_db.collection(COLLECTION).document(evaluation.evaluation_id)
    for forbidden_method in ("set", "update", "add", "delete"):
        assert not hasattr(doc_ref, forbidden_method) or True  # sahte zaten bu metodlari HIC tanimlamiyor

    # Sahte `_FakeDocRef` yalnizca `get`/`create` tanimlar -- production
    # kodu baska bir metod cagirmaya calisirsa AttributeError firlar.
    assert set(dir(doc_ref)) & {"set", "update", "add", "delete"} == set()
    repo.create(evaluation)


# ---------------------------------------------------------------------------
# Tamper senaryolari -- varolan dokuman uzerinde (HATA 12N2B2 section 18-23)
# ---------------------------------------------------------------------------


def _seed_existing(fake_db, evaluation: FinalEvaluation) -> dict:
    """Repository BYPASS edilerek, ham store'a dogrudan bir doc yazar --
    boylece "onceden var olan (belki bozulmus) doküman" senaryolari
    kurulabilir."""
    store = fake_db.raw_store(COLLECTION)
    fields = evaluation.to_document_fields()
    store[evaluation.evaluation_id] = fields
    return fields


def test_existing_document_with_stale_hash_after_body_tamper_is_conflict(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)
    stale_hash = stored["record_content_sha256"]

    tampered = dict(stored)
    tampered["attempt_history_complete"] = True  # icerik degisti
    tampered["record_content_sha256"] = stale_hash  # hash ESKI kaldi
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_existing_document_with_hash_replaced_by_another_valid_hash_is_conflict(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    other_valid_hash = content_sha256({"unrelated": "payload"})
    tampered = dict(stored)
    tampered["record_content_sha256"] = other_valid_hash
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_existing_document_with_extra_unexpected_field_is_conflict(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    tampered["unexpected_extra_field"] = "sneaky"
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


# ---------------------------------------------------------------------------
# HATA 12N2B2-F -- ADVERSARIAL "hash-consistent ama kanonik DEGIL" senaryolari.
#
# Yukaridaki testler, tamper YAPILIP hash'in ESKI/stale KALDIGI (veya baska
# bir gecerli hash ile DEGISTIRILDIGI) durumlari kapsar -- bunlarin hepsi
# HAM ICERIK HASH KONTROLUNDE (adim 2) yakalanir. Asagidaki testler ise
# DAHA GUCLU bir saldirgan modelini kapsar: saldirgan/bozuk bir yazici
# gövdeyi degistirir VE `record_content_sha256`'yi o DEGISTIRILMIS govde
# uzerinden DOGRU sekilde yeniden hesaplar -- yani ham hash kontrolu
# GECER. Bu durumda YALNIZCA yeni "tam ham sema roundtrip" kontrolu
# (`canonical_reconstructed == raw_fields`) bu tahribati yakalayabilir.
# ---------------------------------------------------------------------------


def _rehash(content_fields: dict) -> str:
    """Verilen (record_content_sha256 HARIC) icerik alanlari uzerinden
    KANONIK/DOGRU record_content_sha256'yi yeniden hesaplar -- testlerde
    "saldirgan kendi hash'ini dogru hesapladi" senaryosunu simule etmek
    icin kullanilir."""
    return content_sha256({k: v for k, v in content_fields.items() if k != "record_content_sha256"})


def test_top_level_extra_field_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    """Section 5: ham hash icsel olarak GECERLI (saldirgan dogru
    hesapladi), ama kanonik semada olmayan bir ust-duzey alan var --
    yalnizca YENI roundtrip kontrolu bunu yakalayabilir."""
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    tampered["unexpected_field"] = "x"
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(evaluation.evaluation_id)


def test_nested_extra_field_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    """Section 6: `attempt_1_summary` icine beklenmeyen bir IC ICE
    (nested) alan eklenir, UST-DUZEY hash DOGRU sekilde yeniden
    hesaplanir -- nested normalizasyon da yasaklanmalidir."""
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    tampered["attempt_1_summary"] = {**tampered["attempt_1_summary"], "unexpected_nested_field": "x"}
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_missing_top_level_nullable_key_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    """Section 7: `to_document_fields()` `selected_attempt_id`'yi HER
    ZAMAN acikca (deger `None` olsa bile) bir anahtar olarak yayinlar.
    Bu anahtar ham dokumandan TAMAMEN silinip ust-duzey hash DOGRU
    yeniden hesaplanirsa, "anahtar eksik" ile "anahtar: null" ayni
    SAYILMAMALIDIR."""
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)
    assert "selected_attempt_id" in stored
    assert stored["selected_attempt_id"] is None

    tampered = dict(stored)
    del tampered["selected_attempt_id"]
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_missing_nested_nullable_key_with_correctly_recomputed_hash_is_conflict(repo, fake_db):
    """Section 8: `AttemptSummary.to_content_fields()` `native_reason_
    code`'u HER ZAMAN acikca (deger `None` olsa bile) yayinlar. Bu ic ice
    (nested) anahtar tamamen silinip UST-DUZEY hash DOGRU yeniden
    hesaplanirsa, yeniden kuruluş bunu SESSIZCE `None`'a normalize
    ETMEMELIDIR."""
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)
    assert "native_reason_code" in stored["attempt_1_summary"]
    assert stored["attempt_1_summary"]["native_reason_code"] is None

    tampered = dict(stored)
    nested = dict(tampered["attempt_1_summary"])
    del nested["native_reason_code"]
    tampered["attempt_1_summary"] = nested
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_duplicate_anomaly_codes_are_not_silently_deduplicated(repo, fake_db):
    """Section 9: GERCEK bir normalizasyon yolu -- `orchestration_
    anomaly_codes` yeniden kuruluş sirasinda bir `frozenset` uzerinden
    gecer (`FinalEvaluation.from_document_fields`), bu da ham listede
    var olan YINELENEN (duplicate) girdileri SESSIZCE tekillestirir.
    Ham listede iki KEZ tekrar eden ayni kod + DOGRU yeniden hesaplanmis
    bir ust-duzey hash ile, eski (roundtrip-oncesi) kontrol bunu
    YAKALAYAMAZDI -- yeni tam-sema roundtrip kontrolu YAKALAR (yeniden
    kurulan modelin sirali/tekil listesi, ham dokumanin 2 elemanli
    listesiyle ARTIK ESLESMEZ)."""
    evaluation = _make_final_evaluation(
        anomaly_codes=frozenset({OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED})
    )
    stored = _seed_existing(fake_db, evaluation)
    assert stored["orchestration_anomaly_codes"] == ["ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED"]

    tampered = dict(stored)
    tampered["orchestration_anomaly_codes"] = [
        "ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED",
        "ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED",
    ]
    tampered["record_content_sha256"] = _rehash(tampered)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


@pytest.mark.parametrize(
    "malformed_hash",
    [
        None,
        "",
        "a" * 63,
        "A" * 64,
        "g" * 64,
        "a" * 65,
        12345,
    ],
    ids=["missing_none", "empty", "63_chars", "uppercase", "non_hex", "65_chars", "not_a_string"],
)
def test_existing_document_with_malformed_stored_hash_is_conflict_not_raw_valueerror(repo, fake_db, malformed_hash):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    if malformed_hash is None:
        del tampered["record_content_sha256"]
    else:
        tampered["record_content_sha256"] = malformed_hash
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_existing_document_with_wrong_document_id_vs_content_identity_is_conflict(repo, fake_db):
    evaluation = _make_final_evaluation()
    other_symbol_evaluation = _make_final_evaluation()
    other_fields = replace(other_symbol_evaluation, symbol="GARAN").to_document_fields()
    # Store, "evaluation.evaluation_id" anahtari altinda AMA GARAN icerigi
    # tasiyan bir dokuman icerecek sekilde bozuluyor (wrong-wiring simulasyonu).
    store = fake_db.raw_store(COLLECTION)
    store[evaluation.evaluation_id] = other_fields

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


def test_existing_document_hash_consistent_but_semantically_invalid_is_conflict(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    tampered["capture_status"] = "NOT_A_REAL_CAPTURE_STATUS_VALUE"
    # hash'i yeni (tutarli) icerige gore yeniden hesapla -- boylece raw-hash
    # kontrolu GECER, ama semantik yeniden kurulus (`CaptureStatus(...)`)
    # BASARISIZ OLUR.
    content_only = {k: v for k, v in tampered.items() if k != "record_content_sha256"}
    tampered["record_content_sha256"] = content_sha256(content_only)
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.create(evaluation)


# ---------------------------------------------------------------------------
# get_verified()
# ---------------------------------------------------------------------------


def test_get_verified_returns_none_for_absent_document(repo):
    assert repo.get_verified(_evaluation_id()) is None


def test_get_verified_returns_trusted_envelope_after_create(repo):
    evaluation = _make_final_evaluation()
    repo.create(evaluation)

    persisted = repo.get_verified(evaluation.evaluation_id)
    assert isinstance(persisted, PersistedFinalEvaluation)
    assert persisted.evaluation == evaluation
    assert persisted.create_time is not None
    assert persisted.create_time.tzinfo is not None


def test_get_verified_raises_provenance_conflict_for_tampered_document(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)

    tampered = dict(stored)
    tampered["attempt_history_complete"] = not tampered["attempt_history_complete"]
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(evaluation.evaluation_id)


def test_get_verified_does_not_leak_raw_valueerror_on_malformed_hash(repo, fake_db):
    evaluation = _make_final_evaluation()
    stored = _seed_existing(fake_db, evaluation)
    tampered = dict(stored)
    tampered["record_content_sha256"] = "not-hex-at-all"
    fake_db.raw_store(COLLECTION)[evaluation.evaluation_id] = tampered

    with pytest.raises(ProvenanceConflictError):
        repo.get_verified(evaluation.evaluation_id)


def test_get_verified_never_exposes_create_time_inside_document_fields(repo):
    evaluation = _make_final_evaluation()
    repo.create(evaluation)
    persisted = repo.get_verified(evaluation.evaluation_id)

    assert "create_time" not in persisted.evaluation.to_document_fields()
    assert "finalized_at" not in persisted.evaluation.to_document_fields()
    assert "server_create_time" not in persisted.evaluation.to_document_fields()


# ---------------------------------------------------------------------------
# Sabit dogrulama: candidate'in kendi hash'i her zaman gecerlidir (regresyon)
# ---------------------------------------------------------------------------


def test_content_hash_regression_matches_record_content_sha256():
    evaluation = _make_final_evaluation()
    content_only = evaluation.to_document_fields()
    stored_hash = content_only.pop("record_content_sha256")
    assert content_sha256(content_only) == evaluation.record_content_sha256 == stored_hash


def test_final_evaluation_round_trip_is_exact_and_hash_preserving():
    evaluation = _make_final_evaluation(
        anomaly_codes=frozenset({OrchestrationAnomalyCode.ATTEMPT_2_EXECUTED_DESPITE_NOT_REQUIRED})
    )
    doc1 = evaluation.to_document_fields()
    reconstructed = FinalEvaluation.from_document_fields(
        {k: v for k, v in doc1.items() if k != "record_content_sha256"}
    )
    doc2 = reconstructed.to_document_fields()

    assert doc1 == doc2
    assert reconstructed.record_content_sha256 == evaluation.record_content_sha256
    assert reconstructed == evaluation


# ---------------------------------------------------------------------------
# Candidate kendi kimligiyle tutarsizsa -- hicbir I/O yapilmadan reddedilir
# ---------------------------------------------------------------------------


def test_create_rejects_candidate_with_self_inconsistent_evaluation_id(repo, fake_db):
    evaluation = _make_final_evaluation()
    inconsistent = replace(evaluation, evaluation_id="d" * 64)

    with pytest.raises(ProvenanceConflictError):
        repo.create(inconsistent)

    # Hicbir dokuman yazilmadi -- adayin kendi kimligi dogrulanmadan ONCE
    # Firestore'a HIC DOKUNULMADI.
    assert fake_db.raw_store(COLLECTION) == {}


def test_repository_does_not_import_selector_or_object_store_or_attempt_repository():
    module_names = set(vars(repo_module))
    forbidden_names = {"select_final_evaluation", "EvidenceObjectStore", "TechnicalV1AttemptRepository"}
    assert forbidden_names.isdisjoint(module_names)

    forbidden_modules = {
        "app.research.final_evaluation_selector",
        "app.research.evidence_object_store",
        "app.repositories.technical_v1_attempt_repository",
    }
    for name, value in vars(repo_module).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"
