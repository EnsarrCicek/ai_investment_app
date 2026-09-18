"""HATA 13E — `TechnicalV1SessionController`'ın KENDİ (production) akışını
doğrudan çalıştıran testler.

İki test grubu:
  A) Kontrolcü DİSPATCH mekaniği (tam 100 çağrı, sıra, per-sembol
     yalıtım, restart-safety) -- HAFİF sahte/stub 13B-D servisleriyle
     (section 59'un AÇIKÇA izin verdiği "fake/stub 13C execution
     service"), GERÇEK Firestore/provider olmadan.
  B) Manifest tamlık muhasebesi (section 21-27/40-45) -- GERÇEK
     `TechnicalV1EvaluationRepository`/`TechnicalV1SessionManifestRepository`
     ile, ama 100 `FinalEvaluation` kaydı doğrudan (100 sembolü GERÇEKTEN
     analiz etmeden) inşa edilerek -- manifest mantığı `FinalEvaluation`
     nesnelerinin NASIL üretildiğine değil, yalnızca onların İÇERİĞİNE/
     kimliğine bakar."""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories.technical_v1_evaluation_repository import (
    COLLECTION as EVALUATIONS_COLLECTION,
    TechnicalV1EvaluationRepository,
)
from app.repositories.technical_v1_session_manifest_repository import (
    COLLECTION as MANIFESTS_COLLECTION,
    SessionManifestOutcome,
    TechnicalV1SessionManifestRepository,
)
from app.repositories.technical_v1_session_run_repository import (
    COLLECTION as SESSION_RUNS_COLLECTION,
    TechnicalV1SessionRunRepository,
)
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id, compute_session_id
from app.research.evidence_models import ProvenanceConflictError
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    AttemptSummary,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalEvaluation,
    FinalizationRetryableError,
    ResultState,
    VerificationState,
)
from app.research.session_manifest import SessionAccountingStatus
from app.research.session_run import SessionRunStatus
from app.research.technical_v1_attempt2_orchestration import Attempt2Outcome, Attempt2Report
from app.research.technical_v1_attempt_execution import AttemptExecutionOutcome, AttemptExecutionReport
from app.research.technical_v1_attempt_schedule import formal_cutoff_utc
from app.research.technical_v1_finalization import FinalizationOutcome, FinalizationReport
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
from app.research.technical_v1_session_controller import (
    SessionScientificFacts,
    TechnicalV1SessionController,
)

LOCKED_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"
LOCKED_FREEZE_MANIFEST_SHA256 = "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"
_GIT_SHA = "730ef262f350b97b9290adddbd7c6a38c024729b"
_T_SESSION_DATE = "2026-08-24"


def _trusted_protocol():
    return load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)


def _facts() -> SessionScientificFacts:
    return SessionScientificFacts(
        methodology_git_commit=_GIT_SHA,
        freeze_manifest_sha256=LOCKED_FREEZE_MANIFEST_SHA256,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        E1_date="2026-08-25",
    )


# ---------------------------------------------------------------------------
# Sahte Firestore harness -- 13B/13C/13D testleriyle AYNI desen, artı
# create-only + tam-değiştirme (full-replace) DOKÜMAN türlerini AYNI
# fake client altında birleştirir (her koleksiyon adı kendi store'una
# sahiptir, çakışma YOK).
# ---------------------------------------------------------------------------

_SERVER_TIMESTAMP_SENTINEL = object()


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

    def get(self, transaction=None):
        return _FakeDocSnapshot(self._store.get(self._key), self._create_times.get(self._key))

    def create(self, data):
        if self._key in self._store:
            raise AlreadyExists(f"document already exists: {self._key}")
        self._store[self._key] = dict(data)
        self._create_times.setdefault(self._key, datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc))

    def set(self, payload, merge=False):
        if merge:
            raise AssertionError("production kodu merge=True KULLANMAMALI")
        resolved = dict(payload)
        for key, value in resolved.items():
            if value is _SERVER_TIMESTAMP_SENTINEL:
                resolved[key] = datetime.now(timezone.utc)
        self._store[self._key] = resolved


class _FakeTransaction:
    def create(self, doc_ref, data):
        doc_ref.create(data)


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

    def transaction(self):
        return _FakeTransaction()

    def raw_store(self, name):
        return self._collections.setdefault(name, {})


@pytest.fixture
def fake_db():
    return _FakeFirestoreClient()


