"""HATA 12N2A — `TechnicalV1AttemptRepository`'nin (CLAIM-ONCE modeli:
lease/heartbeat/takeover/generation fencing YOK) KENDİ (production)
metodlarını, gerçek Firestore/ağ olmadan, doğrudan çalıştıran testler.

Desen `test_new_opportunity_notification_repository.py` ile AYNI: gerçek
`Firestore` istemcisini minimal, sözleşme-uyumlu bir sahteyle DEĞİŞTİRİYORUZ
(bu repository `db` parametresini constructor'da doğrudan enjekte
edebildiğinden monkeypatch bile gerekmez), `firestore.transactional`
yalnızca identity-wrapper'a monkeypatch'lenir (gerçek Firestore transaction
protokolü ağ gerektirir) -- decorator'ın SARDIĞI production fonksiyonunun
GÖVDESİ (claim/result kimlik karşılaştırması, content-hash tamper/conflict
kararları) AYNEN çalışır.
"""

from dataclasses import replace

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_attempt_repository as repo_module
from app.research.attempt_models import (
    AttemptClaim,
    AttemptClaimMissingError,
    AttemptResult,
    AttemptResultClassification,
    ClaimOutcome,
    GateCheckResult,
    PublishOutcome,
)
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id
from app.research.evidence_models import ProvenanceConflictError


# ---------------------------------------------------------------------------
# Sahte (fake) Firestore harness -- test_new_opportunity_notification_
# repository.py ile AYNI desen, artı `transaction.create()` destegi.
# ---------------------------------------------------------------------------


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

    def get(self, transaction=None):
        return _FakeDocSnapshot(self._store.get(self._key))

    def create(self, data):
        if self._key in self._store:
            raise AlreadyExists(f"document already exists: {self._key}")
        self._store[self._key] = dict(data)


class _FakeTransaction:
    """Gerçek `google.cloud.firestore.Transaction`'ın yalnız repository'nin
    kullandığı metodu (`create`) taklit eder -- retry/commit protokolü
    olmadan, doğrudan store üzerinde çalışır."""

    def create(self, doc_ref, data):
        if doc_ref._key in doc_ref._store:
            raise AlreadyExists(f"document already exists: {doc_ref._key}")
        doc_ref._store[doc_ref._key] = dict(data)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id)


class _FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}
        self.transaction_call_count = 0

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))

    def transaction(self):
        self.transaction_call_count += 1
        return _FakeTransaction()

    def raw_store(self, name):
        return self._collections.setdefault(name, {})


@pytest.fixture
def fake_db():
    return _FakeFirestoreClient()


@pytest.fixture
def repo(monkeypatch, fake_db):
    # Gerçek Firestore transaction protokolü ağ/backend gerektirir --
    # decorator'ı identity-wrapper'a indirgiyoruz, ama SARDIĞI production
    # fonksiyonunun gövdesi (claim/result kimlik karşılaştırması, content-
    # hash tamper/conflict kararları) AYNEN çalışır.
    monkeypatch.setattr(repo_module.firestore, "transactional", lambda f: f)
    return repo_module.TechnicalV1AttemptRepository(db=fake_db)


# ---------------------------------------------------------------------------
# Ortak test kimlikleri
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_T_SESSION_DATE = "2026-09-09"
_SYMBOL = "AKBNK"

LOCK_A = "a" * 64
LOCK_B = "b" * 64


def _evaluation_id() -> str:
    return compute_evaluation_id(_PROTOCOL_VERSION, _T_SESSION_DATE, _SYMBOL)


def _make_claim(
    attempt_number: int = 1, claimed_by_runtime: str = "cloud-run-rev-x", activation_lock_id: str = LOCK_A
) -> AttemptClaim:
    eval_id = _evaluation_id()
    attempt_id = compute_attempt_id(eval_id, attempt_number)
    return AttemptClaim(
        attempt_id=attempt_id,
        evaluation_id=eval_id,
        attempt_number=attempt_number,
        protocol_version=_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_SYMBOL,
        claimed_by_runtime=claimed_by_runtime,
        activation_lock_id=activation_lock_id,
    )


