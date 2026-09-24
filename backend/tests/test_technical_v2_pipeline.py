"""TECHNICAL V2 — sürümlü evidence pipeline: kimlik, V1/V2 ayrımı, kilit/olgu
doğrulaması, attempt/controller/manifest kimliği, dahili rotalar.

Gerçek Firestore/GCS/Yahoo YOK (sahte nesneler). Aktivasyon kilidi/olayı
OLUŞTURULMAZ; holdout başlatılmaz. Çalışan motor gerçek 1.15.0'dır (V1-dönemi
fixture'ı KULLANILMAZ).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import technical_v1_internal
from app.engines.technical.engine import ENGINE_VERSION
from app.research.activation_lock import TechnicalV1ActivationLock, compute_activation_lock_id
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_evaluation_id
from app.research.identity_gates import evaluate_config_gate
from app.research.session_manifest import derive_expected_evaluation_ids
from app.research.technical_v1_attempt_execution import AttemptExecutionOutcome, TechnicalV1AttemptExecutionService
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
from app.research.technical_v1_scoring_config_values import (
    TechnicalV1MethodologySupersededError,
    load_verified_scoring_config_hash,
)
from app.research.technical_v1_session_controller import SessionScientificFacts, TechnicalV1SessionController
from app.research.technical_versions import (
    TECHNICAL_V1_SPEC,
    TECHNICAL_V2_SPEC,
    TechnicalVersionMismatchError,
    TechnicalVersionSpec,
    assert_identity_matches_running_engine,
    identity_for_protocol_version,
    load_evaluation_identity,
    spec_for_protocol_version,
    validate_lock_identity,
    validate_scientific_facts,
)

V2 = load_evaluation_identity(TECHNICAL_V2_SPEC)
V1 = load_evaluation_identity(TECHNICAL_V1_SPEC)
T_DATE = "2026-09-22"


def _v2_lock(**overrides) -> TechnicalV1ActivationLock:
    fields = dict(
        protocol_version=V2.protocol_version,
        protocol_sha256=V2.protocol_sha256,
        freeze_manifest_sha256=V2.freeze_manifest_sha256,
        methodology_git_commit=V2.methodology_git_commit,
        authorized_methodology_source_fingerprint=V2.methodology_source_fingerprint,
        authorized_project_id="proj",
        authorized_runtime_service="svc",
        authorized_runtime_revision="rev-1",
        methodology_approval_reference=V2.methodology_git_commit,
    )
    fields.update(overrides)
    lock_id = compute_activation_lock_id(
        protocol_version=fields["protocol_version"],
        authorized_methodology_source_fingerprint=fields["authorized_methodology_source_fingerprint"],
        authorized_project_id=fields["authorized_project_id"],
        authorized_runtime_service=fields["authorized_runtime_service"],
        authorized_runtime_revision=fields["authorized_runtime_revision"],
    )
    return TechnicalV1ActivationLock(activation_lock_schema_version="technical_v1_activation_lock_v1",
                                     activation_lock_id=lock_id, **fields)


def _facts(identity=V2, **overrides) -> SessionScientificFacts:
    base = dict(methodology_git_commit=identity.methodology_git_commit,
                freeze_manifest_sha256=identity.freeze_manifest_sha256,
                engine_version=identity.engine_version, scoring_config_hash=identity.scoring_config_hash,
                E1_date="2026-09-23")
    base.update(overrides)
    return SessionScientificFacts(**base)


# ------------------------------------------------------------------ identity


def test_v2_identity_is_derived_from_locked_artifacts():
    protocol = json.loads(TECHNICAL_V2_SPEC.protocol_path.read_text(encoding="utf-8"))
    manifest = json.loads(TECHNICAL_V2_SPEC.freeze_manifest_path.read_text(encoding="utf-8"))
    assert V2.technical_version == "TECHNICAL_V2"
    assert V2.protocol_version == "TECHNICAL_V2_PROTOCOL_V1"
    assert V2.protocol_sha256 == content_sha256(protocol) == "50b5b4e336f48c4043fe6802067b14b86ad8e0beb2cc78a6d56fec8209b395b8"
    assert V2.freeze_manifest_sha256 == content_sha256(manifest) == "41d75cbb06433927d9cc164f2fad56196e6fc8864dcb5e0739bece9278ade0b3"
    assert V2.engine_version == ENGINE_VERSION == "1.15.0"
    assert V2.scoring_config_hash == V1.scoring_config_hash
    assert V2.methodology_source_fingerprint == "8fbea7ed233ba6741fa7cd07ad0fbd3b630f3e68f7ad9a244ae6a484248884e1"
    assert V2.normalized_fingerprint is True and V1.normalized_fingerprint is False


def test_spec_resolution_by_protocol_version():
    assert spec_for_protocol_version("TECHNICAL_V1_PROTOCOL_V1") is TECHNICAL_V1_SPEC
    assert spec_for_protocol_version("TECHNICAL_V2_PROTOCOL_V1") is TECHNICAL_V2_SPEC
    for bad in ("TECHNICAL_V3_PROTOCOL_V1", "", None, "technical_v2_protocol_v1"):
        with pytest.raises(TechnicalVersionMismatchError):
            spec_for_protocol_version(bad)


def test_protocol_bound_to_another_manifest_is_rejected(tmp_path):
    # V2 protokolünü V1 manifest'iyle eşlemeye çalışan sahte spec -> çapraz bağ hatası
    mixed = TechnicalVersionSpec("TECHNICAL_V2", TECHNICAL_V2_SPEC.protocol_path, TECHNICAL_V1_SPEC.freeze_manifest_path,
                                 "TECHNICAL_V2_PROTOCOL_", True)
    with pytest.raises(TechnicalVersionMismatchError):
        load_evaluation_identity(mixed)


def test_running_engine_accepts_v2_and_rejects_new_v1():
    assert_identity_matches_running_engine(V2)
    with pytest.raises(TechnicalV1MethodologySupersededError):
        assert_identity_matches_running_engine(V1)


def test_v1_historical_artifacts_remain_readable_under_engine_1_15():
    assert identity_for_protocol_version("TECHNICAL_V1_PROTOCOL_V1").engine_version == "1.14.0"
    trusted = load_verified_technical_v1_protocol(V1.protocol_sha256)
    assert trusted.protocol_version == "TECHNICAL_V1_PROTOCOL_V1" and len(trusted.frozen_symbol_list) == 100
    assert V1.freeze_manifest_sha256 == "6556f7a9c9b9eedcc4b789c861cc2e1b5b2d4a13be1be75605162f0e578bdc97"
    assert V1.protocol_sha256 == "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"


# ------------------------------------------------------------------ activation-lock identity


def test_fully_matching_v2_lock_passes_validation():
    validate_lock_identity(_v2_lock(), V2)


@pytest.mark.parametrize("override", [
    {"protocol_version": "TECHNICAL_V1_PROTOCOL_V1"},
    {"protocol_sha256": V1.protocol_sha256},
    {"freeze_manifest_sha256": V1.freeze_manifest_sha256},
    {"authorized_methodology_source_fingerprint": "f" * 64},
])
def test_v2_lock_with_wrong_identity_field_is_rejected(override):
    with pytest.raises(TechnicalVersionMismatchError):
        validate_lock_identity(_v2_lock(**override), V2)


def test_v1_lock_resolves_to_superseded_v1_identity():
    v1_lock = SimpleNamespace(protocol_version="TECHNICAL_V1_PROTOCOL_V1")
    with pytest.raises(TechnicalV1MethodologySupersededError):
        assert_identity_matches_running_engine(identity_for_protocol_version(v1_lock.protocol_version))


def test_wrong_scoring_hash_fails_v2_config_gate():
    expected = load_verified_scoring_config_hash(V2.freeze_manifest_sha256, TECHNICAL_V2_SPEC.freeze_manifest_path)
    assert expected == V2.scoring_config_hash
    assert evaluate_config_gate(expected, "0" * 64).result.value == "FAIL"
    assert evaluate_config_gate(expected, V2.scoring_config_hash).result.value == "PASS"


def test_v2_manifest_sha_cannot_load_v1_manifest_file():
    from app.research.evidence_models import ProvenanceConflictError

    with pytest.raises(ProvenanceConflictError):
        load_verified_scoring_config_hash(V2.freeze_manifest_sha256, TECHNICAL_V1_SPEC.freeze_manifest_path)


# ------------------------------------------------------------------ scientific facts


def test_v2_facts_pass_and_v1_or_wrong_facts_are_rejected():
    validate_scientific_facts(_facts(), V2)
    for bad in (_facts(identity=V1), _facts(scoring_config_hash="0" * 64), _facts(engine_version="1.14.0"),
                _facts(freeze_manifest_sha256=V1.freeze_manifest_sha256)):
        with pytest.raises(TechnicalVersionMismatchError):
            validate_scientific_facts(bad, V2)


# ------------------------------------------------------------------ attempt execution (V2)


class _NoClaimAttemptRepo:
    def claim_attempt(self, claim):
        raise AssertionError("claim_attempt çağrılmamalı")


class _LockRepo:
    def __init__(self, lock):
        self._lock = lock

    def get_verified(self, activation_lock_id):
        return SimpleNamespace(lock=self._lock) if activation_lock_id == self._lock.activation_lock_id else None


class _NoEventRepo:
    def get_verified(self, event_id):
        return None


def _attempt_service(lock) -> TechnicalV1AttemptExecutionService:
    boom = SimpleNamespace()
    return TechnicalV1AttemptExecutionService(
        activation_lock_repo=_LockRepo(lock), activation_event_repo=_NoEventRepo(), attempt_repo=_NoClaimAttemptRepo(),
        evidence_store=boom, provider=boom, config_repo=boom, benchmark_cache_repo=boom,
    )


def test_v2_attempt_identity_reaches_pre_activation_without_claim_or_io():
    lock = _v2_lock()
    report = _attempt_service(lock).execute_attempt(
        activation_lock_id=lock.activation_lock_id, protocol_version=V2.protocol_version,
        T_session_date=T_DATE, symbol="AKBNK", attempt_number=1)
    assert report.outcome == AttemptExecutionOutcome.PRE_ACTIVATION


def test_v2_attempt_rejects_request_protocol_version_mismatch_before_claim():
    from app.research.evidence_models import ProvenanceConflictError

    lock = _v2_lock()
    with pytest.raises(ProvenanceConflictError):
        _attempt_service(lock).execute_attempt(
            activation_lock_id=lock.activation_lock_id, protocol_version="TECHNICAL_V1_PROTOCOL_V1",
            T_session_date=T_DATE, symbol="AKBNK", attempt_number=1)


def test_v2_attempt_rejects_wrong_fingerprint_lock_before_claim():
    lock = _v2_lock(authorized_methodology_source_fingerprint="f" * 64)
    with pytest.raises(TechnicalVersionMismatchError):
        _attempt_service(lock).execute_attempt(
            activation_lock_id=lock.activation_lock_id, protocol_version=V2.protocol_version,
            T_session_date=T_DATE, symbol="AKBNK", attempt_number=1)


def test_new_v1_attempt_is_rejected_before_claim_under_engine_1_15():
    v1_lock = _v2_lock(protocol_version=V1.protocol_version, protocol_sha256=V1.protocol_sha256,
                       freeze_manifest_sha256=V1.freeze_manifest_sha256)
    with pytest.raises(TechnicalV1MethodologySupersededError):
        _attempt_service(v1_lock).execute_attempt(
            activation_lock_id=v1_lock.activation_lock_id, protocol_version=V1.protocol_version,
            T_session_date=T_DATE, symbol="AKBNK", attempt_number=1)


# ------------------------------------------------------------------ controller (V2)


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"{name} çağrılmamalı")


class _EvaluationRepo:
    def __init__(self, verified_ids=()):
        self._ids = set(verified_ids)
        self.requested: list[str] = []

    def get_verified(self, evaluation_id):
        self.requested.append(evaluation_id)
        return None  # V2 kimlikleri için hiçbir doğrulanmış final yok


def _controller(identity=V2, evaluation_repo=None, trusted_protocol=None) -> TechnicalV1SessionController:
    trusted = trusted_protocol or load_verified_technical_v1_protocol(identity.protocol_sha256, identity.spec.protocol_path)
    return TechnicalV1SessionController(
        trusted_protocol=trusted, attempt_execution_service=_Forbidden(), attempt2_orchestrator=_Forbidden(),
        finalizer=_Forbidden(), session_run_repo=_Forbidden(), session_manifest_repo=_Forbidden(),
        evaluation_repo=evaluation_repo or _Forbidden(), evaluation_identity=identity,
    )


def test_controller_rejects_trusted_protocol_of_another_version():
    v1_trusted = load_verified_technical_v1_protocol(V1.protocol_sha256)
    with pytest.raises(TechnicalVersionMismatchError):
        _controller(trusted_protocol=v1_trusted)


@pytest.mark.parametrize("phase", ["attempt1", "attempt2", "finalize", "manifest"])
def test_v2_controller_rejects_v1_protocol_version_before_any_symbol(phase):
    from datetime import datetime, timezone

    c = _controller()
    now = datetime(2026, 9, 23, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(TechnicalVersionMismatchError):
        if phase == "attempt1":
            c.run_attempt1_phase(activation_lock_id="a" * 64, protocol_version=V1.protocol_version, T_session_date=T_DATE, now=now)
        elif phase == "attempt2":
            c.run_attempt2_phase(activation_lock_id="a" * 64, protocol_version=V1.protocol_version, T_session_date=T_DATE,
                                 facts=_facts(), now=now)
        elif phase == "finalize":
            c.run_finalization_phase(protocol_version=V1.protocol_version, T_session_date=T_DATE, facts=_facts(), now=now)
        else:
            c.build_session_manifest_if_complete(protocol_version=V1.protocol_version, T_session_date=T_DATE, facts=_facts())


@pytest.mark.parametrize("phase", ["attempt2", "finalize", "manifest"])
def test_v2_controller_rejects_v1_facts_before_any_symbol(phase):
    from datetime import datetime, timezone

    c = _controller()
    now = datetime(2026, 9, 23, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(TechnicalVersionMismatchError):
        if phase == "attempt2":
            c.run_attempt2_phase(activation_lock_id="a" * 64, protocol_version=V2.protocol_version, T_session_date=T_DATE,
                                 facts=_facts(identity=V1), now=now)
        elif phase == "finalize":
            c.run_finalization_phase(protocol_version=V2.protocol_version, T_session_date=T_DATE, facts=_facts(identity=V1), now=now)
        else:
            c.build_session_manifest_if_complete(protocol_version=V2.protocol_version, T_session_date=T_DATE,
                                                 facts=_facts(identity=V1))


def test_v2_manifest_denominator_is_exact_frozen_100_and_v1_finals_cannot_satisfy_it():
    v1_ids = derive_expected_evaluation_ids(V1.protocol_version, T_DATE, load_verified_technical_v1_protocol(V1.protocol_sha256).frozen_symbol_list)
    repo = _EvaluationRepo(verified_ids=v1_ids)
    result = _controller(evaluation_repo=repo).build_session_manifest_if_complete(
        protocol_version=V2.protocol_version, T_session_date=T_DATE, facts=_facts())
    acc = result.accounting
    assert acc.expected_symbol_count == 100
    assert len(repo.requested) == 100 and set(repo.requested).isdisjoint(v1_ids)
    assert acc.verified_count == 0 and acc.absent_count == 100
    assert acc.status.value != "COMPLETE" and result.manifest is None and result.create_outcome is None


def test_v1_and_v2_evaluation_ids_never_collide():
    symbols = load_verified_technical_v1_protocol(V2.protocol_sha256, TECHNICAL_V2_SPEC.protocol_path).frozen_symbol_list
    v2_ids = derive_expected_evaluation_ids(V2.protocol_version, T_DATE, symbols)
    v1_ids = derive_expected_evaluation_ids(V1.protocol_version, T_DATE, symbols)
    assert len(set(v2_ids)) == 100 and set(v2_ids).isdisjoint(v1_ids)
    assert compute_evaluation_id(V2.protocol_version, T_DATE, "AKBNK") != compute_evaluation_id(V1.protocol_version, T_DATE, "AKBNK")


# ------------------------------------------------------------------ internal routes

_SECRET = "test-technical-secret"


@pytest.fixture
def route_client(monkeypatch):
    monkeypatch.setattr(technical_v1_internal, "TECHNICAL_V1_JOB_SECRET", _SECRET)
    app = FastAPI()
    app.include_router(technical_v1_internal.router)
    app.include_router(technical_v1_internal.router_v2)
    return TestClient(app)


def _body(identity, with_facts=True):
    body = {"protocol_version": identity.protocol_version, "protocol_sha256": identity.protocol_sha256,
            "T_session_date": T_DATE, "activation_lock_id": "a" * 64}
    if with_facts:
        body.update(dataclasses.asdict(_facts(identity=identity)))
    return body


@pytest.mark.parametrize("phase", ["attempt1", "attempt2", "finalize", "manifest"])
@pytest.mark.parametrize("headers", [{}, {"x-job-secret": "wrong"}])
def test_v2_routes_require_job_secret(route_client, phase, headers):
    called = []
    route_client.app.dependency_overrides[technical_v1_internal.get_v2_controller_factory] = lambda: (lambda sha: called.append(sha))
    r = route_client.post(f"/internal/technical-v2/{phase}", json=_body(V2), headers=headers)
    assert r.status_code == 403 and called == []


@pytest.mark.parametrize("phase", ["attempt1", "attempt2", "finalize", "manifest"])
def test_v2_routes_reject_v1_protocol_and_v1_routes_reject_v2_protocol(route_client, phase):
    called = []
    fake = lambda: (lambda sha: called.append(sha))  # noqa: E731
    route_client.app.dependency_overrides[technical_v1_internal.get_v2_controller_factory] = fake
    route_client.app.dependency_overrides[technical_v1_internal.get_controller_factory] = fake
    h = {"x-job-secret": _SECRET}
    assert route_client.post(f"/internal/technical-v2/{phase}", json=_body(V1), headers=h).status_code == 422
    assert route_client.post(f"/internal/technical-v1/{phase}", json=_body(V2), headers=h).status_code == 422
    assert called == []


def test_v2_route_uses_v2_controller_factory_only(route_client):
    seen = {}

    class _Controller:
        def run_attempt1_phase(self, **kw):
            seen.update(kw)
            return SimpleNamespace(outcomes=(), processed=0)

    route_client.app.dependency_overrides[technical_v1_internal.get_v2_controller_factory] = lambda: (lambda sha: _Controller())
    route_client.app.dependency_overrides[technical_v1_internal.get_controller_factory] = lambda: (
        lambda sha: pytest.fail("V1 fabrikası kullanılmamalı"))
    r = route_client.post("/internal/technical-v2/attempt1", json=_body(V2, with_facts=False), headers={"x-job-secret": _SECRET})
    assert r.status_code == 200 and seen["protocol_version"] == V2.protocol_version


def test_real_v2_factory_passes_identity_then_stops_at_missing_bucket(route_client, monkeypatch):
    from app.research import technical_v1_production

    monkeypatch.setattr(technical_v1_production, "TECHNICAL_V1_EVIDENCE_BUCKET", None)
    monkeypatch.setattr(technical_v1_production, "get_firestore_client",
                        lambda: pytest.fail("Firestore client oluşturulmamalı"))
    r = route_client.post("/internal/technical-v2/attempt1", json=_body(V2, with_facts=False), headers={"x-job-secret": _SECRET})
    assert r.status_code == 503  # kimlik geçti, bucket yapılandırılmamış -> hiçbir I/O yok


def test_real_v1_factory_is_rejected_as_superseded(route_client, monkeypatch):
    from app.research import technical_v1_production

    monkeypatch.setattr(technical_v1_production, "get_firestore_client",
                        lambda: pytest.fail("Firestore client oluşturulmamalı"))
    r = route_client.post("/internal/technical-v1/attempt1", json=_body(V1, with_facts=False), headers={"x-job-secret": _SECRET})
    assert r.status_code == 409


def test_real_v2_factory_rejects_v1_protocol_sha(monkeypatch):
    from app.research import technical_v1_production

    with pytest.raises(TechnicalVersionMismatchError):
        technical_v1_production.build_session_controller(protocol_sha256=V1.protocol_sha256, technical_version="TECHNICAL_V2")


def test_no_activation_route_exists():
    from app.main import app

    paths = app.openapi()["paths"]
    assert not [p for p in paths if "activ" in p.lower()]
    assert {p for p in paths if p.startswith("/internal/technical-v2/")} == {
        "/internal/technical-v2/attempt1", "/internal/technical-v2/attempt2",
        "/internal/technical-v2/finalize", "/internal/technical-v2/manifest"}


# ------------------------------------------------------------------ V1 vs V2 numeric parity


def test_numeric_parity_between_v1_and_v2_classifier_semantics(monkeypatch):
    """Aynı girdiyle 1.14.0 sınıflandırıcı semantiği (hacim kapılı) ile 1.15.0
    arasında YALNIZCA signal_class/horizon farklılaşabilir."""
    import numpy as np
    import pandas as pd

    import app.engines.technical.engine as eng
    from app.engines.technical.scoring import DEFAULT_TECHNICAL_FAMILY_WEIGHTS, compute_scoring_config_hash
    from app.engines.technical.signal_classifier import classify_signal

    def classify_1_14(inputs):
        forced = dataclasses.replace(inputs, relative_volume_class="HIGH")
        if classify_signal(forced) == "STRONG_BULLISH_INITIATION" and inputs.relative_volume_class not in ("HIGH", "VERY_HIGH"):
            return "BULLISH_CONFIRMED"
        return classify_signal(inputs)

    rng = np.random.default_rng(4)
    n = 160
    close = 100 * np.exp(np.cumsum(0.006 + rng.normal(0, 0.012, n)))
    idx = pd.bdate_range("2024-01-02", periods=n).tz_localize("Europe/Istanbul")
    df = pd.DataFrame({"Open": close * 0.998, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                       "Volume": rng.uniform(9e5, 1.1e6, n)}, index=idx)
    bench = pd.Series(np.linspace(100, 110, n), index=[ts.date() for ts in idx])
    weights = {"rsi": 0.1667, "macd": 0.1667, "trend": 0.1667, "bollinger": 0.1667, "momentum": 0.1667,
               "ema_slope": 0.2, "roc": 0.1665}
    fw = dict(DEFAULT_TECHNICAL_FAMILY_WEIGHTS)
    h = compute_scoring_config_hash(weights, fw)
    from datetime import datetime, timezone

    now = datetime(2024, 9, 1, tzinfo=timezone.utc)
    new = eng.compute_technical_analysis(df, "TST", weights, fw, h, "PARITY", {}, benchmark_close_series=bench, now=now)
    monkeypatch.setattr(eng, "classify_signal", classify_1_14)
    old = eng.compute_technical_analysis(df, "TST", weights, fw, h, "PARITY", {}, benchmark_close_series=bench, now=now)
    for field in ("technical_score", "components", "confidence", "relative_volume_class", "breakout_event_id",
                  "market_structure", "scoring_config_hash", "engine_version"):
        assert getattr(new, field) == getattr(old, field), field
    allowed = {("BULLISH_CONFIRMED", "STRONG_BULLISH_INITIATION")}
    assert new.signal_class == old.signal_class or (old.signal_class, new.signal_class) in allowed