@pytest.fixture(autouse=True)
def _fake_server_timestamp(monkeypatch):
    from app.repositories import technical_v1_session_run_repository as run_repo_module

    monkeypatch.setattr(run_repo_module.firestore, "SERVER_TIMESTAMP", _SERVER_TIMESTAMP_SENTINEL)


def _make_run_repo(fake_db) -> TechnicalV1SessionRunRepository:
    return TechnicalV1SessionRunRepository(db=fake_db)


def _make_manifest_repo(fake_db) -> TechnicalV1SessionManifestRepository:
    return TechnicalV1SessionManifestRepository(db=fake_db)


def _make_evaluation_repo(fake_db) -> TechnicalV1EvaluationRepository:
    return TechnicalV1EvaluationRepository(db=fake_db)


# ---------------------------------------------------------------------------
# Hafif sahte/stub 13B-D servisleri (section 59) -- kontrolcü DİSPATCH
# mekaniğini, gerçek yığından İZOLE test etmek için.
# ---------------------------------------------------------------------------


class _StubAttempt1Service:
    def __init__(self, outcome=AttemptExecutionOutcome.RESULT_PUBLISHED, fail_symbols=frozenset()):
        self.calls: list[str] = []
        self._outcome = outcome
        self._fail_symbols = fail_symbols

    def execute_attempt(self, *, activation_lock_id, protocol_version, T_session_date, symbol, attempt_number, now):
        self.calls.append(symbol)
        if symbol in self._fail_symbols:
            raise RuntimeError(f"simulated per-symbol crash: {symbol}")
        return AttemptExecutionReport(outcome=self._outcome)


class _StubAttempt2Orchestrator:
    def __init__(self, outcome=Attempt2Outcome.DISPATCHED, fail_symbols=frozenset()):
        self.calls: list[tuple[str, str]] = []
        self._outcome = outcome
        self._fail_symbols = fail_symbols

    def run_attempt2_if_required(self, context, *, activation_lock_id, now):
        self.calls.append((context.symbol, activation_lock_id))
        if context.symbol in self._fail_symbols:
            raise RuntimeError(f"simulated per-symbol crash: {context.symbol}")
        return Attempt2Report(outcome=self._outcome)


class _StubFinalizer:
    def __init__(self, outcome=FinalizationOutcome.CREATED, retryable_symbols=frozenset(), conflict_symbols=frozenset()):
        self.calls: list[str] = []
        self._outcome = outcome
        self._retryable_symbols = retryable_symbols
        self._conflict_symbols = conflict_symbols

    def finalize(self, context, *, now):
        self.calls.append(context.symbol)
        if context.symbol in self._retryable_symbols:
            raise FinalizationRetryableError("simulated transient failure")
        if context.symbol in self._conflict_symbols:
            raise ProvenanceConflictError("simulated per-evaluation conflict")
        return FinalizationReport(outcome=self._outcome)


def _make_controller(fake_db, *, attempt1=None, attempt2=None, finalizer=None) -> TechnicalV1SessionController:
    return TechnicalV1SessionController(
        trusted_protocol=_trusted_protocol(),
        attempt_execution_service=attempt1 or _StubAttempt1Service(),
        attempt2_orchestrator=attempt2 or _StubAttempt2Orchestrator(),
        finalizer=finalizer or _StubFinalizer(),
        session_run_repo=_make_run_repo(fake_db),
        session_manifest_repo=_make_manifest_repo(fake_db),
        evaluation_repo=_make_evaluation_repo(fake_db),
    )


NOW = datetime(2026, 8, 25, 6, 10, tzinfo=timezone.utc)  # 09:10 Europe/Istanbul


# ---------------------------------------------------------------------------
# section 33/34 -- attempt1 exact 100, frozen-only source
# ---------------------------------------------------------------------------


def test_frozen_universe_is_exactly_100_unique_symbols():
    protocol = _trusted_protocol()
    assert len(protocol.frozen_symbol_list) == 100
    assert len(set(protocol.frozen_symbol_list)) == 100


def test_attempt1_phase_dispatches_exactly_100_symbols_in_frozen_order(fake_db):
    stub = _StubAttempt1Service()
    controller = _make_controller(fake_db, attempt1=stub)

    report = controller.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )

    assert report.processed == 100
    assert stub.calls == list(_trusted_protocol().frozen_symbol_list)
    assert len(set(stub.calls)) == 100  # no duplicates, no omissions