def _make_result(
    attempt_number: int = 1,
    result_classification: AttemptResultClassification = AttemptResultClassification.FAILED,
    native_reason_code: str | None = "PROVIDER_EXHAUSTED",
    activation_lock_id: str = LOCK_A,
) -> AttemptResult:
    eval_id = _evaluation_id()
    attempt_id = compute_attempt_id(eval_id, attempt_number)
    return AttemptResult(
        attempt_id=attempt_id,
        evaluation_id=eval_id,
        attempt_number=attempt_number,
        protocol_version=_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_SYMBOL,
        scheduled_for="2026-09-09T08:00:00+03:00",
        runtime_fingerprint="ai-investment-backend-00030-xyz",
        activation_lock_id=activation_lock_id,
        config_gate_result=GateCheckResult.PASS,
        methodology_gate_result=GateCheckResult.PASS,
        runtime_gate_result=GateCheckResult.PASS,
        universe_gate_result=GateCheckResult.PASS,
        result_classification=result_classification,
        native_reason_code=native_reason_code,
        started_at="2026-09-09T08:00:00+03:00",
        finished_at="2026-09-09T08:00:05+03:00",
    )


# ---------------------------------------------------------------------------
# ID golden testleri (HATA 12N2A section 5/32)
# ---------------------------------------------------------------------------

_GOLDEN_EVALUATION_ID = "7529fa9d86d93579f5e7962f1a63743186ec41674f43f85021ee35363024cd2b"
_GOLDEN_ATTEMPT_ID_1 = "bd4d075bcc0232a29628d95589cd8f8367a1da7dce3630961b41bfa0910b46ea"
_GOLDEN_ATTEMPT_ID_2 = "8b43d7503a3ac8700b9a02efc1e17fc8204216ed7655a2f574f467e094e74597"


def test_golden_evaluation_id():
    assert _evaluation_id() == _GOLDEN_EVALUATION_ID


def test_golden_attempt_ids():
    eval_id = _evaluation_id()
    assert compute_attempt_id(eval_id, 1) == _GOLDEN_ATTEMPT_ID_1
    assert compute_attempt_id(eval_id, 2) == _GOLDEN_ATTEMPT_ID_2


def test_evaluation_id_stable_regardless_of_dict_construction_order():
    a = compute_evaluation_id(_PROTOCOL_VERSION, _T_SESSION_DATE, _SYMBOL)
    b = compute_evaluation_id(symbol=_SYMBOL, t_session_date=_T_SESSION_DATE, protocol_version=_PROTOCOL_VERSION)
    assert a == b == _GOLDEN_EVALUATION_ID


@pytest.mark.parametrize(
    "changed_kwargs",
    [
        {"symbol": "GARAN"},
        {"t_session_date": "2026-09-10"},
        {"protocol_version": "TECHNICAL_V1_PROTOCOL_V2"},
    ],
)
def test_evaluation_id_changes_with_any_identity_field(changed_kwargs):
    base = dict(protocol_version=_PROTOCOL_VERSION, t_session_date=_T_SESSION_DATE, symbol=_SYMBOL)
    base.update(changed_kwargs)
    assert compute_evaluation_id(**base) != _GOLDEN_EVALUATION_ID


def test_attempt_id_changes_with_attempt_number():
    eval_id = _evaluation_id()
    assert compute_attempt_id(eval_id, 1) != compute_attempt_id(eval_id, 2)


def test_attempt_id_changes_with_evaluation_id():
    other_eval_id = compute_evaluation_id(_PROTOCOL_VERSION, _T_SESSION_DATE, "GARAN")
    assert compute_attempt_id(_evaluation_id(), 1) != compute_attempt_id(other_eval_id, 1)


# ---------------------------------------------------------------------------
# Claim testleri (HATA 12N2A section 28)
# ---------------------------------------------------------------------------


def test_A_first_claim_is_claimed(repo):
    outcome = repo.claim_attempt(_make_claim())
    assert outcome == ClaimOutcome.CLAIMED


def test_B_duplicate_same_identity_is_already_claimed(repo):
    claim = _make_claim()
    assert repo.claim_attempt(claim) == ClaimOutcome.CLAIMED
    # Farkli bir runtime'dan AYNI mantiksal identity ile "redelivery" --
    # section 9: claimed_by_runtime farkli olmasi conflict SAYILMAZ.
    duplicate_claim = replace(claim, claimed_by_runtime="cloud-run-rev-y")
    assert repo.claim_attempt(duplicate_claim) == ClaimOutcome.ALREADY_CLAIMED


def test_C_duplicate_does_not_mutate_claim(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    stored_before = dict(fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim.attempt_id])

    duplicate_claim = replace(claim, claimed_by_runtime="cloud-run-rev-y")
    repo.claim_attempt(duplicate_claim)
    stored_after = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim.attempt_id]

    assert stored_after == stored_before  # ilk claimant'in claimed_by_runtime'i KORUNDU


