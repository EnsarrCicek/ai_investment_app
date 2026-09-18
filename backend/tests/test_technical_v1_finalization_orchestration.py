"""HATA 13D — `TechnicalV1Attempt2Orchestrator`/`TechnicalV1Finalizer`'ın
KENDİ (production) akışını, gerçek Firestore/GCS/ağ olmadan, doğrudan
çalıştıran testler.

Desen `test_technical_v1_attempt_execution.py` İLE AYNI: gerçek Firestore
client'ı minimal, sözleşme-uyumlu bir sahteyle değiştirilir; `Fake
EvidenceObjectStore` (HATA 12N1, üretim kodunun KENDİSİ) GCS'in yerini
alır; provider hiçbir zaman gerçek ağa gitmez. Attempt1/attempt2 durumları
GERÇEK `TechnicalV1AttemptExecutionService` (HATA 13C, DEĞİŞTİRİLMEMİŞ)
çağrılarak üretilir -- burada İKİNCİ bir sahte/stub attempt sonucu
üretme mantığı YAZILMAZ."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories import technical_v1_attempt_repository as attempt_repo_module
from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
from app.repositories.technical_v1_attempt_repository import TechnicalV1AttemptRepository
from app.repositories.technical_v1_evaluation_repository import (
    COLLECTION as EVALUATIONS_COLLECTION,
    FinalEvaluationOutcome,
    TechnicalV1EvaluationRepository,
)
from app.research import technical_v1_runtime_identity as runtime_identity_module
from app.research.activation_event import build_initial_activation_event
from app.research.activation_lock import TechnicalV1ActivationLock, compute_activation_lock_id
from app.research.attempt_models import AttemptClaim, AttemptResultClassification, GateCheckResult
from app.research.attempt_reason_codes import PROVIDER_DATA_UNAVAILABLE
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id
from app.research.evidence_models import EvidenceObjectKind, ObjectStoreError, ProvenanceConflictError
from app.research.evidence_object_store import FakeEvidenceObjectStore
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    CaptureStatus,
    EvaluationIntegrityStatus,
    FinalizationContext,
    FinalizationRetryableError,
)
from app.research.technical_v1_attempt2_orchestration import (
    Attempt2Outcome,
    TechnicalV1Attempt2Orchestrator,
)
from app.research.technical_v1_attempt_execution import TechnicalV1AttemptExecutionService
from app.research.technical_v1_attempt_schedule import attempt2_decision_time_utc, formal_cutoff_utc
from app.research.technical_v1_finalization import FinalizationOutcome, TechnicalV1Finalizer
from app.research.technical_v1_methodology_observation import observe_methodology_source_fingerprint
from app.research.technical_v1_scoring_config_values import load_verified_scoring_config_hash
from app.services.market_data.trading_calendar import expected_trading_sessions

TZ = ZoneInfo("Europe/Istanbul")
EXEC_NOW = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)  # analysis_start=2026-02-25, boundary=2026-08-24

LOCKED_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"
LOCKED_FREEZE_MANIFEST_SHA256 = "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"
LOCKED_ENGINE_VERSION = "1.14.0"

_FROZEN_INDICATOR_WEIGHTS = {
    "rsi": 0.1667,
    "macd": 0.1667,
    "trend": 0.1667,
    "bollinger": 0.1667,
    "momentum": 0.1667,
    "ema_slope": 0.2,
    "roc": 0.1665,
}
_FROZEN_FAMILY_WEIGHTS = {
    "trend": 0.33333333333333331,
    "oscillator_position": 0.33333333333333331,
    "momentum_rate": 0.33333333333333331,
}

_PROJECT_ID = "test-project-2026"
_RUNTIME_SERVICE = "backend-api"
_RUNTIME_REVISION = "backend-api-00001-abc"
_GIT_SHA = "730ef262f350b97b9290adddbd7c6a38c024729b"

_REAL_FROZEN_MEMBER = "THYAO"
_T_SESSION_DATE = "2026-08-24"


# ---------------------------------------------------------------------------
# Sahte Firestore harness -- 13B/13C testleriyle AYNI desen.
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

    def get(self, transaction=None):
        return _FakeDocSnapshot(self._store.get(self._key), self._create_times.get(self._key))

    def create(self, data):
        if self._key in self._store:
            raise AlreadyExists(f"document already exists: {self._key}")
        self._store[self._key] = dict(data)
        # HATA 13D: varsayılan create_time, T_SESSION_DATE=2026-08-24 için
        # formal_cutoff_utc'den (2026-08-25 06:45 UTC) ÖNCE olacak şekilde
        # seçildi -- attempt1/attempt2 dokümanlarının SIRADAN (geç-yazım
        # OLMAYAN) durumda otomatik olarak "cutoff'tan önce" sayılması
        # için. Geç-yazım senaryoları `set_create_time()` ile AÇIKÇA
        # override eder.
        self._create_times.setdefault(self._key, datetime(2026, 8, 25, 5, 30, tzinfo=timezone.utc))


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

    def set_create_time(self, collection_name, doc_id, create_time):
        """Testler için: belirli bir dokümanın sunucu `create_time`'ını
        AÇIKÇA kontrol eder (attempt1/attempt2'nin cutoff'a göre önce/sonra
        oluştuğunu simüle etmek için)."""
        self._create_times.setdefault(collection_name, {})[doc_id] = create_time


class _FakeProvider:
    def __init__(self, history_df: pd.DataFrame, fail_on_symbols: frozenset = frozenset()):
        self._history_df = history_df
        self._fail_on_symbols = fail_on_symbols
        self.calls: list[str] = []

    def get_history(self, symbol, period="6mo", interval="1d", start=None, end=None):
        self.calls.append(symbol)
        if symbol in self._fail_on_symbols:
            raise ValueError(f"simulated provider failure for {symbol!r}")
        return self._history_df.copy()

    def get_latest(self, symbol):
        raise NotImplementedError

    def get_quote(self, symbol):
        raise NotImplementedError


class _FakeConfigRepo:
    def __init__(self, indicator_weights=None, family_weights=None):
        self._indicator_weights = indicator_weights if indicator_weights is not None else dict(_FROZEN_INDICATOR_WEIGHTS)
        self._family_weights = family_weights if family_weights is not None else dict(_FROZEN_FAMILY_WEIGHTS)

    def get_raw(self, key):
        if key == "technical_indicator_weights":
            return self._indicator_weights
        if key == "technical_family_weights":
            return self._family_weights
        return None


class _FakeBenchmarkCacheRepo:
    def get(self):
        return None

    def set(self, close_by_date, fetched_at):
        pass


class _FailingEvidenceStore:
    def __init__(self, inner, fail_kind, fail_with):
        self._inner = inner
        self._fail_kind = fail_kind
        self._fail_with = fail_with

    def put_immutable(self, kind, expected_sha256, raw_bytes):
        return self._inner.put_immutable(kind, expected_sha256, raw_bytes)

    def get_verified(self, kind, expected_sha256):
        if kind == self._fail_kind:
            raise self._fail_with
        return self._inner.get_verified(kind, expected_sha256)


def _bday_df(start: str, end: str, base_price: float = 100.0, seed: int = 7) -> pd.DataFrame:
    sessions = expected_trading_sessions(pd.Timestamp(start).date(), pd.Timestamp(end).date())
    dates = pd.DatetimeIndex([pd.Timestamp(d, tz=TZ) for d in sessions])
    rng = np.random.default_rng(seed)
    closes = base_price + np.cumsum(rng.normal(0, 1, len(dates)))
    return pd.DataFrame(
        {
            "Open": closes - 0.2,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": rng.integers(1000, 5000, len(dates)),
        },
        index=dates,
    )


@pytest.fixture
def fake_db():
    return _FakeFirestoreClient()


@pytest.fixture(autouse=True)
def _isolated_transactional(monkeypatch):
    monkeypatch.setattr(attempt_repo_module.firestore, "transactional", lambda f: f)


@pytest.fixture
def runtime_env(monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", _PROJECT_ID)
    monkeypatch.setenv("K_SERVICE", _RUNTIME_SERVICE)
    monkeypatch.setenv("K_REVISION", _RUNTIME_REVISION)


@pytest.fixture
def real_methodology_fingerprint():
    return observe_methodology_source_fingerprint()


def _make_lock(methodology_fingerprint: str) -> TechnicalV1ActivationLock:
    activation_lock_id = compute_activation_lock_id(
        protocol_version=LOCKED_PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=_RUNTIME_REVISION,
    )
    return TechnicalV1ActivationLock(
        activation_lock_schema_version="technical_v1_activation_lock_v1",
        activation_lock_id=activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        freeze_manifest_sha256=LOCKED_FREEZE_MANIFEST_SHA256,
        methodology_git_commit=_GIT_SHA,
        authorized_methodology_source_fingerprint=methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=_RUNTIME_REVISION,
        methodology_approval_reference=_GIT_SHA,
    )


@pytest.fixture
def authorized_setup(fake_db, runtime_env, real_methodology_fingerprint):
    lock = _make_lock(real_methodology_fingerprint)
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock)
    event = build_initial_activation_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock.activation_lock_id
    )
    TechnicalV1ActivationEventRepository(db=fake_db).create(event)
    return lock


def _make_execution_service(fake_db, provider, config_repo=None, evidence_store=None) -> TechnicalV1AttemptExecutionService:
    return TechnicalV1AttemptExecutionService(
        activation_lock_repo=TechnicalV1ActivationLockRepository(db=fake_db),
        activation_event_repo=TechnicalV1ActivationEventRepository(db=fake_db),
        attempt_repo=TechnicalV1AttemptRepository(db=fake_db),
        evidence_store=evidence_store if evidence_store is not None else FakeEvidenceObjectStore(),
        provider=provider,
        config_repo=config_repo if config_repo is not None else _FakeConfigRepo(),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )


def _run_attempt1(service, lock, symbol=_REAL_FROZEN_MEMBER):
    return service.execute_attempt(
        activation_lock_id=lock.activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=symbol,
        attempt_number=1,
        now=EXEC_NOW,
    )


def _make_context(symbol=_REAL_FROZEN_MEMBER, T_session_date=_T_SESSION_DATE) -> FinalizationContext:
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, T_session_date, symbol)
    scoring_config_hash = load_verified_scoring_config_hash(LOCKED_FREEZE_MANIFEST_SHA256)
    return FinalizationContext(
        evaluation_id=evaluation_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        methodology_git_commit=_GIT_SHA,
        freeze_manifest_sha256=LOCKED_FREEZE_MANIFEST_SHA256,
        engine_version=LOCKED_ENGINE_VERSION,
        scoring_config_hash=scoring_config_hash,
        T_session_date=T_session_date,
        symbol=symbol,
        E1_date="2026-08-25",
        attempt2_decision_time_utc=attempt2_decision_time_utc(T_session_date),
        formal_cutoff_utc=formal_cutoff_utc(T_session_date),
    )


BEFORE_DECISION = attempt2_decision_time_utc(_T_SESSION_DATE) - timedelta(minutes=1)
AT_DECISION = attempt2_decision_time_utc(_T_SESSION_DATE)
IN_WINDOW = attempt2_decision_time_utc(_T_SESSION_DATE) + timedelta(minutes=10)
AT_CUTOFF = formal_cutoff_utc(_T_SESSION_DATE)
AFTER_CUTOFF = formal_cutoff_utc(_T_SESSION_DATE) + timedelta(minutes=30)  # ~operasyonel 10:15 benzeri


def _make_attempt2_orchestrator(fake_db, execution_service) -> TechnicalV1Attempt2Orchestrator:
    return TechnicalV1Attempt2Orchestrator(db=fake_db, attempt_execution_service=execution_service)


def _make_finalizer(fake_db, evidence_store) -> TechnicalV1Finalizer:
    return TechnicalV1Finalizer(
        db=fake_db, evidence_store=evidence_store, evaluation_repo=TechnicalV1EvaluationRepository(db=fake_db)
    )


def _claim_attempt1_only(fake_db, lock):
    """attempt1 için "claim var + result yok" durumunu doğrudan (13C'yi
    ATLAYARAK, çünkü execute_attempt() her zaman ya publish eder ya da
    exception fırlatır) simüle eder -- claim_attempt() KENDİSİ hâlâ
    değiştirilmemiş, gerçek üretim metodu olarak çağrılır."""
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, _REAL_FROZEN_MEMBER)
    attempt_id = compute_attempt_id(evaluation_id, 1)
    claim = AttemptClaim(
        attempt_id=attempt_id,
        evaluation_id=evaluation_id,
        attempt_number=1,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_REAL_FROZEN_MEMBER,
        claimed_by_runtime="cloud-run-rev-x",
        activation_lock_id=lock.activation_lock_id,
    )
    TechnicalV1AttemptRepository(db=fake_db).claim_attempt(claim)


# ---------------------------------------------------------------------------
# section 38 -- attempt1 VALID before 09:00 -> attempt2 not dispatched
# ---------------------------------------------------------------------------


def test_attempt1_valid_before_0900_skips_attempt2(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    report1 = _run_attempt1(exec_service, lock)
    assert report1.result.result_classification == AttemptResultClassification.VALID_CANDIDATE

    calls_after_attempt1 = len(provider.calls)
    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.NOT_REQUIRED_FIRST_VALID
    assert report2.execution_report is None
    assert len(provider.calls) == calls_after_attempt1  # attempt2 için SIFIR ek provider çağrısı


# ---------------------------------------------------------------------------
# section 39/40/41 -- attempt1 non-valid terminal -> attempt2 REQUIRED
# ---------------------------------------------------------------------------


def test_attempt1_exclusion_requires_attempt2(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2026-08-01", "2026-08-24")  # INSUFFICIENT_HISTORY
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    report1 = _run_attempt1(exec_service, lock)
    assert report1.result.result_classification == AttemptResultClassification.EXCLUSION

    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.DISPATCHED
    assert report2.execution_report.outcome.value == "RESULT_PUBLISHED"
    assert report2.execution_report.result.attempt_number == 2


def test_attempt1_failed_requires_attempt2(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df, fail_on_symbols=frozenset({_REAL_FROZEN_MEMBER}))
    exec_service = _make_execution_service(fake_db, provider)
    report1 = _run_attempt1(exec_service, lock)
    assert report1.result.result_classification == AttemptResultClassification.FAILED

    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()
    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.DISPATCHED
    assert report2.execution_report.result.attempt_number == 2


def test_attempt1_blocked_requires_attempt2(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    drifted_weights = {
        "rsi": 0.2, "macd": 0.2, "trend": 0.2, "bollinger": 0.1, "momentum": 0.1, "ema_slope": 0.1, "roc": 0.1,
    }
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider, config_repo=_FakeConfigRepo(indicator_weights=drifted_weights))
    report1 = _run_attempt1(exec_service, lock)
    assert report1.result.result_classification == AttemptResultClassification.BLOCKED_CONFIG_DRIFT

    # attempt2, DÜZELTİLMİŞ (frozen) config ile çalışsın diye YENİ bir
    # execution service kullanılır -- attempt2'nin KENDİ çalıştırılması
    # bu testin konusu DEĞİL, yalnızca "REQUIRED" kararı.
    fixed_exec_service = _make_execution_service(fake_db, provider)
    orchestrator = _make_attempt2_orchestrator(fake_db, fixed_exec_service)
    context = _make_context()
    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.DISPATCHED
    assert report2.execution_report.result.attempt_number == 2


# ---------------------------------------------------------------------------
# section 42 -- attempt1 CLAIMED, NO_RESULT -> attempt2 REQUIRED, no takeover
# ---------------------------------------------------------------------------


def test_attempt1_claimed_no_result_requires_attempt2_without_takeover(fake_db, authorized_setup):
    lock = authorized_setup
    _claim_attempt1_only(fake_db, lock)

    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.DISPATCHED
    assert report2.execution_report.result.attempt_number == 2
    # attempt1'in claim'i HİÇ dokunulmadan (takeover YOK) kalır.
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, _REAL_FROZEN_MEMBER)
    attempt1_id = compute_attempt_id(evaluation_id, 1)
    assert attempt1_id in fake_db.raw_store("technical_v1_attempt_claims")
    assert attempt1_id not in fake_db.raw_store("technical_v1_attempt_results")


# ---------------------------------------------------------------------------
# section 43/44 -- timing window
# ---------------------------------------------------------------------------


def test_before_0900_produces_not_yet_due_with_zero_writes(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2026-08-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    report = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=BEFORE_DECISION)

    assert report.outcome == Attempt2Outcome.NOT_YET_DUE
    assert provider.calls == []
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, _REAL_FROZEN_MEMBER)
    attempt2_id = compute_attempt_id(evaluation_id, 2)
    assert attempt2_id not in fake_db.raw_store("technical_v1_attempt_claims")


@pytest.mark.parametrize("now_value", [AT_CUTOFF, AFTER_CUTOFF], ids=["exactly_at_cutoff", "after_cutoff"])
def test_at_or_after_0945_produces_window_closed(fake_db, authorized_setup, now_value):
    lock = authorized_setup
    # attempt1 EXCLUSION -> attempt2 REQUIRED, ama pencere zaten kapalı.
    df = _bday_df("2026-08-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    calls_before = len(provider.calls)
    report = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=now_value)

    assert report.outcome == Attempt2Outcome.WINDOW_CLOSED
    assert len(provider.calls) == calls_before  # attempt2 için YENİ provider çağrısı YOK
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, _REAL_FROZEN_MEMBER)
    attempt2_id = compute_attempt_id(evaluation_id, 2)
    assert attempt2_id not in fake_db.raw_store("technical_v1_attempt_claims")


# ---------------------------------------------------------------------------
# section 45 -- duplicate attempt2 invocation
# ---------------------------------------------------------------------------


def test_duplicate_attempt2_invocation_does_not_repeat_provider_work(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2026-08-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()

    first = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)
    calls_after_first = len(provider.calls)
    assert first.outcome == Attempt2Outcome.DISPATCHED

    second = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock.activation_lock_id, now=IN_WINDOW)

    assert second.outcome == Attempt2Outcome.DISPATCHED
    assert second.execution_report.outcome.value == "ALREADY_CLAIMED"
    assert len(provider.calls) == calls_after_first


# ---------------------------------------------------------------------------
# section 46/47 -- finalize before/after cutoff
# ---------------------------------------------------------------------------


def test_finalize_before_cutoff_is_not_yet_finalizable(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    evidence_store = exec_service._evidence_store
    finalizer = _make_finalizer(fake_db, evidence_store)
    context = _make_context()

    report = finalizer.finalize(context, now=BEFORE_DECISION)

    assert report.outcome == FinalizationOutcome.NOT_YET_FINALIZABLE
    assert report.evaluation is None
    assert fake_db.raw_store(EVALUATIONS_COLLECTION) == {}


def test_finalize_after_cutoff_persists_canonical_final_evaluation(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    evidence_store = exec_service._evidence_store
    finalizer = _make_finalizer(fake_db, evidence_store)
    context = _make_context()

    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.outcome == FinalizationOutcome.CREATED
    assert report.evaluation.capture_status == CaptureStatus.VALID_CAPTURE_AVAILABLE
    assert report.evaluation.evaluation_id in fake_db.raw_store(EVALUATIONS_COLLECTION)


# ---------------------------------------------------------------------------
# section 48/49/50 -- final selection scenarios
# ---------------------------------------------------------------------------


def test_attempt1_valid_only_is_selected(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    report1 = _run_attempt1(exec_service, lock)

    finalizer = _make_finalizer(fake_db, exec_service._evidence_store)
    context = _make_context()
    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.evaluation.selected_attempt_id == report1.result.attempt_id
    assert report.evaluation.technical_observation_eligible is True


def test_attempt1_nonvalid_attempt2_valid_is_selected(fake_db, authorized_setup):
    lock = authorized_setup
    exec_service = _make_execution_service(fake_db, _FakeProvider(_bday_df("2026-08-01", "2026-08-24")))
    _run_attempt1(exec_service, lock)  # INSUFFICIENT_HISTORY

    # attempt2: yeterli geçmişli, GERÇEKTEN valid bir provider verisiyle.
    valid_df = _bday_df("2025-09-01", "2026-08-24")
    exec_service_2 = _make_execution_service(fake_db, _FakeProvider(valid_df))
    report2 = exec_service_2.execute_attempt(
        activation_lock_id=lock.activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_REAL_FROZEN_MEMBER,
        attempt_number=2,
        now=EXEC_NOW,
    )
    assert report2.result.result_classification == AttemptResultClassification.VALID_CANDIDATE

    finalizer = _make_finalizer(fake_db, exec_service_2._evidence_store)
    context = _make_context()
    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.evaluation.selected_attempt_id == report2.result.attempt_id
    assert report.evaluation.attempt_1_summary.requirement_state == AttemptRequirementState.REQUIRED
    assert report.evaluation.attempt_2_summary.result_classification == AttemptResultClassification.VALID_CANDIDATE.value


def test_both_nonvalid_produces_no_valid_capture_available(fake_db, authorized_setup):
    lock = authorized_setup
    short_df = _bday_df("2026-08-01", "2026-08-24")
    exec_service = _make_execution_service(fake_db, _FakeProvider(short_df))
    _run_attempt1(exec_service, lock)  # INSUFFICIENT_HISTORY
    exec_service.execute_attempt(
        activation_lock_id=lock.activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_REAL_FROZEN_MEMBER,
        attempt_number=2,
        now=EXEC_NOW,
    )  # AYNI şekilde INSUFFICIENT_HISTORY

    finalizer = _make_finalizer(fake_db, exec_service._evidence_store)
    context = _make_context()
    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.evaluation.capture_status == CaptureStatus.NO_VALID_CAPTURE_AVAILABLE
    assert report.evaluation.selected_attempt_id is None
    assert report.evaluation.technical_observation_eligible is False


# ---------------------------------------------------------------------------
# section 51 -- transient evidence failure, no sibling fallback
# ---------------------------------------------------------------------------


def test_transient_evidence_failure_raises_retryable_and_persists_nothing(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    failing_store = _FailingEvidenceStore(
        exec_service._evidence_store,
        fail_kind=EvidenceObjectKind.ASSET_SNAPSHOT,
        fail_with=ObjectStoreError("simulated transient GCS failure"),
    )
    finalizer = _make_finalizer(fake_db, failing_store)
    context = _make_context()

    with pytest.raises(FinalizationRetryableError):
        finalizer.finalize(context, now=AFTER_CUTOFF)

    assert fake_db.raw_store(EVALUATIONS_COLLECTION) == {}


# ---------------------------------------------------------------------------
# section 52 -- evidence hash mismatch
# ---------------------------------------------------------------------------


def test_evidence_hash_mismatch_is_recorded_as_integrity_failure(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    failing_store = _FailingEvidenceStore(
        exec_service._evidence_store,
        fail_kind=EvidenceObjectKind.ASSET_SNAPSHOT,
        fail_with=ProvenanceConflictError("simulated content-address mismatch"),
    )
    finalizer = _make_finalizer(fake_db, failing_store)
    context = _make_context()

    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.outcome == FinalizationOutcome.CREATED
    assert report.evaluation.evaluation_integrity_status == EvaluationIntegrityStatus.EVIDENCE_INTEGRITY_FAILURE
    assert report.evaluation.capture_status == CaptureStatus.NO_VALID_CAPTURE_AVAILABLE
    assert report.evaluation.selected_attempt_id is None


# ---------------------------------------------------------------------------
# section 53 -- claim/result relation invalid
# ---------------------------------------------------------------------------


def test_claim_relation_invalid_is_reflected_in_persisted_final_evaluation(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    # Ham depoyu BYPASS ederek attempt1 claim'inin activation_lock_id'sini
    # tamperlar -- publish_result() zaten geçmiş, ama finalize-zamanı
    # BAĞIMSIZ doğrulama bunu YAKALAMALI (claim/result identity relation).
    evaluation_id = compute_evaluation_id(LOCKED_PROTOCOL_VERSION, _T_SESSION_DATE, _REAL_FROZEN_MEMBER)
    attempt1_id = compute_attempt_id(evaluation_id, 1)
    claims_store = fake_db.raw_store("technical_v1_attempt_claims")
    tampered_claim = dict(claims_store[attempt1_id])
    tampered_claim["symbol"] = "GARAN"  # kimlik alanlarından birini boz
    claims_store[attempt1_id] = tampered_claim

    finalizer = _make_finalizer(fake_db, exec_service._evidence_store)
    context = _make_context()
    report = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert report.outcome == FinalizationOutcome.CREATED
    from app.research.final_evaluation_models import VerificationState

    assert report.evaluation.attempt_1_summary.verification_state == VerificationState.CLAIM_RELATION_INVALID
    assert report.evaluation.evaluation_integrity_status == EvaluationIntegrityStatus.PROVENANCE_CONFLICT


# ---------------------------------------------------------------------------
# section 54 -- concurrent create race
# ---------------------------------------------------------------------------


def test_concurrent_create_race_benign_reuse_when_existing_matches(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    evidence_store = exec_service._evidence_store
    finalizer_a = _make_finalizer(fake_db, evidence_store)
    context = _make_context()
    report_a = finalizer_a.finalize(context, now=AFTER_CUTOFF)
    assert report_a.outcome == FinalizationOutcome.CREATED

    finalizer_b = _make_finalizer(fake_db, evidence_store)
    report_b = finalizer_b.finalize(context, now=AFTER_CUTOFF)

    assert report_b.outcome == FinalizationOutcome.IDEMPOTENT_REUSE
    assert report_b.evaluation.record_content_sha256 == report_a.evaluation.record_content_sha256


def test_concurrent_create_race_conflict_when_existing_differs(fake_db, authorized_setup, monkeypatch):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    evidence_store = exec_service._evidence_store
    evaluation_repo = TechnicalV1EvaluationRepository(db=fake_db)
    context = _make_context()

    # BAŞKA bir (tutarsız) FinalEvaluation'ı doğrudan repository ile
    # (finalizer'ı BYPASS ederek) ÖNCEDEN persist et -- "B" finalizer'ının
    # karşılaşacağı VAR OLAN, FARKLI kaydı simüle eder.
    from app.research.final_evaluation_models import (
        AttemptSummary,
        ClaimPresence,
        FinalEvaluation,
        ResultState,
        VerificationState,
    )

    conflicting_summary = AttemptSummary(
        attempt_number=1,
        attempt_id=compute_attempt_id(context.evaluation_id, 1),
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NOT_APPLICABLE,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )
    conflicting_evaluation = FinalEvaluation(
        evaluation_id=context.evaluation_id,
        protocol_version=context.protocol_version,
        T_session_date=context.T_session_date,
        symbol=context.symbol,
        protocol_sha256=context.protocol_sha256,
        methodology_git_commit=context.methodology_git_commit,
        freeze_manifest_sha256=context.freeze_manifest_sha256,
        engine_version=context.engine_version,
        scoring_config_hash=context.scoring_config_hash,
        E1_date=context.E1_date,
        formal_cutoff_timestamp=context.formal_cutoff_timestamp_str(),
        capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
        evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
        technical_observation_eligible=False,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=conflicting_summary,
        attempt_2_summary=conflicting_summary,
    )
    evaluation_repo.create(conflicting_evaluation)

    # HATA 13D FINAL FIX section 6: "A ve B başlangıçta İKİSİ DE final
    # görmüyor" yarışını simüle eder -- gerçek bir eşzamanlılık yarışında
    # B'nin early-lookup'ı A'nın YAZMASINI henüz GÖRMEYEBİLİR (`None`
    # döner); bu, finalizer'ın YENİ erken-bakış kısa-devresini BİR KEZLİK
    # atlatır ki B kendi (attempt1'in GERÇEK verisinden türeyen) adayını
    # hesaplayıp `.create()`'e ulaşsın -- orada VAR OLAN, FARKLI kayıtla
    # karşılaşıp repository'nin KENDİ, DEĞİŞTİRİLMEMİŞ mantığıyla
    # reddedilir (section 6: "Existing repository create() behavior may
    # verify/reuse the existing canonical record... Do NOT introduce a
    # lease").
    real_get_verified = TechnicalV1EvaluationRepository.get_verified
    call_count = {"n": 0}

    def racy_get_verified(self, evaluation_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return real_get_verified(self, evaluation_id)

    monkeypatch.setattr(TechnicalV1EvaluationRepository, "get_verified", racy_get_verified)

    finalizer_b = _make_finalizer(fake_db, evidence_store)
    with pytest.raises(ProvenanceConflictError):
        finalizer_b.finalize(context, now=AFTER_CUTOFF)


# ---------------------------------------------------------------------------
# section 55 -- idempotent finalization
# ---------------------------------------------------------------------------


def test_finalizing_twice_is_idempotent(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    finalizer = _make_finalizer(fake_db, exec_service._evidence_store)
    context = _make_context()

    first = finalizer.finalize(context, now=AFTER_CUTOFF)
    second = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert first.outcome == FinalizationOutcome.CREATED
    assert second.outcome == FinalizationOutcome.IDEMPOTENT_REUSE
    assert first.evaluation.record_content_sha256 == second.evaluation.record_content_sha256
    assert len(fake_db.raw_store(EVALUATIONS_COLLECTION)) == 1


# ---------------------------------------------------------------------------
# section 56 -- late result does not rewrite
# ---------------------------------------------------------------------------


def test_late_attempt_result_does_not_rewrite_existing_final_evaluation(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    _run_attempt1(exec_service, lock)

    finalizer = _make_finalizer(fake_db, exec_service._evidence_store)
    context = _make_context()
    first = finalizer.finalize(context, now=AFTER_CUTOFF)
    assert first.outcome == FinalizationOutcome.CREATED

    # Cutoff'tan SONRA (audit-only, denetim amaçlı) bir attempt2 sonucu
    # ekleniyor -- bu, ZATEN persist edilmiş FinalEvaluation'ı ASLA
    # yeniden yazmamalı.
    late_report = exec_service.execute_attempt(
        activation_lock_id=lock.activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_REAL_FROZEN_MEMBER,
        attempt_number=2,
        now=EXEC_NOW,
    )
    assert late_report.outcome.value == "RESULT_PUBLISHED"
    # Bu sonucun Firestore create_time'ı formal cutoff'tan SONRAYA
    # AÇIKÇA itilir -- "geç yazım" senaryosunun GERÇEK anlamı budur
    # (yalnızca finalize()'ın İKİNCİ kez çağrılması DEĞİL).
    fake_db.set_create_time("technical_v1_attempt_results", late_report.result.attempt_id, AFTER_CUTOFF + timedelta(hours=1))

    # HATA 13D FINAL FIX -- KİLİTLİ KURAL: "İLK BAŞARIYLA OLUŞTURULMUŞ,
    # DOĞRULANMIŞ FinalEvaluation KANONİKTİR." finalize()'ın ikinci
    # çağrısı, ZATEN var olan doğrulanmış final'i BULUR ve KOŞULSUZ
    # IDEMPOTENT_REUSE döner -- attempt1/attempt2'yi YENİDEN OKUMAZ,
    # select_final_evaluation()'ı YENİDEN ÇAĞIRMAZ, YENİ bir hash HİÇ
    # hesaplamaz/karşılaştırmaz. Geç attempt2 sonucu SADECE attempt audit
    # deposunda (technical_v1_attempt_results) görünür kalır -- bilimsel
    # anlık-görüntüye HİÇ giremez.
    second = finalizer.finalize(context, now=AFTER_CUTOFF)

    assert second.outcome == FinalizationOutcome.IDEMPOTENT_REUSE
    assert second.evaluation.evaluation_id == first.evaluation.evaluation_id
    assert second.evaluation.record_content_sha256 == first.evaluation.record_content_sha256
    assert second.evaluation.selected_attempt_id == first.evaluation.selected_attempt_id
    assert second.evaluation.to_document_fields() == first.evaluation.to_document_fields()
    # Var olan, İLK persist edilmiş kayıt HİÇ DEĞİŞMEDEN kalır.
    stored = fake_db.raw_store(EVALUATIONS_COLLECTION)[context.evaluation_id]
    assert stored["record_content_sha256"] == first.evaluation.record_content_sha256
    assert stored["selected_attempt_id"] == first.evaluation.selected_attempt_id
    assert len(fake_db.raw_store(EVALUATIONS_COLLECTION)) == 1
    # Geç attempt2, attempt audit deposunda hâlâ görünür (silinmedi/
    # gizlenmedi) -- yalnızca zaten-finalize-edilmiş anlık-görüntüye
    # GİREMEDİ.
    assert late_report.result.attempt_id in fake_db.raw_store("technical_v1_attempt_results")


# ---------------------------------------------------------------------------
# Attempt2 different activation lock (section 9)
# ---------------------------------------------------------------------------


def test_attempt2_may_use_a_different_activation_lock_than_attempt1(
    fake_db, runtime_env, real_methodology_fingerprint, monkeypatch
):
    lock_a = _make_lock(real_methodology_fingerprint)
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock_a)
    event_a = build_initial_activation_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock_a.activation_lock_id
    )
    TechnicalV1ActivationEventRepository(db=fake_db).create(event_a)

    df = _bday_df("2026-08-01", "2026-08-24")  # INSUFFICIENT_HISTORY -> attempt2 REQUIRED
    provider = _FakeProvider(df)
    exec_service = _make_execution_service(fake_db, provider)
    report1 = _run_attempt1(exec_service, lock_a)
    assert report1.result.activation_lock_id == lock_a.activation_lock_id

    # attempt2 için AYRI bir kilit yetkilendir (farklı runtime revizyonu).
    from app.research.activation_event import build_lock_authorized_event

    other_activation_lock_id = compute_activation_lock_id(
        protocol_version=LOCKED_PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=real_methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision="backend-api-00002-def",
    )
    lock_b = TechnicalV1ActivationLock(
        activation_lock_schema_version="technical_v1_activation_lock_v1",
        activation_lock_id=other_activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        protocol_sha256=LOCKED_PROTOCOL_SHA256,
        freeze_manifest_sha256=LOCKED_FREEZE_MANIFEST_SHA256,
        methodology_git_commit=_GIT_SHA,
        authorized_methodology_source_fingerprint=real_methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision="backend-api-00002-def",
        methodology_approval_reference=_GIT_SHA,
    )
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock_b)
    event_b = build_lock_authorized_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock_b.activation_lock_id
    )
    TechnicalV1ActivationEventRepository(db=fake_db).create(event_b)

    # attempt1 (08:00) ile attempt2 (09:00-09:45) arasında GERÇEK bir
    # redeploy'u simüle eder -- gözlemlenen runtime, ŞİMDİ lock_b'nin
    # yetkilendirdiği revizyonla eşleşir (lock_a'nınkiyle DEĞİL).
    monkeypatch.setenv("K_REVISION", "backend-api-00002-def")

    orchestrator = _make_attempt2_orchestrator(fake_db, exec_service)
    context = _make_context()
    report2 = orchestrator.run_attempt2_if_required(context, activation_lock_id=lock_b.activation_lock_id, now=IN_WINDOW)

    assert report2.outcome == Attempt2Outcome.DISPATCHED
    assert report2.execution_report.result.activation_lock_id == lock_b.activation_lock_id
    assert report2.execution_report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert lock_a.activation_lock_id != lock_b.activation_lock_id