def test_attempt1_phase_never_reads_live_universe_source():
    """section 34: kontrolcü modülü, canlı BIST100/AssetRepository/
    provider-keşfi ile ilgili HİÇBİR şeyi import ETMEZ -- kaynak
    incelemesiyle doğrudan doğrulanır."""
    import inspect

    import app.research.technical_v1_session_controller as module

    import_lines = [
        line.strip() for line in inspect.getsource(module).splitlines() if line.strip().startswith(("import ", "from "))
    ]
    forbidden = ("asset_repository", "bist_provider", "market_data", "yfinance", "bist100")
    for line in import_lines:
        lowered = line.lower()
        for name in forbidden:
            assert name not in lowered, f"yasaklı bağımlılık: {line!r}"


# ---------------------------------------------------------------------------
# section 35 -- per-symbol failure isolation
# ---------------------------------------------------------------------------


def test_attempt1_phase_one_symbol_crash_does_not_abort_the_other_99(fake_db):
    protocol = _trusted_protocol()
    crashing_symbol = protocol.frozen_symbol_list[42]
    stub = _StubAttempt1Service(fail_symbols=frozenset({crashing_symbol}))
    controller = _make_controller(fake_db, attempt1=stub)

    report = controller.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )

    assert report.processed == 100
    assert stub.calls == list(protocol.frozen_symbol_list)  # 100'ü de ÇAĞRILDI
    assert report.count("RESULT_PUBLISHED") == 99
    assert report.count("OPERATIONAL_ERROR") == 1
    failing_outcome = next(o for o in report.outcomes if o.symbol == crashing_symbol)
    assert failing_outcome.outcome == "OPERATIONAL_ERROR"
    assert failing_outcome.detail == "RuntimeError"


def test_attempt2_phase_one_symbol_crash_does_not_abort_the_other_99(fake_db):
    protocol = _trusted_protocol()
    crashing_symbol = protocol.frozen_symbol_list[7]
    stub = _StubAttempt2Orchestrator(fail_symbols=frozenset({crashing_symbol}))
    controller = _make_controller(fake_db, attempt2=stub)

    report = controller.run_attempt2_phase(
        activation_lock_id="b" * 64,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        facts=_facts(),
        now=NOW,
    )

    assert report.processed == 100
    assert report.count("DISPATCHED") == 99
    assert report.count("OPERATIONAL_ERROR") == 1


# ---------------------------------------------------------------------------
# section 36 -- attempt1 rerun / idempotency (dispatch shape only -- REAL
# claim-once semantics already proven in 13C's own suite)
# ---------------------------------------------------------------------------


def test_attempt1_phase_rerun_calls_execute_attempt_again_for_every_symbol(fake_db):
    """Kontrolcü KENDİSİ "zaten claim edildi" ÖN-kontrolü YAPMAZ (section 15)
    -- her geçişte 100 sembolün TAMAMI için `execute_attempt()`'i AYNEN
    çağırır, tekrarlı-çağrı GÜVENLİĞİNİ 13C'nin KENDİ claim-once
    semantiğine (ZATEN kilitli, burada DEĞİŞTİRİLMEDİ) bırakır."""
    stub = _StubAttempt1Service(outcome=AttemptExecutionOutcome.ALREADY_CLAIMED)
    controller = _make_controller(fake_db, attempt1=stub)

    first = controller.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )
    second = controller.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )

    assert first.processed == 100
    assert second.processed == 100
    assert len(stub.calls) == 200  # 2x100 -- KONTROLCÜ SEVİYESİNDE dedupe YOK
    assert second.count("ALREADY_CLAIMED") == 100  # 13C'nin claim-once'ı bu şekilde YANSIR


# ---------------------------------------------------------------------------
# section 37/38 -- attempt2 exact 100 decisions + different lock
# ---------------------------------------------------------------------------


def test_attempt2_phase_dispatches_exactly_100_decisions(fake_db):
    stub = _StubAttempt2Orchestrator()
    controller = _make_controller(fake_db, attempt2=stub)

    report = controller.run_attempt2_phase(
        activation_lock_id="b" * 64,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        facts=_facts(),
        now=NOW,
    )

    assert report.processed == 100
    assert len(stub.calls) == 100
    assert {symbol for symbol, _ in stub.calls} == set(_trusted_protocol().frozen_symbol_list)