def test_D_existing_claim_with_inconsistent_identity_is_provenance_conflict(repo, fake_db):
    claim = _make_claim()
    # Repository'nin KENDI API'sini BYPASS ederek, ayni attempt_id altinda
    # BOZUK/yanlis-wiring bir kayit simule ediyoruz (ornegin farkli bir
    # symbol tasiyan bir dokuman).
    store = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)
    corrupted = claim.to_document_fields()
    corrupted["symbol"] = "GARAN"  # attempt_id ile TUTARSIZ
    store[claim.attempt_id] = corrupted

    with pytest.raises(ProvenanceConflictError):
        repo.claim_attempt(claim)


def test_E_attempt_1_and_2_have_separate_documents(repo, fake_db):
    claim1 = _make_claim(attempt_number=1)
    claim2 = _make_claim(attempt_number=2)
    assert claim1.attempt_id != claim2.attempt_id

    repo.claim_attempt(claim1)
    repo.claim_attempt(claim2)

    store = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)
    assert claim1.attempt_id in store
    assert claim2.attempt_id in store
    assert store[claim1.attempt_id]["attempt_number"] == 1
    assert store[claim2.attempt_id]["attempt_number"] == 2


def test_F_claim_document_has_no_lease_heartbeat_or_generation_fields(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    stored = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim.attempt_id]

    forbidden_keys = {
        "status",
        "lease",
        "lease_expires_at",
        "heartbeat",
        "generation",
        "lease_generation",
        "claim_token",
        "result",
        "technical_score",
        "evidence_hashes",
        "provider_output",
    }
    assert forbidden_keys.isdisjoint(stored.keys())
    assert set(stored.keys()) == {
        "attempt_id",
        "evaluation_id",
        "attempt_number",
        "protocol_version",
        "T_session_date",
        "symbol",
        "claimed_by_runtime",
        "activation_lock_id",
    }


# ---------------------------------------------------------------------------
# Activation-lock binding testleri (HATA 12N3C2-B2-C section 11/12/26)
# ---------------------------------------------------------------------------


def test_G_duplicate_claim_after_redeploy_under_different_lock_is_already_claimed(repo, fake_db):
    """Section 26 (ZORUNLU): attempt_id=X, lock=A ile claim edilir. Sonra
    AYNI attempt slotu icin, MESRU bir redeploy sonrasi FARKLI bir
    activation_lock_id (B) tasiyan bir claim_attempt() cagrisi yapilir --
    bu YENI bir claim degil, normal (ilk-claimant-kazanir) bir
    redelivery'dir: ALREADY_CLAIMED doner, saklanan claim HALA lock A'yi
    tasir (overwrite/conflict YOK, salt B tasidigi icin)."""
    claim_lock_a = _make_claim(activation_lock_id=LOCK_A)
    assert repo.claim_attempt(claim_lock_a) == ClaimOutcome.CLAIMED

    claim_lock_b = replace(claim_lock_a, activation_lock_id=LOCK_B)
    assert repo.claim_attempt(claim_lock_b) == ClaimOutcome.ALREADY_CLAIMED

    stored = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim_lock_a.attempt_id]
    assert stored["activation_lock_id"] == LOCK_A  # HICBIR ZAMAN B'ye yeniden yazilmadi


def test_H_duplicate_claim_after_redeploy_does_not_mutate_stored_document(repo, fake_db):
    claim_lock_a = _make_claim(activation_lock_id=LOCK_A)
    repo.claim_attempt(claim_lock_a)
    stored_before = dict(fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim_lock_a.attempt_id])

    claim_lock_b = replace(claim_lock_a, activation_lock_id=LOCK_B)
    repo.claim_attempt(claim_lock_b)
    stored_after = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim_lock_a.attempt_id]

    assert stored_after == stored_before


def test_I_claimed_plus_no_result_retains_activation_lock_provenance(repo):
    """Section 31 (ZORUNLU): yalnizca claim persist edilir (result YOK) --
    bu, kalici, gecerli CLAIMED+NO_RESULT durumudur. Reconstruction, hangi
    immutable aktivasyon yetkilendirmesinin bu sahiplini kurdugunu
    (activation_lock_id) KORUR -- crash/OOM sonrasi bile provenance
    kaybolmaz."""
    claim = _make_claim(activation_lock_id=LOCK_A)
    repo.claim_attempt(claim)

    reloaded = repo.get_claim(claim.attempt_id)
    assert reloaded is not None
    assert reloaded.activation_lock_id == LOCK_A
    assert repo.get_result(claim.attempt_id) is None


# ---------------------------------------------------------------------------
# Result testleri (HATA 12N2A section 29)
# ---------------------------------------------------------------------------


def test_A_publish_result_with_valid_claim_is_created(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)
    result = _make_result()

    outcome = repo.publish_result(result)
    assert outcome == PublishOutcome.CREATED


