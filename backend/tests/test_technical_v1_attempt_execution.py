"""HATA 13C — `TechnicalV1AttemptExecutionService`'in KENDİ (production)
akışını, gerçek Firestore/GCS/ağ olmadan, doğrudan çalıştıran testler.

Desen `test_technical_v1_activation_lock_repository.py`/`test_technical_v1_
attempt_repository.py` İLE AYNI: gerçek Firestore client'ı minimal,
sözleşme-uyumlu bir sahteyle değiştirilir; `FakeEvidenceObjectStore`
(HATA 12N1, üretim kodunun KENDİSİ) GCS'in yerini alır; provider hiçbir
zaman gerçek ağa gitmez."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from google.api_core.exceptions import AlreadyExists

from app.engines.technical.data_quality import TradingCalendarUnsupportedError
from app.repositories import technical_v1_attempt_repository as attempt_repo_module
from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
from app.repositories.technical_v1_attempt_repository import TechnicalV1AttemptRepository
from app.research import technical_v1_attempt_execution as execution_module
from app.research import technical_v1_runtime_identity as runtime_identity_module
from app.research.activation_event import build_initial_activation_event
from app.research.activation_lock import TechnicalV1ActivationLock, compute_activation_lock_id
from app.research.attempt_models import AttemptResultClassification, ClaimOutcome, GateCheckResult, PublishOutcome
from app.research.attempt_reason_codes import (
    LEADING_EDGE_UNVERIFIED,
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    PROVIDER_DATA_UNAVAILABLE,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
    SYMBOL_NOT_IN_FROZEN_UNIVERSE,
    TECHNICAL_SCORE_NONE,
)
from app.research.evidence_models import EvidenceObjectKind, ObjectStoreError, ProvenanceConflictError
from app.research.evidence_object_store import FakeEvidenceObjectStore
from app.research.evidence_serialization import deserialize_asset_snapshot
from app.research.technical_v1_attempt_execution import (
    AttemptExecutionOutcome,
    TechnicalV1AttemptExecutionService,
)
from app.research.technical_v1_methodology_observation import observe_methodology_source_fingerprint
from app.services.market_data.trading_calendar import expected_trading_sessions

# TECH-VOL 1B: V1 pipeline mekaniği, V1 metodolojisiyle eşleşen bir motor altında test edilir.
pytestmark = pytest.mark.usefixtures("v1_era_engine_version")

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 8, 25, 13, 0, tzinfo=TZ)  # analysis_start=2026-02-25, boundary=2026-08-24

LOCKED_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"
LOCKED_FREEZE_MANIFEST_SHA256 = "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"

# `technical_v1_freeze_manifest.json`'daki KENDİ `technical_indicator_
# weights`/`technical_family_weights` alanlarıyla BİREBİR aynı -- bu
# TEK kombinasyon, `load_verified_scoring_config_hash(LOCKED_FREEZE_
# MANIFEST_SHA256)`'ın döndürdüğü GERÇEK, dondurulmuş `scoring_config_hash`
# değerini üretir (doğrudan doğrulandı). Fake config repo bunu döndürünce
# CONFIG kapısı GERÇEKTEN PASS eder -- taklit/mock bir eşleşme DEĞİL.
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
_NOT_A_MEMBER = "FAKE"

_T_SESSION_DATE = "2026-08-24"


# ---------------------------------------------------------------------------
# Sahte Firestore harness -- activation-lock/activation-event/attempt
# repository testleriyle AYNI desen, TEK bir paylaşılan store'da birleştirilmiş
# (üç repository de AYNI fake client'ı kullanır, üç AYRI koleksiyon adıyla).
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
        self._create_times[self._key] = datetime(2026, 9, 18, 6, 0, tzinfo=TZ)


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


class _FakeProvider:
    """`MarketDataProvider` sözleşmesine uyan, gerçek ağa hiç gitmeyen sahte
    sağlayıcı -- her çağrıyı (`symbol`) kaydeder, `fail_on_symbols`
    içindeyse istisna fırlatır."""

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
    """Gerçek `FakeEvidenceObjectStore`'u sarmalar, TEK bir `kind` için
    `put_immutable()`'ı yapılandırılabilir bir istisnayla BAŞARISIZ kılar
    (section 52/53 -- object-store transient/provenance senaryoları)."""

    def __init__(self, inner: FakeEvidenceObjectStore, fail_kind: EvidenceObjectKind, fail_with: Exception):
        self._inner = inner
        self._fail_kind = fail_kind
        self._fail_with = fail_with

    def put_immutable(self, kind, expected_sha256, raw_bytes):
        if kind == self._fail_kind:
            raise self._fail_with
        return self._inner.put_immutable(kind, expected_sha256, raw_bytes)

    def get_verified(self, kind, expected_sha256):
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
    # HATA 12N2A test deseni: gerçek Firestore transaction protokolü ağ
    # gerektirir -- decorator identity-wrapper'a indirgenir, SARDIĞI
    # production fonksiyonunun gövdesi AYNEN çalışır.
    monkeypatch.setattr(attempt_repo_module.firestore, "transactional", lambda f: f)


@pytest.fixture
def runtime_env(monkeypatch):
    """RUNTIME kapısının GERÇEKTEN gözlemlenebilir olması için (section
    17) K_SERVICE/K_REVISION/FIREBASE_PROJECT_ID'yi bilinen, sabit test
    değerlerine ayarlar."""
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
    """Tam yetkilendirilmiş (activation lock + INITIAL event, ikisi de
    repository'ye GERÇEKTEN persist edilmiş) bir senaryo -- her "happy path"
    testin ortak başlangıç noktası."""
    lock = _make_lock(real_methodology_fingerprint)
    lock_repo = TechnicalV1ActivationLockRepository(db=fake_db)
    lock_repo.create(lock)

    event = build_initial_activation_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock.activation_lock_id
    )
    event_repo = TechnicalV1ActivationEventRepository(db=fake_db)
    event_repo.create(event)

    return lock


def _make_service(fake_db, provider, config_repo=None, evidence_store=None) -> TechnicalV1AttemptExecutionService:
    return TechnicalV1AttemptExecutionService(
        activation_lock_repo=TechnicalV1ActivationLockRepository(db=fake_db),
        activation_event_repo=TechnicalV1ActivationEventRepository(db=fake_db),
        attempt_repo=TechnicalV1AttemptRepository(db=fake_db),
        evidence_store=evidence_store if evidence_store is not None else FakeEvidenceObjectStore(),
        provider=provider,
        config_repo=config_repo if config_repo is not None else _FakeConfigRepo(),
        benchmark_cache_repo=_FakeBenchmarkCacheRepo(),
    )


def _execute(service, lock, symbol=_REAL_FROZEN_MEMBER, attempt_number=1):
    return service.execute_attempt(
        activation_lock_id=lock.activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=symbol,
        attempt_number=attempt_number,
        now=NOW,
    )


# ---------------------------------------------------------------------------
# section 40 -- pre-claim no-write tests
# ---------------------------------------------------------------------------


def test_no_event_produces_zero_claim_zero_evidence_zero_provider_calls(fake_db, runtime_env, real_methodology_fingerprint):
    lock = _make_lock(real_methodology_fingerprint)
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock)
    # KASITLI OLARAK hiçbir activation event create edilmedi.

    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.outcome == AttemptExecutionOutcome.PRE_ACTIVATION
    assert fake_db.raw_store("technical_v1_attempt_claims") == {}
    assert fake_db.raw_store("technical_v1_attempt_results") == {}
    assert provider.calls == []


def test_outside_frozen_universe_produces_zero_claim_zero_evidence_zero_provider_calls(fake_db, authorized_setup):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock, symbol=_NOT_A_MEMBER)

    assert report.outcome == AttemptExecutionOutcome.OUTSIDE_FROZEN_UNIVERSE
    assert fake_db.raw_store("technical_v1_attempt_claims") == {}
    assert fake_db.raw_store("technical_v1_attempt_results") == {}
    assert provider.calls == []


def test_lock_protocol_contradiction_produces_zero_claim_zero_provider_calls(fake_db, runtime_env, real_methodology_fingerprint):
    activation_lock_id = compute_activation_lock_id(
        protocol_version=LOCKED_PROTOCOL_VERSION,
        authorized_methodology_source_fingerprint=real_methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=_RUNTIME_REVISION,
    )
    contradictory_lock = TechnicalV1ActivationLock(
        activation_lock_schema_version="technical_v1_activation_lock_v1",
        activation_lock_id=activation_lock_id,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        protocol_sha256="f" * 64,  # trusted_protocol'ün GERÇEK hash'iyle UYUŞMUYOR
        freeze_manifest_sha256=LOCKED_FREEZE_MANIFEST_SHA256,
        methodology_git_commit=_GIT_SHA,
        authorized_methodology_source_fingerprint=real_methodology_fingerprint,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=_RUNTIME_REVISION,
        methodology_approval_reference=_GIT_SHA,
    )
    TechnicalV1ActivationLockRepository(db=fake_db).create(contradictory_lock)

    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    with pytest.raises(ProvenanceConflictError):
        _execute(service, contradictory_lock)

    assert fake_db.raw_store("technical_v1_attempt_claims") == {}
    assert provider.calls == []


# ---------------------------------------------------------------------------
# section 7 -- activation lock not found
# ---------------------------------------------------------------------------


def test_activation_lock_not_found(fake_db):
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    report = service.execute_attempt(
        activation_lock_id="a" * 64,
        protocol_version=LOCKED_PROTOCOL_VERSION,
        T_session_date=_T_SESSION_DATE,
        symbol=_REAL_FROZEN_MEMBER,
        attempt_number=1,
        now=NOW,
    )

    assert report.outcome == AttemptExecutionOutcome.ACTIVATION_LOCK_NOT_FOUND
    assert provider.calls == []


# ---------------------------------------------------------------------------
# section 41/42 -- authorization immediately before claim
# ---------------------------------------------------------------------------


def test_authorization_happens_before_claim_attempt_is_ever_called(fake_db, authorized_setup, monkeypatch):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    call_order: list[str] = []
    real_authorize = execution_module.authorize_pre_claim
    real_claim_attempt = TechnicalV1AttemptRepository.claim_attempt

    def spy_authorize(**kwargs):
        call_order.append("authorize_pre_claim")
        return real_authorize(**kwargs)

    def spy_claim_attempt(self, claim):
        call_order.append("claim_attempt")
        return real_claim_attempt(self, claim)

    monkeypatch.setattr(execution_module, "authorize_pre_claim", spy_authorize)
    monkeypatch.setattr(TechnicalV1AttemptRepository, "claim_attempt", spy_claim_attempt)

    _execute(service, lock)

    assert call_order == ["authorize_pre_claim", "claim_attempt"]


# ---------------------------------------------------------------------------
# section 42 -- BLOCKED identity gate tests
# ---------------------------------------------------------------------------


def test_config_drift_blocks_before_any_provider_call(fake_db, authorized_setup):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    drifted_weights = {
        "rsi": 0.2,
        "macd": 0.2,
        "trend": 0.2,
        "bollinger": 0.1,
        "momentum": 0.1,
        "ema_slope": 0.1,
        "roc": 0.1,
    }  # tam/geçerli ama dondurulmuş config'ten FARKLI bir ağırlık seti
    drifted_config_repo = _FakeConfigRepo(indicator_weights=drifted_weights)
    service = _make_service(fake_db, provider, config_repo=drifted_config_repo)

    report = _execute(service, lock)

    assert report.outcome == AttemptExecutionOutcome.RESULT_PUBLISHED
    assert report.result.result_classification == AttemptResultClassification.BLOCKED_CONFIG_DRIFT
    assert report.result.native_reason_code == SCORING_CONFIG_HASH_MISMATCH
    assert report.result.config_gate_result == GateCheckResult.FAIL
    assert provider.calls == []
    assert report.result.asset_object_ref is None
    assert report.result.benchmark_object_ref is None
    assert report.result.technical_output_object_ref is None


def test_methodology_drift_blocks_before_any_provider_call(fake_db, runtime_env):
    lock = _make_lock("a" * 64)  # GERÇEK gözlemlenen parmak-izinden FARKLI
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock)
    event = build_initial_activation_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock.activation_lock_id
    )
    TechnicalV1ActivationEventRepository(db=fake_db).create(event)

    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.BLOCKED_METHODOLOGY_DRIFT
    assert report.result.native_reason_code == METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH
    assert provider.calls == []


def test_runtime_drift_blocks_before_any_provider_call(fake_db, real_methodology_fingerprint, monkeypatch):
    monkeypatch.setattr(runtime_identity_module, "FIREBASE_PROJECT_ID", _PROJECT_ID)
    monkeypatch.setenv("K_SERVICE", _RUNTIME_SERVICE)
    monkeypatch.setenv("K_REVISION", "some-other-revision")  # lock'un yetkilendirdiğinden FARKLI

    lock = _make_lock(real_methodology_fingerprint)
    TechnicalV1ActivationLockRepository(db=fake_db).create(lock)
    event = build_initial_activation_event(
        protocol_version=LOCKED_PROTOCOL_VERSION, activation_lock_id=lock.activation_lock_id
    )
    TechnicalV1ActivationEventRepository(db=fake_db).create(event)

    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY
    assert report.result.native_reason_code == RUNTIME_IDENTITY_UNAUTHORIZED
    assert provider.calls == []


def test_universe_drift_blocks_after_claim_even_though_preclaim_already_passed(fake_db, authorized_setup, monkeypatch):
    """Section 17/29: post-claim UNIVERSE kapısı, pre-claim üyelik kontrolü
    ZATEN geçmiş olsa BİLE defense-in-depth olarak ÇALIŞTIRILIR."""
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    from app.research import identity_gates as identity_gates_module

    monkeypatch.setattr(
        execution_module,
        "evaluate_universe_gate",
        lambda *args, **kwargs: identity_gates_module.IdentityGateEvaluation(
            result=GateCheckResult.FAIL, reason_code=SYMBOL_NOT_IN_FROZEN_UNIVERSE
        ),
    )

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG
    assert report.result.native_reason_code == SYMBOL_NOT_IN_FROZEN_UNIVERSE
    assert provider.calls == []


# ---------------------------------------------------------------------------
# section 43 -- provider FAILED tests
# ---------------------------------------------------------------------------


def test_asset_provider_failure_is_terminal_failed(fake_db, authorized_setup):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"), fail_on_symbols=frozenset({_REAL_FROZEN_MEMBER}))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.FAILED
    assert report.result.native_reason_code == PROVIDER_DATA_UNAVAILABLE
    assert report.result.asset_object_ref is None
    assert report.result.technical_output_object_ref is None


def test_benchmark_provider_failure_is_terminal_failed_after_asset_evidence_captured(fake_db, authorized_setup):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"), fail_on_symbols=frozenset({"XU100"}))
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.FAILED
    assert report.result.native_reason_code == PROVIDER_DATA_UNAVAILABLE
    # Asset evidence, benchmark provider hatasından ÖNCE zaten yakalanmıştı.
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is None
    assert report.result.technical_output_object_ref is None


# ---------------------------------------------------------------------------
# section 44 -- internal defect boundary
# ---------------------------------------------------------------------------


def test_unexpected_exception_after_claim_propagates_and_publishes_no_result(fake_db, authorized_setup, monkeypatch):
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected programming defect")

    monkeypatch.setattr(execution_module, "compute_technical_analysis", _boom)

    with pytest.raises(RuntimeError):
        _execute(service, lock)

    claims = fake_db.raw_store("technical_v1_attempt_claims")
    results = fake_db.raw_store("technical_v1_attempt_results")
    assert len(claims) == 1
    assert results == {}


def test_unapproved_data_quality_reason_propagates_as_internal_defect_not_exclusion(fake_db, authorized_setup, monkeypatch):
    """Section 28: `TRADING_CALENDAR_UNSUPPORTED_YEAR` HATA-12-onaylı bir
    EXCLUSION reason'ı DEĞİLDİR -- tahmin edilip FAILED/EXCLUSION'a
    ZORLANMAZ, olduğu gibi YUKARI fırlatılır."""
    lock = authorized_setup
    provider = _FakeProvider(_bday_df("2025-09-01", "2026-08-24"))
    service = _make_service(fake_db, provider)

    def _unsupported_year(*args, **kwargs):
        raise TradingCalendarUnsupportedError(2099)

    monkeypatch.setattr(execution_module, "check_data_quality", _unsupported_year)

    with pytest.raises(TradingCalendarUnsupportedError):
        _execute(service, lock)

    assert fake_db.raw_store("technical_v1_attempt_results") == {}
    assert len(fake_db.raw_store("technical_v1_attempt_claims")) == 1


# ---------------------------------------------------------------------------
# section 45 -- continuity exclusion
# ---------------------------------------------------------------------------


def test_continuity_exclusion_preserves_asset_evidence_only(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    df = df.drop(pd.Timestamp("2026-06-17", tz=TZ))  # analysis_start'tan SONRA bir boşluk
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == "MISSING_TRADING_SESSION"
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is None
    assert report.result.technical_output_object_ref is None


# ---------------------------------------------------------------------------
# section 46 -- OHLCV exclusion
# ---------------------------------------------------------------------------


def test_ohlcv_exclusion_preserves_asset_evidence_only(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    tampered_date = pd.Timestamp("2026-06-17", tz=TZ)  # analysis_start'tan SONRA
    df.loc[tampered_date, "Volume"] = -1
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == "INVALID_OHLCV"
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is None
    assert report.result.technical_output_object_ref is None


# ---------------------------------------------------------------------------
# section 47 -- insufficient history
# ---------------------------------------------------------------------------


def test_insufficient_history_exclusion_not_replaced_by_leading_edge(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2026-08-01", "2026-08-24")  # ~17 iş günü, MIN_HISTORY_DAYS(60) altı
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == "INSUFFICIENT_HISTORY"
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is None
    assert report.result.technical_output_object_ref is None


# ---------------------------------------------------------------------------
# section 48 -- TECHNICAL_SCORE_NONE
# ---------------------------------------------------------------------------


def test_technical_score_none_exclusion_has_all_three_evidence_refs(fake_db, authorized_setup, monkeypatch):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    monkeypatch.setattr(
        "app.engines.technical.engine.aggregate_available_scores", lambda *args, **kwargs: None
    )

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == TECHNICAL_SCORE_NONE
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is not None
    assert report.result.technical_output_object_ref is not None


# ---------------------------------------------------------------------------
# section 49 -- LEADING_EDGE_UNVERIFIED + independent reconstruction
# ---------------------------------------------------------------------------


def test_leading_edge_unverified_exclusion_has_all_three_refs_and_is_reconstructible(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2026-05-01", "2026-08-24")  # ~82 iş günü, pre-roll kanıtı YOK
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == LEADING_EDGE_UNVERIFIED
    assert report.result.technical_output_sha256 is not None  # gerçek, non-None bir skor üretildi
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is not None
    assert report.result.technical_output_object_ref is not None

    # Section 49: persisted GENİŞ (pre-roll dahil) asset snapshot'tan
    # BAĞIMSIZ olarak resolve_expected_start()'ı yeniden çalıştır --
    # AYNI LEADING_EDGE_UNVERIFIED sonucunu üretmeli.
    from app.engines.technical.history_window import HistoryValidationStatus, resolve_expected_start

    evidence_store = service._evidence_store
    raw_bytes = evidence_store.get_verified(EvidenceObjectKind.ASSET_SNAPSHOT, report.result.asset_input_sha256)
    reconstructed_df, reconstructed_symbol = deserialize_asset_snapshot(json.loads(raw_bytes))
    assert reconstructed_symbol == _REAL_FROZEN_MEMBER

    from app.engines.technical.history_window import compute_history_window

    analysis_start = compute_history_window(NOW).analysis_start
    _, reconstructed_status = resolve_expected_start(reconstructed_df, analysis_start)
    assert reconstructed_status == HistoryValidationStatus.LEADING_EDGE_UNVERIFIED


# ---------------------------------------------------------------------------
# section 50 -- coexistence precedence
# ---------------------------------------------------------------------------


def test_technical_score_none_and_leading_edge_unverified_coexistence_prefers_score_none(
    fake_db, authorized_setup, monkeypatch
):
    lock = authorized_setup
    df = _bday_df("2026-05-01", "2026-08-24")  # LEADING_EDGE_UNVERIFIED şekli
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    monkeypatch.setattr(
        "app.engines.technical.engine.aggregate_available_scores", lambda *args, **kwargs: None
    )

    report = _execute(service, lock)

    assert report.result.result_classification == AttemptResultClassification.EXCLUSION
    assert report.result.native_reason_code == TECHNICAL_SCORE_NONE
    assert report.result.asset_object_ref is not None
    assert report.result.benchmark_object_ref is not None
    assert report.result.technical_output_object_ref is not None


# ---------------------------------------------------------------------------
# section 51 -- VALID_CANDIDATE
# ---------------------------------------------------------------------------


def test_valid_candidate_full_run(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    report = _execute(service, lock)

    result = report.result
    assert result.result_classification == AttemptResultClassification.VALID_CANDIDATE
    assert result.native_reason_code is None
    assert result.config_gate_result == GateCheckResult.PASS
    assert result.methodology_gate_result == GateCheckResult.PASS
    assert result.runtime_gate_result == GateCheckResult.PASS
    assert result.universe_gate_result == GateCheckResult.PASS
    assert result.asset_object_ref is not None
    assert result.benchmark_object_ref is not None
    assert result.technical_output_object_ref is not None
    assert result.activation_lock_id == lock.activation_lock_id

    from app.research.evidence_serialization import input_snapshot_sha256_from_hashes

    assert result.input_snapshot_sha256 == input_snapshot_sha256_from_hashes(
        result.asset_input_sha256, result.benchmark_input_sha256
    )
    assert report.publish_outcome == PublishOutcome.CREATED


# ---------------------------------------------------------------------------
# section 52 -- snapshot failure (transient object-store failure)
# ---------------------------------------------------------------------------


def test_transient_evidence_store_failure_publishes_no_result(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    failing_store = _FailingEvidenceStore(
        FakeEvidenceObjectStore(),
        fail_kind=EvidenceObjectKind.BENCHMARK_SNAPSHOT,
        fail_with=ObjectStoreError("simulated transient GCS failure"),
    )
    service = _make_service(fake_db, provider, evidence_store=failing_store)

    with pytest.raises(ObjectStoreError):
        _execute(service, lock)

    assert fake_db.raw_store("technical_v1_attempt_results") == {}
    assert len(fake_db.raw_store("technical_v1_attempt_claims")) == 1


# ---------------------------------------------------------------------------
# section 53 -- provenance conflict
# ---------------------------------------------------------------------------


def test_evidence_provenance_conflict_publishes_no_result(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    failing_store = _FailingEvidenceStore(
        FakeEvidenceObjectStore(),
        fail_kind=EvidenceObjectKind.ASSET_SNAPSHOT,
        fail_with=ProvenanceConflictError("simulated content-address conflict"),
    )
    service = _make_service(fake_db, provider, evidence_store=failing_store)

    with pytest.raises(ProvenanceConflictError):
        _execute(service, lock)

    assert fake_db.raw_store("technical_v1_attempt_results") == {}
    assert len(fake_db.raw_store("technical_v1_attempt_claims")) == 1


# ---------------------------------------------------------------------------
# section 54 -- duplicate worker invocation
# ---------------------------------------------------------------------------


def test_duplicate_worker_invocation_does_not_repeat_provider_work(fake_db, authorized_setup):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    first = _execute(service, lock)
    calls_after_first = len(provider.calls)
    assert first.outcome == AttemptExecutionOutcome.RESULT_PUBLISHED
    assert calls_after_first > 0

    second = _execute(service, lock)

    assert second.outcome == AttemptExecutionOutcome.ALREADY_CLAIMED
    assert len(provider.calls) == calls_after_first  # ikinci provider fetch YOK
    assert second.result is None


def test_claim_outcome_is_claimed_on_first_success(fake_db, authorized_setup, monkeypatch):
    lock = authorized_setup
    df = _bday_df("2025-09-01", "2026-08-24")
    provider = _FakeProvider(df)
    service = _make_service(fake_db, provider)

    recorded = {}
    real_claim_attempt = TechnicalV1AttemptRepository.claim_attempt

    def spy(self, claim):
        outcome = real_claim_attempt(self, claim)
        recorded["outcome"] = outcome
        return outcome

    monkeypatch.setattr(TechnicalV1AttemptRepository, "claim_attempt", spy)

    _execute(service, lock)

    assert recorded["outcome"] == ClaimOutcome.CLAIMED