def test_attempt2_phase_uses_the_supplied_lock_for_all_symbols_not_attempt1s(fake_db):
    attempt1_stub = _StubAttempt1Service()
    attempt2_stub = _StubAttempt2Orchestrator()
    controller = _make_controller(fake_db, attempt1=attempt1_stub, attempt2=attempt2_stub)

    lock_a = "a" * 64
    lock_b = "b" * 64
    controller.run_attempt1_phase(
        activation_lock_id=lock_a, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )
    controller.run_attempt2_phase(
        activation_lock_id=lock_b,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        facts=_facts(),
        now=NOW,
    )

    assert all(used_lock == lock_b for _, used_lock in attempt2_stub.calls)
    assert lock_a != lock_b


# ---------------------------------------------------------------------------
# section 39 -- finalize exact 100, one retryable does not abort
# ---------------------------------------------------------------------------


def test_finalization_phase_one_retryable_does_not_abort_the_other_99(fake_db):
    protocol = _trusted_protocol()
    retryable_symbol = protocol.frozen_symbol_list[13]
    stub = _StubFinalizer(retryable_symbols=frozenset({retryable_symbol}))
    controller = _make_controller(fake_db, finalizer=stub)

    report = controller.run_finalization_phase(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=_facts(), now=NOW
    )

    assert report.processed == 100
    assert report.count("CREATED") == 99
    assert report.count("RETRYABLE") == 1

    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    persisted_run = _make_run_repo(fake_db).get(session_id)
    retryable_evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, retryable_symbol)
    assert persisted_run.snapshot.retry_pending_evaluation_ids == (retryable_evaluation_id,)
    assert persisted_run.snapshot.status == SessionRunStatus.FINALIZATION_RETRY_PENDING


def test_finalization_phase_one_provenance_conflict_does_not_abort_the_other_99(fake_db):
    protocol = _trusted_protocol()
    conflicting_symbol = protocol.frozen_symbol_list[55]
    stub = _StubFinalizer(conflict_symbols=frozenset({conflicting_symbol}))
    controller = _make_controller(fake_db, finalizer=stub)

    report = controller.run_finalization_phase(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=_facts(), now=NOW
    )

    assert report.processed == 100
    assert report.count("PROVENANCE_CONFLICT") == 1

    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    persisted_run = _make_run_repo(fake_db).get(session_id)
    conflicting_evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, conflicting_symbol)
    assert persisted_run.snapshot.provenance_blocked_evaluation_ids == (conflicting_evaluation_id,)
    assert persisted_run.snapshot.status == SessionRunStatus.PROVENANCE_BLOCKED


def test_finalization_before_cutoff_is_recorded_operationally_not_fabricated(fake_db):
    stub = _StubFinalizer(outcome=FinalizationOutcome.NOT_YET_FINALIZABLE)
    controller = _make_controller(fake_db, finalizer=stub)

    report = controller.run_finalization_phase(
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        facts=_facts(),
        now=NOW,
    )

    assert report.count("NOT_YET_FINALIZABLE") == 100
    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    persisted_run = _make_run_repo(fake_db).get(session_id)
    assert persisted_run.snapshot.status == SessionRunStatus.INCOMPLETE
    assert _make_evaluation_repo(fake_db).get_verified(
        compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, "THYAO")
    ) is None


# ---------------------------------------------------------------------------
# section 46 -- SessionRun operational updates across phases
# ---------------------------------------------------------------------------


def test_session_run_reflects_incomplete_until_finalization_observes_issues(fake_db):
    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    run_repo = _make_run_repo(fake_db)
    assert run_repo.get(session_id) is None  # section 46: "initial state"

    controller = _make_controller(fake_db)
    controller.run_finalization_phase(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=_facts(), now=NOW
    )

    persisted = run_repo.get(session_id)
    assert persisted.snapshot.status == SessionRunStatus.INCOMPLETE
    assert persisted.snapshot.retry_pending_evaluation_ids == ()
    assert persisted.snapshot.provenance_blocked_evaluation_ids == ()


# ---------------------------------------------------------------------------
# section 47 -- restart / resume safety
# ---------------------------------------------------------------------------


def test_controller_restart_resumes_safely_with_a_fresh_instance(fake_db):
    stub_a = _StubAttempt1Service()
    controller_a = _make_controller(fake_db, attempt1=stub_a)
    controller_a.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )

    # "Süreç yeniden başlar" -- YENİ bir kontrolcü/servis örneği, ama AYNI
    # (kalıcı) repository'ler.
    stub_b = _StubAttempt1Service()
    controller_b = _make_controller(fake_db, attempt1=stub_b)
    report_b = controller_b.run_attempt1_phase(
        activation_lock_id="a" * 64, protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, now=NOW
    )

    assert report_b.processed == 100
    assert len(stub_b.calls) == 100  # YENİ örnek TÜM 100'ü yeniden dener -- 13C'nin claim-once'ı asıl güvenliği sağlar