def test_B_publish_same_exact_result_twice_is_idempotent_reuse(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)
    result = _make_result()

    assert repo.publish_result(result) == PublishOutcome.CREATED
    assert repo.publish_result(result) == PublishOutcome.IDEMPOTENT_REUSE


def test_C_same_attempt_id_different_content_is_provenance_conflict(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)
    result_a = _make_result(native_reason_code="PROVIDER_EXHAUSTED")
    repo.publish_result(result_a)

    result_b = replace(result_a, native_reason_code="DIFFERENT_REASON")
    with pytest.raises(ProvenanceConflictError):
        repo.publish_result(result_b)


def test_D_publish_result_without_claim_raises_attempt_claim_missing_error(repo):
    result = _make_result()  # HICBIR claim_attempt() cagrisi YAPILMADI
    with pytest.raises(AttemptClaimMissingError):
        repo.publish_result(result)


def test_E_claim_remains_immutable_after_result_published(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    stored_claim_before = dict(fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim.attempt_id])

    repo.publish_result(_make_result())

    stored_claim_after = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)[claim.attempt_id]
    assert stored_claim_after == stored_claim_before


def test_F_claim_with_no_result_is_valid_readable_state(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)

    assert repo.get_claim(claim.attempt_id) == claim
    assert repo.get_result(claim.attempt_id) is None  # AUDIT_INCOMPLETE aday durumu -- gecerli, kalici


def test_G_failed_terminal_result_distinct_from_no_result(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)

    assert repo.get_result(claim.attempt_id) is None

    failed_result = _make_result(result_classification=AttemptResultClassification.FAILED)
    repo.publish_result(failed_result)

    stored = repo.get_result(claim.attempt_id)
    assert stored is not None
    assert stored.result_classification == AttemptResultClassification.FAILED


def test_H_blocked_result_can_be_terminal(repo):
    claim = _make_claim()
    repo.claim_attempt(claim)

    blocked_result = _make_result(
        result_classification=AttemptResultClassification.BLOCKED_CONFIG_DRIFT,
        native_reason_code="SCORING_CONFIG_HASH_MISMATCH",
    )
    outcome = repo.publish_result(blocked_result)
    assert outcome == PublishOutcome.CREATED

    stored = repo.get_result(claim.attempt_id)
    assert stored.result_classification == AttemptResultClassification.BLOCKED_CONFIG_DRIFT
    assert stored.native_reason_code == "SCORING_CONFIG_HASH_MISMATCH"


