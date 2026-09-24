"""PROD-2 — Technical V1 internal job endpoint'lerinin (`app/api/
technical_v1_internal.py`) KENDİ (production) davranışını, gerçek
Firestore/GCS/provider olmadan, `fastapi.testclient.TestClient` ile
doğrudan çalıştıran testler.

Desen `test_api_backtest_period_validation.py` ile AYNI: KENDİ, izole bir
`FastAPI()` uygulaması + router + `TestClient` -- `app.main.app`'in
TAMAMI import edilmez. Controller, `get_controller_factory`
bağımlılığının `app.dependency_overrides` ile GERÇEK GCS/Firestore/
provider'a hiç dokunmadan değiştirilmesiyle sahtelenir (section 28/38) --
`TechnicalV1SessionController`'ın KENDİSİ (production kodu, DEĞİŞTİRİLMEMİŞ)
kullanılır, yalnızca onun ALTINDAKİ üç servis (attempt1/attempt2/finalizer)
hafif stub'lardır (13E'nin kendi test dosyasıyla AYNI desen)."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import technical_v1_internal
from app.repositories.technical_v1_session_manifest_repository import TechnicalV1SessionManifestRepository
from app.repositories.technical_v1_session_run_repository import TechnicalV1SessionRunRepository
from app.research import technical_v1_production
from app.research.evidence_models import ProvenanceConflictError
from app.research.final_evaluation_models import FinalizationRetryableError
from app.research.technical_v1_attempt2_orchestration import Attempt2Outcome, Attempt2Report
from app.research.technical_v1_attempt_execution import AttemptExecutionOutcome, AttemptExecutionReport
from app.research.technical_v1_finalization import FinalizationOutcome, FinalizationReport
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
from app.research.technical_v1_session_controller import TechnicalV1SessionController

# TECH-VOL 1B / TECHNICAL V2: V1 route + factory mekaniği V1 metodolojisiyle eşleşen motor altında test edilir.
pytestmark = pytest.mark.usefixtures("v1_era_engine_version")

LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"
LOCKED_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_T_SESSION_DATE = "2026-08-24"
_JOB_SECRET = "test-technical-v1-secret"

_FULL_FACTS_FIELDS = {
    "methodology_git_commit": "730ef262f350b97b9290adddbd7c6a38c024729b",
    "freeze_manifest_sha256": "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97",
    "engine_version": "1.14.0",
    "scoring_config_hash": "c" * 64,
    "E1_date": "2026-08-25",
}

_ATTEMPT1_BODY = {
    "protocol_version": LOCKED_PROTOCOL_VERSION,
    "protocol_sha256": LOCKED_PROTOCOL_SHA256,
    "T_session_date": _T_SESSION_DATE,
    "activation_lock_id": "a" * 64,
}
_ATTEMPT2_BODY = {**_ATTEMPT1_BODY, **_FULL_FACTS_FIELDS}
_FINALIZE_BODY = {
    "protocol_version": LOCKED_PROTOCOL_VERSION,
    "protocol_sha256": LOCKED_PROTOCOL_SHA256,
    "T_session_date": _T_SESSION_DATE,
    **_FULL_FACTS_FIELDS,
}
_MANIFEST_BODY = dict(_FINALIZE_BODY)


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
    def __init__(self, outcome=Attempt2Outcome.DISPATCHED):
        self.calls: list[str] = []
        self._outcome = outcome

    def run_attempt2_if_required(self, context, *, activation_lock_id, now):
        self.calls.append(context.symbol)
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


class _FakeDocRef:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def set(self, payload, merge=False):
        self._store[self._key] = dict(payload)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDocRef(self._store, doc_id)


class _FakeFirestoreClient:
    """`run_finalization_phase()`'in `TechnicalV1SessionRunRepository.
    upsert()`'ü GERÇEKTEN çağırdığı için minimal bir sahte Firestore --
    diğer testlerdeki AYNI full-replace deseni. `firestore.SERVER_
    TIMESTAMP` sentinel'i bu testlerde HİÇ okunmadığından (yalnızca
    write-path egzersiz edilir) özel bir çözümleme GEREKMEZ."""

    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))


@pytest.fixture(autouse=True)
def _job_secret(monkeypatch):
    monkeypatch.setattr(technical_v1_internal, "TECHNICAL_V1_JOB_SECRET", _JOB_SECRET)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(technical_v1_internal.router)
    return TestClient(app)


def _make_controller(*, attempt1=None, attempt2=None, finalizer=None) -> TechnicalV1SessionController:
    protocol = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    return TechnicalV1SessionController(
        trusted_protocol=protocol,
        attempt_execution_service=attempt1 or _StubAttempt1Service(),
        attempt2_orchestrator=attempt2 or _StubAttempt2Orchestrator(),
        finalizer=finalizer or _StubFinalizer(),
        session_run_repo=TechnicalV1SessionRunRepository(db=_FakeFirestoreClient()),
        session_manifest_repo=TechnicalV1SessionManifestRepository(db=_FakeFirestoreClient()),
        evaluation_repo=_FakeEvaluationRepoStub(),
    )


class _FakeEvaluationRepoStub:
    """Manifest fazı testlerinde `build_session_manifest_if_complete()`'in
    100 `get_verified()` çağrısını (hepsi ABSENT) güvenle egzersiz etmesi
    için minimal, gerçek Firestore'a hiç dokunmayan bir sahte."""

    def get_verified(self, evaluation_id):
        return None


@pytest.fixture
def override_controller(client):
    def _install(controller: TechnicalV1SessionController):
        client.app.dependency_overrides[technical_v1_internal.get_controller_factory] = (
            lambda: (lambda protocol_sha256: controller)
        )

    yield _install
    client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# section 26 -- auth failure produces zero writes
# ---------------------------------------------------------------------------


def test_missing_auth_header_is_rejected_before_any_controller_call(client):
    calls = []

    def _factory():
        def _build(protocol_sha256):
            calls.append(protocol_sha256)
            raise AssertionError("controller factory MUST NOT be called on auth failure")

        return _build

    client.app.dependency_overrides[technical_v1_internal.get_controller_factory] = _factory

    response = client.post("/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY)

    assert response.status_code == 403
    assert calls == []
    client.app.dependency_overrides.clear()


def test_wrong_auth_secret_is_rejected(client):
    response = client.post(
        "/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY, headers={"x-job-secret": "wrong-secret"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# section 27 -- missing bucket produces explicit configuration failure
# ---------------------------------------------------------------------------


def test_missing_evidence_bucket_produces_explicit_configuration_error(client, monkeypatch):
    monkeypatch.setattr(technical_v1_production, "TECHNICAL_V1_EVIDENCE_BUCKET", None)

    response = client.post(
        "/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 503
    assert "TECHNICAL_V1_EVIDENCE_BUCKET" in response.json()["detail"]


# ---------------------------------------------------------------------------
# section 28/29/30 -- endpoint dispatch mechanics
# ---------------------------------------------------------------------------


def test_attempt1_endpoint_dispatches_via_controller_and_aggregates_counts(client, override_controller):
    stub = _StubAttempt1Service()
    override_controller(_make_controller(attempt1=stub))

    response = client.post(
        "/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "attempt1"
    assert body["processed"] == 100
    assert body["outcome_counts"] == {"RESULT_PUBLISHED": 100}
    assert len(stub.calls) == 100


def test_attempt2_endpoint_does_not_reimplement_time_decisions(client, override_controller):
    stub = _StubAttempt2Orchestrator(outcome=Attempt2Outcome.NOT_REQUIRED_FIRST_VALID)
    override_controller(_make_controller(attempt2=stub))

    response = client.post(
        "/internal/technical-v1/attempt2", json=_ATTEMPT2_BODY, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome_counts"] == {"NOT_REQUIRED_FIRST_VALID": 100}
    assert len(stub.calls) == 100
    # section 11: kararı VEREN 13D orchestrator'dır (stub burada onun
    # YERİNE geçiyor) -- endpoint kendi zaman/karar mantığı İÇERMEZ.


def test_finalization_endpoint_represents_retryable_and_conflict_counts(client, override_controller):
    protocol = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    retryable_symbol = protocol.frozen_symbol_list[10]
    conflict_symbol = protocol.frozen_symbol_list[20]
    stub = _StubFinalizer(
        retryable_symbols=frozenset({retryable_symbol}), conflict_symbols=frozenset({conflict_symbol})
    )
    override_controller(_make_controller(finalizer=stub))

    response = client.post(
        "/internal/technical-v1/finalize", json=_FINALIZE_BODY, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome_counts"]["CREATED"] == 98
    assert body["outcome_counts"]["RETRYABLE"] == 1
    assert body["outcome_counts"]["PROVENANCE_CONFLICT"] == 1
    assert len(stub.calls) == 100


# ---------------------------------------------------------------------------
# section 31 -- manifest endpoint, complete vs incomplete
# ---------------------------------------------------------------------------


def test_manifest_endpoint_missing_records_succeeds_operationally_but_reports_incomplete(client, override_controller):
    override_controller(_make_controller())  # evaluation_repo stub -> hepsi ABSENT

    response = client.post(
        "/internal/technical-v1/manifest", json=_MANIFEST_BODY, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 200  # eksik bir session bir sunucu çökmesi DEĞİLDİR
    body = response.json()
    assert body["accounting_status"] == "MISSING_FINAL_RECORDS"
    assert body["expected_symbol_count"] == 100
    assert body["verified_count"] == 0
    assert body["absent_count"] == 100
    assert body["manifest_persisted"] is False
    assert body["create_outcome"] is None


# ---------------------------------------------------------------------------
# section 32/33 -- aggregate + partial failure logging
# ---------------------------------------------------------------------------


def test_all_100_operational_errors_emit_unmistakable_aggregate_error_log(client, override_controller, caplog):
    protocol = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    stub = _StubAttempt1Service(fail_symbols=frozenset(protocol.frozen_symbol_list))
    override_controller(_make_controller(attempt1=stub))

    with caplog.at_level(logging.WARNING, logger="technical_v1"):
        response = client.post(
            "/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY, headers={"x-job-secret": _JOB_SECRET}
        )

    assert response.status_code == 200
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    payload = json.loads(error_records[0].message)
    assert payload["event"] == "phase_all_symbols_failed"
    assert payload["phase"] == "attempt1"
    assert payload["processed"] == 100
    assert payload["outcome_counts"]["OPERATIONAL_ERROR"] == 100


def test_one_operational_error_emits_warning_without_aborting_session(client, override_controller, caplog):
    protocol = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    crashing_symbol = protocol.frozen_symbol_list[5]
    stub = _StubAttempt1Service(fail_symbols=frozenset({crashing_symbol}))
    override_controller(_make_controller(attempt1=stub))

    with caplog.at_level(logging.WARNING, logger="technical_v1"):
        response = client.post(
            "/internal/technical-v1/attempt1", json=_ATTEMPT1_BODY, headers={"x-job-secret": _JOB_SECRET}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 100
    assert body["outcome_counts"]["OPERATIONAL_ERROR"] == 1
    assert body["outcome_counts"]["RESULT_PUBLISHED"] == 99

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    aggregate = [json.loads(r.message) for r in warning_records if json.loads(r.message).get("event") == "phase_partial_failure"]
    assert len(aggregate) == 1
    assert aggregate[0]["outcome_counts"]["OPERATIONAL_ERROR"] == 1
    per_symbol = [json.loads(r.message) for r in warning_records if json.loads(r.message).get("event") == "phase_symbol_issue"]
    assert any(item["symbol"] == crashing_symbol for item in per_symbol)


# ---------------------------------------------------------------------------
# section 17 -- manifest incomplete also logged as warning
# ---------------------------------------------------------------------------


def test_manifest_incomplete_emits_warning_log(client, override_controller, caplog):
    override_controller(_make_controller())

    with caplog.at_level(logging.WARNING, logger="technical_v1"):
        response = client.post(
            "/internal/technical-v1/manifest", json=_MANIFEST_BODY, headers={"x-job-secret": _JOB_SECRET}
        )

    assert response.status_code == 200
    warning_records = [json.loads(r.message) for r in caplog.records if r.levelno == logging.WARNING]
    manifest_events = [item for item in warning_records if item.get("event") == "manifest_incomplete"]
    assert len(manifest_events) == 1
    assert manifest_events[0]["accounting_status"] == "MISSING_FINAL_RECORDS"


# ---------------------------------------------------------------------------
# section 34 -- log redaction
# ---------------------------------------------------------------------------


def test_secret_and_raw_exception_message_never_appear_in_logs(client, override_controller, caplog):
    protocol = load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)
    crashing_symbol = protocol.frozen_symbol_list[0]

    class _LeakyStub:
        calls = []

        def execute_attempt(self, **kwargs):
            self.calls.append(kwargs["symbol"])
            if kwargs["symbol"] == crashing_symbol:
                raise RuntimeError(f"leak test: secret={_JOB_SECRET} url=https://example.com/token=abc123")
            return AttemptExecutionReport(outcome=AttemptExecutionOutcome.RESULT_PUBLISHED)

    stub = _LeakyStub()
    override_controller(_make_controller(attempt1=stub))

    with caplog.at_level(logging.WARNING, logger="technical_v1"):
        response = client.post(
            "/internal/technical-v1/attempt1",
            json=_ATTEMPT1_BODY,
            headers={"x-job-secret": _JOB_SECRET, "Authorization": "Bearer super-secret-token"},
        )

    assert response.status_code == 200
    all_log_text = "\n".join(r.message for r in caplog.records)
    assert _JOB_SECRET not in all_log_text
    assert "super-secret-token" not in all_log_text
    assert "https://example.com" not in all_log_text
    assert "token=abc123" not in all_log_text
    # exception TÜRÜ (sadece adı) loglanır, ham mesaj DEĞİL.
    assert "RuntimeError" in all_log_text


# ---------------------------------------------------------------------------
# section 37 -- no public symbol list
# ---------------------------------------------------------------------------


def test_extra_symbol_list_field_is_silently_ignored_not_applied(client, override_controller):
    stub = _StubAttempt1Service()
    override_controller(_make_controller(attempt1=stub))

    body_with_symbols = dict(_ATTEMPT1_BODY)
    body_with_symbols["symbols"] = ["FAKE1", "FAKE2"]

    response = client.post(
        "/internal/technical-v1/attempt1", json=body_with_symbols, headers={"x-job-secret": _JOB_SECRET}
    )

    assert response.status_code == 200
    assert response.json()["processed"] == 100
    assert "FAKE1" not in stub.calls
    assert "FAKE2" not in stub.calls


# ---------------------------------------------------------------------------
# section 9 -- malformed T_session_date rejected
# ---------------------------------------------------------------------------


def test_malformed_t_session_date_is_rejected_with_400(client, override_controller):
    override_controller(_make_controller())
    bad_body = {**_ATTEMPT1_BODY, "T_session_date": "24-08-2026"}

    response = client.post("/internal/technical-v1/attempt1", json=bad_body, headers={"x-job-secret": _JOB_SECRET})

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# section 35 -- production factory composition (real build_session_controller)
# ---------------------------------------------------------------------------


def test_production_factory_builds_full_dependency_chain(monkeypatch):
    monkeypatch.setattr(technical_v1_production, "TECHNICAL_V1_EVIDENCE_BUCKET", "fake-bucket-name")

    class _FakeGCSClient:
        def bucket(self, name):
            raise AssertionError("gerçek GCS client hiç KULLANILMAMALI (yalnızca lazy referans tutulur)")

    monkeypatch.setattr(technical_v1_production, "get_firestore_client", lambda: _FakeFirestoreClient())

    controller = technical_v1_production.build_session_controller(protocol_sha256=LOCKED_PROTOCOL_SHA256)

    assert isinstance(controller, TechnicalV1SessionController)
    assert controller._attempt_execution_service is not None
    assert controller._attempt2_orchestrator is not None
    assert controller._finalizer is not None
    assert len(controller._trusted_protocol.frozen_symbol_list) == 100


def test_production_factory_raises_before_any_io_when_bucket_missing(monkeypatch):
    monkeypatch.setattr(technical_v1_production, "TECHNICAL_V1_EVIDENCE_BUCKET", None)

    def _boom():
        raise AssertionError("get_firestore_client MUST NOT be called before the bucket check")

    monkeypatch.setattr(technical_v1_production, "get_firestore_client", _boom)

    with pytest.raises(technical_v1_production.TechnicalV1ConfigurationError):
        technical_v1_production.build_session_controller(protocol_sha256=LOCKED_PROTOCOL_SHA256)


# ---------------------------------------------------------------------------
# section 36 -- import/startup regression with Technical V1 env absent
# ---------------------------------------------------------------------------


def test_app_main_imports_successfully_without_evidence_bucket_configured(monkeypatch):
    monkeypatch.delenv("TECHNICAL_V1_EVIDENCE_BUCKET", raising=False)
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    assert main_module.app is not None