# ---------------------------------------------------------------------------
# Manifest testleri (Grup B) -- GERÇEK evaluation/manifest repository'leri.
# ---------------------------------------------------------------------------


def _absent_summary(evaluation_id: str, attempt_number: int) -> AttemptSummary:
    return AttemptSummary(
        attempt_number=attempt_number,
        attempt_id=compute_attempt_id(evaluation_id, attempt_number),
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NOT_APPLICABLE,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )


def _make_minimal_final_evaluation(symbol: str, facts: SessionScientificFacts) -> FinalEvaluation:
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, symbol)
    return FinalEvaluation(
        evaluation_id=evaluation_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=symbol,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        methodology_git_commit=facts.methodology_git_commit,
        freeze_manifest_sha256=facts.freeze_manifest_sha256,
        engine_version=facts.engine_version,
        scoring_config_hash=facts.scoring_config_hash,
        E1_date=facts.E1_date,
        formal_cutoff_timestamp=formal_cutoff_utc(_T_SESSION_DATE).isoformat(),
        capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
        evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
        technical_observation_eligible=False,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=_absent_summary(evaluation_id, 1),
        attempt_2_summary=_absent_summary(evaluation_id, 2),
    )


def _seed_all_100_final_evaluations(fake_db, facts) -> None:
    repo = _make_evaluation_repo(fake_db)
    for symbol in _trusted_protocol().frozen_symbol_list:
        repo.create(_make_minimal_final_evaluation(symbol, facts))


# ---------------------------------------------------------------------------
# section 40 -- manifest, all 100 finals present
# ---------------------------------------------------------------------------


def test_manifest_complete_with_all_100_final_evaluations(fake_db):
    facts = _facts()
    _seed_all_100_final_evaluations(fake_db, facts)
    controller = _make_controller(fake_db)

    result = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    assert result.accounting.status == SessionAccountingStatus.COMPLETE
    assert result.accounting.expected_symbol_count == 100
    assert result.accounting.verified_count == 100
    assert result.manifest is not None
    assert result.manifest.expected_symbol_count == 100
    assert result.create_outcome == SessionManifestOutcome.CREATED

    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    assert _make_manifest_repo(fake_db).get_verified(session_id) is not None


# ---------------------------------------------------------------------------
# section 41 -- manifest, one missing
# ---------------------------------------------------------------------------


def test_manifest_missing_one_final_evaluation(fake_db):
    facts = _facts()
    protocol = _trusted_protocol()
    repo = _make_evaluation_repo(fake_db)
    missing_symbol = protocol.frozen_symbol_list[0]
    for symbol in protocol.frozen_symbol_list:
        if symbol == missing_symbol:
            continue
        repo.create(_make_minimal_final_evaluation(symbol, facts))

    controller = _make_controller(fake_db)
    result = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    assert result.accounting.status == SessionAccountingStatus.MISSING_FINAL_RECORDS
    assert result.accounting.verified_count == 99
    assert result.accounting.absent_count == 1
    assert result.manifest is None
    assert result.create_outcome is None
    session_id = compute_session_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE)
    assert _make_manifest_repo(fake_db).get_verified(session_id) is None


# ---------------------------------------------------------------------------
# section 42 -- foreign record does not affect denominator
# ---------------------------------------------------------------------------