def test_I_server_metadata_not_included_in_content_hash(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    result = _make_result()
    repo.publish_result(result)

    stored = fake_db.raw_store(repo_module.ATTEMPT_RESULTS_COLLECTION)[result.attempt_id]
    assert "create_time" not in stored
    assert "update_time" not in stored
    assert "finalized_at" not in stored

    # Ayrica: `to_content_fields()`'in KENDISI de bu anahtarlari hic
    # icermez -- yapisal olarak (hash'e girme sansi bile YOK).
    assert "create_time" not in result.to_content_fields()
    assert "update_time" not in result.to_content_fields()


# ---------------------------------------------------------------------------
# Claim/result activation-lock iliskisi (HATA 12N3C2-B2-C section 13/14/27/28)
# ---------------------------------------------------------------------------


def test_J_claim_and_result_same_lock_publishes_normally(repo):
    claim = _make_claim(activation_lock_id=LOCK_A)
    repo.claim_attempt(claim)
    result = _make_result(activation_lock_id=LOCK_A)

    assert repo.publish_result(result) == PublishOutcome.CREATED
    assert repo.get_result(claim.attempt_id).activation_lock_id == LOCK_A


def test_K_claim_and_result_different_lock_is_rejected_before_persistence(repo, fake_db):
    claim = _make_claim(activation_lock_id=LOCK_A)
    repo.claim_attempt(claim)
    mismatched_result = _make_result(activation_lock_id=LOCK_B)

    with pytest.raises(ProvenanceConflictError):
        repo.publish_result(mismatched_result)

    # Hicbir result dokumani yazilmadi.
    assert mismatched_result.attempt_id not in fake_db.raw_store(repo_module.ATTEMPT_RESULTS_COLLECTION)


def test_L_attempt1_and_attempt2_may_use_different_locks(repo):
    """Section 17/30: AYNI evaluation icindeki attempt1/attempt2 FARKLI
    activation_lock_id'ler kullanabilir (mesru redeploy) -- bu asla
    reddedilmemeli, cunku her attempt kendi claim/result ciftiyle BAGIMSIZ
    dogrulanir."""
    claim1 = _make_claim(attempt_number=1, activation_lock_id=LOCK_A)
    repo.claim_attempt(claim1)
    result1 = _make_result(attempt_number=1, activation_lock_id=LOCK_A)
    assert repo.publish_result(result1) == PublishOutcome.CREATED

    claim2 = _make_claim(attempt_number=2, activation_lock_id=LOCK_B)
    repo.claim_attempt(claim2)
    result2 = _make_result(attempt_number=2, activation_lock_id=LOCK_B)
    assert repo.publish_result(result2) == PublishOutcome.CREATED

    assert repo.get_result(claim1.attempt_id).activation_lock_id == LOCK_A
    assert repo.get_result(claim2.attempt_id).activation_lock_id == LOCK_B


# ---------------------------------------------------------------------------
# Katı ham şema (HATA 12N3C2-B2-C section 32)
# ---------------------------------------------------------------------------


def test_M_stored_claim_document_missing_activation_lock_id_fails_reconstruction(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    store = fake_db.raw_store(repo_module.ATTEMPT_CLAIMS_COLLECTION)
    corrupted = dict(store[claim.attempt_id])
    del corrupted["activation_lock_id"]
    store[claim.attempt_id] = corrupted

    with pytest.raises(KeyError):
        repo.get_claim(claim.attempt_id)


def test_N_stored_result_document_missing_activation_lock_id_fails_reconstruction(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    result = _make_result()
    repo.publish_result(result)

    store = fake_db.raw_store(repo_module.ATTEMPT_RESULTS_COLLECTION)
    corrupted = dict(store[result.attempt_id])
    del corrupted["activation_lock_id"]
    store[result.attempt_id] = corrupted

    with pytest.raises(KeyError):
        repo.get_result(result.attempt_id)


# ---------------------------------------------------------------------------
# Transaction testi (HATA 12N2A section 30)
# ---------------------------------------------------------------------------


def test_publish_result_uses_a_firestore_transaction(repo, fake_db):
    claim = _make_claim()
    repo.claim_attempt(claim)
    assert fake_db.transaction_call_count == 0  # claim_attempt() transaction KULLANMAZ (yalnizca .create())

    repo.publish_result(_make_result())
    assert fake_db.transaction_call_count == 1

    # Idempotent ikinci cagri da AYNI transaction yolunu kullanir.
    repo.publish_result(_make_result())
    assert fake_db.transaction_call_count == 2


# ---------------------------------------------------------------------------
# Content-hash tamper testi (HATA 12N2A section 31)
# ---------------------------------------------------------------------------


def test_content_hash_tamper_is_detected_even_if_stale_hash_matches_candidate(repo, fake_db):
    """Depoda VAR olan bir result dokumaninin ICERIK alanlari (ornegin
    `native_reason_code`) depolama-katmani bir bug ile degistirilmis, AMA
    saklanan `attempt_result_content_sha256` stringi degismemis (ESKI/
    STALE kalmis) senaryosunu simule eder. Candidate'in KENDI hash'i o
    ESKI/stale string ile TESADUFEN ayni olsa BILE (bu test bunu KASITLI
    OLARAK kuruyor), repository ONCE VAR OLAN dokumanin kendi ICSEL
    tutarliligini (recompute == stored) kontrol eder ve bunu BASARISIZ
    bulup PROVENANCE_CONFLICT firlatir -- adaya hic bakmadan."""
    claim = _make_claim()
    repo.claim_attempt(claim)
    original_result = _make_result(native_reason_code="PROVIDER_EXHAUSTED")
    repo.publish_result(original_result)

    stale_hash = original_result.content_sha256  # tamper'dan ONCEKI (simdi STALE) hash

    store = fake_db.raw_store(repo_module.ATTEMPT_RESULTS_COLLECTION)
    tampered = dict(store[original_result.attempt_id])
    tampered["native_reason_code"] = "SILENTLY_CHANGED_BY_A_BUG"  # icerik degisti
    tampered["attempt_result_content_sha256"] = stale_hash  # ama hash ESKI kaldi (KASITLI tutarsizlik)
    store[original_result.attempt_id] = tampered

    # Candidate, KASITLI OLARAK ayni (stale) hash'i "tasiyacak" sekilde
    # DEGIL -- gercek/orijinal icerikle publish edilir; asil nokta
    # repository'nin VAR OLAN kaydin kendi ICSEL tutarliligini candidate'e
    # BAKMADAN ONCE kontrol ettigini kanitlamaktir.
    with pytest.raises(ProvenanceConflictError):
        repo.publish_result(original_result)