def test_manifest_ignores_foreign_final_evaluation_outside_session(fake_db):
    facts = _facts()
    _seed_all_100_final_evaluations(fake_db, facts)

    # Yabancı (bu oturuma ait OLMAYAN, farklı bir T_session_date) bir kayıt.
    foreign = _make_minimal_final_evaluation("THYAO", facts)
    foreign_other_date = FinalEvaluation(
        evaluation_id=compute_evaluation_id(LOCKED_PROTOCOL_VERSION, "2026-08-25", "THYAO"),
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date="2026-08-25",
        symbol="THYAO",
        protocol_sha256=foreign.protocol_sha256,
        methodology_git_commit=foreign.methodology_git_commit,
        freeze_manifest_sha256=foreign.freeze_manifest_sha256,
        engine_version=foreign.engine_version,
        scoring_config_hash=foreign.scoring_config_hash,
        E1_date="2026-08-26",
        formal_cutoff_timestamp=formal_cutoff_utc("2026-08-25").isoformat(),
        capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
        evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
        technical_observation_eligible=False,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=foreign.attempt_1_summary,
        attempt_2_summary=foreign.attempt_2_summary,
    )
    _make_evaluation_repo(fake_db).create(foreign_other_date)

    controller = _make_controller(fake_db)
    result = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    assert result.accounting.status == SessionAccountingStatus.COMPLETE
    assert result.accounting.expected_symbol_count == 100
    assert result.manifest.expected_symbol_count == 100
    # Yabancı kayıt hash'e/denominatöre HİÇ girmedi.
    assert foreign_other_date.evaluation_id not in result.manifest.to_content_fields().get(
        "final_evaluation_records_sha256", ""
    )


# ---------------------------------------------------------------------------
# section 43 -- repository provenance conflict accounting
# ---------------------------------------------------------------------------


def test_manifest_repository_provenance_conflict_for_one_corrupted_record(fake_db):
    facts = _facts()
    _seed_all_100_final_evaluations(fake_db, facts)

    protocol = _trusted_protocol()
    corrupted_symbol = protocol.frozen_symbol_list[3]
    corrupted_evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, corrupted_symbol)
    store = fake_db.raw_store(EVALUATIONS_COLLECTION)
    tampered = dict(store[corrupted_evaluation_id])
    tampered["record_content_sha256"] = "0" * 64
    store[corrupted_evaluation_id] = tampered

    controller = _make_controller(fake_db)
    result = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    assert result.accounting.status == SessionAccountingStatus.REPOSITORY_PROVENANCE_CONFLICT
    assert result.accounting.conflict_count == 1
    assert result.manifest is None
    assert result.create_outcome is None


# ---------------------------------------------------------------------------
# section 44 -- manifest idempotency
# ---------------------------------------------------------------------------


def test_manifest_build_and_persist_twice_is_idempotent(fake_db):
    facts = _facts()
    _seed_all_100_final_evaluations(fake_db, facts)
    controller = _make_controller(fake_db)

    first = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )
    second = controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    assert first.create_outcome == SessionManifestOutcome.CREATED
    assert second.create_outcome == SessionManifestOutcome.IDEMPOTENT_REUSE
    assert first.manifest.record_content_sha256 == second.manifest.record_content_sha256
    assert len(fake_db.raw_store(MANIFESTS_COLLECTION)) == 1


# ---------------------------------------------------------------------------
# section 45 -- manifest conflict on different content, same session_id
# ---------------------------------------------------------------------------


def test_manifest_conflict_when_existing_differs(fake_db):
    facts = _facts()
    _seed_all_100_final_evaluations(fake_db, facts)
    controller = _make_controller(fake_db)
    controller.build_session_manifest_if_complete(
        protocol_version=LOCKED_PROTOCOL_VERSION, T_session_date=_T_SESSION_DATE, facts=facts
    )

    # Aynı session_id, ama İÇERİK olarak farklı (bir sembolün capture_status'unu
    # doğrudan repository BYPASS edilerek değiştirilmiş yeni bir aday) bir
    # manifest -- var olan kayıtla ÇAKIŞMALI.
    protocol = _trusted_protocol()
    different_evaluations = [_make_minimal_final_evaluation(symbol, facts) for symbol in protocol.frozen_symbol_list]
    from app.research.session_manifest import build_session_manifest

    # technical_observation_eligible_count'u DEĞİŞTİRMEDEN farklı bir
    # final_evaluation_records_sha256 üretmek için TEK bir kaydın
    # evaluation_integrity_status'unu (capture_status/eligible AYNI kalacak
    # şekilde) değiştiriyoruz.
    from dataclasses import replace as _replace

    different_evaluations[0] = _replace(
        different_evaluations[0], evaluation_integrity_status=EvaluationIntegrityStatus.EVIDENCE_INTEGRITY_FAILURE
    )
    conflicting_manifest = build_session_manifest(
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        freeze_manifest_sha256=facts.freeze_manifest_sha256,
        frozen_symbols=protocol.frozen_symbol_list,
        final_evaluations=different_evaluations,
    )

    with pytest.raises(ProvenanceConflictError):
        _make_manifest_repo(fake_db).create(conflicting_manifest)
