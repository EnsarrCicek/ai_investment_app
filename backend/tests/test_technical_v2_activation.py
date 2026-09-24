"""TECHNICAL V2-R1 — aktivasyon orkestrasyonu (yerel, sahte Firestore).

Sahte veritabanı yalnızca get/create/sorgu destekler; set/update/delete/batch
çağrısı testi düşürür. Bu testler MANTIĞI doğrular; gerçek Firestore
eşzamanlılık davranışının kanıtı DEĞİLDİR (create precondition'ı sahte
AlreadyExists ile taklit edilir).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import AlreadyExists

from app.repositories.technical_v1_activation_event_repository import COLLECTION as EVENTS
from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
from app.repositories.technical_v1_activation_lock_repository import COLLECTION as LOCKS
from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
from app.research import technical_v2_activation as act
from app.research.activation_lock import compute_runtime_fingerprint
from app.research.technical_v2_readiness import FirestoreReadOnlyActivationStateReader
from app.research.technical_versions import TECHNICAL_V2_SPEC, load_evaluation_identity

V2 = load_evaluation_identity(TECHNICAL_V2_SPEC)
PROJECT, SERVICE, REVISION, OTHER_REVISION = "ai-investment-app-2026", "ai-investment-backend", "ai-investment-backend-00042-abc", "ai-investment-backend-00043-def"
GIT = "8180ed8dd484dccafe1fd9eceda32a33a92f7d92"
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
BAD_HASH = "0" * 64


# ------------------------------------------------------------------ fake Firestore (create-only)


class _Snap:
    def __init__(self, doc_id, data, create_time):
        self.id, self._data, self.create_time = doc_id, data, create_time
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, db, coll, doc_id):
        self._db, self._coll, self._id = db, coll, doc_id

    def get(self):
        data, ct = self._db.store.get(self._coll, {}).get(self._id, (None, None))
        return _Snap(self._id, data, ct)

    def create(self, data):
        self._db.create_calls.append((self._coll, self._id))
        hook = self._db.before_create.pop((self._coll, self._id), None)
        if hook:
            hook()
        failure = self._db.fail_next_create.pop(self._coll, None)
        if failure:
            raise failure
        coll = self._db.store.setdefault(self._coll, {})
        if self._id in coll:
            raise AlreadyExists(f"{self._coll}/{self._id}")
        coll[self._id] = (dict(data), self._db.server_create_time)

    def __getattr__(self, name):
        raise AssertionError(f"yasak yazma yolu: document.{name}")


class _Query:
    def __init__(self, db, coll):
        self._db, self._coll, self._filters = db, coll, []

    def where(self, field, op, value):
        self._filters.append((field, value))
        return self

    def limit(self, n):
        return self

    def document(self, doc_id):
        return _DocRef(self._db, self._coll, doc_id)

    def get(self):
        if self._coll in self._db.fail_query:
            raise RuntimeError(f"query failed: {self._coll}")
        rows = self._db.store.get(self._coll, {})
        return [_Snap(i, d, ct) for i, (d, ct) in rows.items() if all(d.get(f) == v for f, v in self._filters)]

    def __getattr__(self, name):
        raise AssertionError(f"yasak yazma yolu: collection.{name}")


class _Db:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.create_calls: list[tuple] = []
        self.fail_next_create: dict[str, Exception] = {}
        self.before_create: dict[tuple, callable] = {}
        self.fail_query: set[str] = set()
        self.server_create_time = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)

    def collection(self, name):
        return _Query(self, name)

    def __getattr__(self, name):
        raise AssertionError(f"yasak yazma yolu: db.{name}")


# ------------------------------------------------------------------ helpers


def _deps(db, *, observed_revision, observed_project=PROJECT, live_scoring=None, lock_repo=None):
    return dict(
        lock_repo=lock_repo or TechnicalV1ActivationLockRepository(db=db),
        event_repo=TechnicalV1ActivationEventRepository(db=db),
        state_reader=FirestoreReadOnlyActivationStateReader(db),
        live_scoring_config_hash_reader=live_scoring or (lambda: V2.scoring_config_hash),
        runtime_identity_reader=lambda: {"service": SERVICE, "revision": observed_revision},
        runtime_fingerprint_observer=lambda: compute_runtime_fingerprint(observed_project, SERVICE, observed_revision),
    )


def _activate(db, *, revision=REVISION, observed_revision=None, git=GIT, live_scoring=None, lock_repo=None, clock=None):
    return act._activate(
        expected_project_id=PROJECT, expected_runtime_service=SERVICE, expected_runtime_revision=revision,
        methodology_git_commit=git, methodology_approval_reference=git, clock=clock or (lambda: NOW),
        **_deps(db, observed_revision=observed_revision or revision, live_scoring=live_scoring, lock_repo=lock_repo),
    )


def _authorize(db, *, revision=OTHER_REVISION, observed_revision=None, project=PROJECT, git=GIT, live_scoring=None):
    return act._authorize_revision(
        expected_project_id=project, expected_runtime_service=SERVICE, expected_runtime_revision=revision,
        methodology_git_commit=git, methodology_approval_reference=git,
        **_deps(db, observed_revision=observed_revision or revision, observed_project=project, live_scoring=live_scoring),
    )


def _attempt_service(db):
    from types import SimpleNamespace

    from app.research.technical_v1_attempt_execution import TechnicalV1AttemptExecutionService

    nothing = SimpleNamespace()
    return TechnicalV1AttemptExecutionService(
        activation_lock_repo=nothing, activation_event_repo=TechnicalV1ActivationEventRepository(db=db),
        attempt_repo=nothing, evidence_store=nothing, provider=nothing, config_repo=nothing, benchmark_cache_repo=nothing)


def _lock(db, lock_id):
    return TechnicalV1ActivationLockRepository(db=db).get_verified(lock_id).lock


# ------------------------------------------------------------------ zero writes on failure


def test_failed_readiness_gate_performs_zero_writes():
    db = _Db()
    r = _activate(db, live_scoring=lambda: BAD_HASH)
    assert r.status == act.BLOCKED and "PRODUCTION_READINESS_FAILED" in r.reason_codes
    assert "LIVE_SCORING_CONFIG_MISMATCH" in r.readiness_failed_gates
    assert db.create_calls == [] and r.writes_attempted == 0


def test_unreadable_live_config_performs_zero_writes():
    db = _Db()

    def boom():
        raise RuntimeError("unavailable")

    r = _activate(db, live_scoring=boom)
    assert r.status == act.BLOCKED and db.create_calls == []


@pytest.mark.parametrize("kwargs, code", [
    ({"observed_revision": OTHER_REVISION}, "RUNTIME_IDENTITY_NOT_AUTHORIZED_TARGET"),
    ({"git": "not-a-git-sha"}, "INVALID_AUTHORIZATION_INPUT"),
])
def test_wrong_identity_or_authorization_input_performs_zero_writes(kwargs, code):
    db = _Db()
    r = _activate(db, **kwargs)
    assert r.status == act.BLOCKED and code in r.reason_codes and db.create_calls == []


def test_engine_mismatch_performs_zero_writes(monkeypatch):
    import app.engines.technical.engine as eng

    monkeypatch.setattr(eng, "ENGINE_VERSION", "1.14.0")
    db = _Db()
    r = _activate(db)
    assert r.status == act.BLOCKED and "V2_IDENTITY_OR_ENGINE_MISMATCH" in r.reason_codes and db.create_calls == []


def test_unobservable_runtime_performs_zero_writes():
    db = _Db()

    def missing():
        raise RuntimeError("K_SERVICE eksik")

    r = act._activate(
        expected_project_id=PROJECT, expected_runtime_service=SERVICE, expected_runtime_revision=REVISION,
        methodology_git_commit=GIT, methodology_approval_reference=GIT,
        lock_repo=TechnicalV1ActivationLockRepository(db=db), event_repo=TechnicalV1ActivationEventRepository(db=db),
        state_reader=FirestoreReadOnlyActivationStateReader(db), live_scoring_config_hash_reader=lambda: V2.scoring_config_hash,
        runtime_identity_reader=missing, runtime_fingerprint_observer=missing)
    assert r.status == act.BLOCKED and "RUNTIME_IDENTITY_UNOBSERVABLE" in r.reason_codes and db.create_calls == []


def test_existing_v2_evidence_blocks_with_zero_writes():
    db = _Db()
    db.store["technical_v1_attempt_claims"] = {"x": ({"protocol_version": V2.protocol_version}, None)}
    r = _activate(db)
    assert r.status == act.BLOCKED and "NO_EVIDENCE_COLLECTION_RUNNING" in r.readiness_failed_gates and db.create_calls == []


def test_activation_blocked_before_writes_when_holdout_start_undeterminable():
    db = _Db()
    r = _activate(db, clock=lambda: datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc))  # 2027 takvimi yok
    assert r.status == act.BLOCKED and "HOLDOUT_START_UNDETERMINABLE" in r.reason_codes and db.create_calls == []


# ------------------------------------------------------------------ success + idempotent repeat


def test_first_activation_writes_lock_then_initial_event_via_atomic_create():
    db = _Db()
    r = _activate(db)
    assert r.status == act.ACTIVATED, r
    assert (r.lock_outcome, r.event_outcome) == ("CREATED", "CREATED")
    assert db.create_calls == [(LOCKS, r.activation_lock_id), (EVENTS, r.activation_event_id)]
    event_doc = db.store[EVENTS][r.activation_event_id][0]
    lock_doc = db.store[LOCKS][r.activation_lock_id][0]
    assert event_doc["activation_lock_id"] == r.activation_lock_id and event_doc["protocol_version"] == V2.protocol_version
    assert lock_doc["freeze_manifest_sha256"] == V2.freeze_manifest_sha256
    assert lock_doc["authorized_methodology_source_fingerprint"] == V2.methodology_source_fingerprint
    # sahte create_time 2026-10-01 08:00 IST -> o günün 10:00 açılışı strictly-after
    assert r.initial_event_create_time_observed == "2026-10-01T05:00:00+00:00"
    assert r.effective_holdout_start == "2026-10-01" and r.readiness_evaluated is True


def test_same_request_repeat_is_already_activated_with_zero_writes():
    db = _Db()
    first = _activate(db)
    calls = list(db.create_calls)
    again = _activate(db)
    assert again.status == act.ALREADY_ACTIVATED and again.activation_lock_id == first.activation_lock_id
    assert db.create_calls == calls
    # yalnızca mevcut kaydı bildirir: readiness değerlendirilmez, başlangıç kaymaz
    assert again.readiness_evaluated is False and again.readiness_failed_gates == ()
    assert again.effective_holdout_start == first.effective_holdout_start == "2026-10-01"


def test_already_activated_does_not_claim_current_eligibility():
    db = _Db()
    _activate(db)
    again = _activate(db, live_scoring=lambda: BAD_HASH)  # config şu an bozuk olsa bile yalnızca kayıt raporlanır
    assert again.status == act.ALREADY_ACTIVATED and again.readiness_evaluated is False
    assert any("NOT re-evaluated" in n for n in again.notes)


def test_conflicting_request_after_activation_is_blocked_not_idempotent():
    db = _Db()
    _activate(db)
    calls = list(db.create_calls)
    other = _activate(db, revision=OTHER_REVISION)
    assert other.status == act.BLOCKED and "INITIAL_EVENT_BINDS_ANOTHER_LOCK" in other.reason_codes
    assert db.create_calls == calls


# ------------------------------------------------------------------ partial write + recovery


def test_partial_lock_without_event_is_recovered_only_by_same_request():
    db = _Db()
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    partial = _activate(db)
    assert partial.status == act.BLOCKED and act.PARTIAL_LOCK_WITHOUT_EVENT in partial.reason_codes
    assert partial.activation_lock_id in db.store[LOCKS] and EVENTS not in db.store

    # farklı bir istek kısmi durumu devralamaz
    before = list(db.create_calls)
    other = _activate(db, revision=OTHER_REVISION)
    assert other.status == act.BLOCKED and "OTHER_V2_ACTIVATION_LOCK_PRESENT" in other.reason_codes
    assert db.create_calls == before

    # aynı istek kurtarır: kilit yeniden yazılmaz, yalnızca olay
    recovered = _activate(db)
    assert recovered.status == act.ACTIVATED and recovered.recovered_partial_state is True
    assert recovered.lock_outcome == "PREEXISTING_VERIFIED" and recovered.event_outcome == "CREATED"
    assert db.create_calls[len(before):] == [(EVENTS, recovered.activation_event_id)]


@pytest.mark.parametrize("kwargs, code", [
    ({"live_scoring": lambda: BAD_HASH}, "PRODUCTION_READINESS_FAILED"),
    ({"observed_revision": OTHER_REVISION}, "RUNTIME_IDENTITY_NOT_AUTHORIZED_TARGET"),
])
def test_partial_recovery_does_not_skip_config_or_runtime_checks(kwargs, code):
    db = _Db()
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    _activate(db)
    before = list(db.create_calls)
    r = _activate(db, **kwargs)
    assert r.status == act.BLOCKED and code in r.reason_codes and db.create_calls == before


def test_partial_recovery_does_not_skip_methodology_check(monkeypatch):
    import app.engines.technical.engine as eng

    db = _Db()
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    _activate(db)
    before = list(db.create_calls)
    monkeypatch.setattr(eng, "ENGINE_VERSION", "1.14.0")
    r = _activate(db)
    assert r.status == act.BLOCKED and "V2_IDENTITY_OR_ENGINE_MISMATCH" in r.reason_codes and db.create_calls == before


def test_concurrent_different_candidates_only_one_initial_event_wins_and_nothing_is_deleted():
    db = _Db()
    winner = {}

    def other_request_completes_first():
        winner["r"] = _activate(db, revision=OTHER_REVISION)

    # B'nin kilit create'inden hemen önce A tamamlanır (yarış penceresi)
    from app.research.activation_lock import compute_activation_lock_id

    b_lock_id = compute_activation_lock_id(
        protocol_version=V2.protocol_version, authorized_methodology_source_fingerprint=V2.methodology_source_fingerprint,
        authorized_project_id=PROJECT, authorized_runtime_service=SERVICE, authorized_runtime_revision=REVISION)
    db.before_create[(LOCKS, b_lock_id)] = other_request_completes_first
    loser = _activate(db)
    assert winner["r"].status == act.ACTIVATED
    assert loser.status == act.BLOCKED and "INITIAL_EVENT_CONFLICT" in loser.reason_codes
    event_doc = db.store[EVENTS][winner["r"].activation_event_id][0]
    assert event_doc["activation_lock_id"] == winner["r"].activation_lock_id  # kazananın olayı değişmedi
    assert b_lock_id in db.store[LOCKS]  # yetkisiz kalan kilit silinmedi
    assert _attempt_service(db)._find_authorizing_event(_lock(db, b_lock_id)) is None  # ve hiçbir şey yetkilendirmez


def test_existing_candidate_lock_with_different_content_is_rejected():
    db = _Db()
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    partial = _activate(db)
    data, ct = db.store[LOCKS][partial.activation_lock_id]
    db.store[LOCKS][partial.activation_lock_id] = ({**data, "methodology_approval_reference": "f" * 40}, ct)
    before = list(db.create_calls)
    r = _activate(db)
    assert r.status == act.BLOCKED and db.create_calls == before


# ------------------------------------------------------------------ entry point trust boundary


def test_public_entry_accepts_only_authorization_inputs():
    expected = ["expected_project_id", "expected_runtime_service", "expected_runtime_revision",
                "methodology_git_commit", "methodology_approval_reference"]
    assert list(inspect.signature(act.run_technical_v2_activation).parameters) == expected
    assert list(inspect.signature(act.run_technical_v2_revision_authorization).parameters) == expected


def test_public_entry_fails_closed_without_firestore(monkeypatch):
    import app.core.firebase as fb

    def no_client():
        raise RuntimeError("no credentials")

    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setattr(fb, "get_firestore_client", no_client)
    r = act.run_technical_v2_activation(expected_project_id=PROJECT, expected_runtime_service=SERVICE,
                                        expected_runtime_revision=REVISION, methodology_git_commit=GIT,
                                        methodology_approval_reference=GIT)
    assert r.status == act.BLOCKED and "FIRESTORE_CLIENT_UNAVAILABLE" in r.reason_codes


class _ClientWithProject:
    def __init__(self, project):
        self.project = project

    def collection(self, *_a):
        raise AssertionError("proje tutarsızken Firestore'a dokunulmamalı")


@pytest.mark.parametrize("entry", ["run_technical_v2_activation", "run_technical_v2_revision_authorization"])
@pytest.mark.parametrize("env_project, client_project, code", [
    (None, PROJECT, "RUNTIME_PROJECT_ID_NOT_EXPLICIT"),  # config'in sessiz varsayılanı kabul edilmez
    ("other-project", PROJECT, "RUNTIME_PROJECT_ID_MISMATCH"),
    (PROJECT, "other-project", "FIRESTORE_CLIENT_PROJECT_MISMATCH"),
])
def test_public_entries_block_before_any_io_on_project_identity_mismatch(monkeypatch, entry, env_project, client_project, code):
    import app.core.firebase as fb

    if env_project is None:
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    else:
        monkeypatch.setenv("FIREBASE_PROJECT_ID", env_project)
    monkeypatch.setattr(fb, "get_firestore_client", lambda: _ClientWithProject(client_project))
    r = getattr(act, entry)(expected_project_id=PROJECT, expected_runtime_service=SERVICE,
                            expected_runtime_revision=REVISION, methodology_git_commit=GIT,
                            methodology_approval_reference=GIT)
    assert r.status == act.BLOCKED and r.reason_codes == (code,) and r.writes_attempted == 0


def test_event_repository_rejects_v1_event_under_engine_1_15_before_any_io():
    from app.research.activation_event import build_initial_activation_event
    from app.research.technical_v1_scoring_config_values import TechnicalV1MethodologySupersededError

    class _NoDb:
        def collection(self, *_a):
            raise AssertionError("Firestore'a dokunulmamalı")

    event = build_initial_activation_event(protocol_version="TECHNICAL_V1_PROTOCOL_V1", activation_lock_id="a" * 64)
    with pytest.raises(TechnicalV1MethodologySupersededError):
        TechnicalV1ActivationEventRepository(db=_NoDb()).create(event)


def test_event_repository_rejects_unknown_protocol_version_before_any_io():
    from app.research.activation_event import build_initial_activation_event
    from app.research.technical_versions import TechnicalVersionMismatchError

    class _NoDb:
        def collection(self, *_a):
            raise AssertionError("Firestore'a dokunulmamalı")

    event = build_initial_activation_event(protocol_version="TECHNICAL_V9_PROTOCOL_V1", activation_lock_id="a" * 64)
    with pytest.raises(TechnicalVersionMismatchError):
        TechnicalV1ActivationEventRepository(db=_NoDb()).create(event)


def test_activation_output_is_recognized_by_attempt_execution_contract():
    db = _Db()
    r = _activate(db)
    event = _attempt_service(db)._find_authorizing_event(_lock(db, r.activation_lock_id))
    assert event is not None and event.activation_lock_id == r.activation_lock_id


# ------------------------------------------------------------------ revision transition (LOCK_AUTHORIZED)


def test_revision_authorization_before_activation_is_blocked_with_zero_writes():
    db = _Db()
    r = _authorize(db)
    assert r.status == act.BLOCKED and "NOT_ACTIVATED" in r.reason_codes and db.create_calls == []


def test_revision_authorization_writes_lock_and_event_without_touching_initial():
    db = _Db()
    first = _activate(db)
    initial_before = db.store[EVENTS][first.activation_event_id]
    r = _authorize(db)
    assert r.status == act.AUTHORIZED, r
    assert r.readiness_evaluated is True and (r.lock_outcome, r.event_outcome) == ("CREATED", "CREATED")
    assert db.create_calls[-2:] == [(LOCKS, r.activation_lock_id), (EVENTS, r.activation_event_id)]
    assert db.store[EVENTS][first.activation_event_id] == initial_before  # INITIAL aynen
    assert r.effective_holdout_start == first.effective_holdout_start  # başlangıç kaymadı
    doc = db.store[EVENTS][r.activation_event_id][0]
    assert doc["event_type"] == "LOCK_AUTHORIZED" and doc["activation_lock_id"] == r.activation_lock_id
    svc = _attempt_service(db)
    assert svc._find_authorizing_event(_lock(db, r.activation_lock_id)).event_type.value == "LOCK_AUTHORIZED"
    assert svc._find_authorizing_event(_lock(db, first.activation_lock_id)) is not None  # önceki kilit yetkili kalır


def test_revision_authorization_repeat_reports_existing_record_with_zero_writes():
    db = _Db()
    _activate(db)
    first = _authorize(db)
    calls = list(db.create_calls)
    again = _authorize(db, live_scoring=lambda: BAD_HASH)
    assert again.status == act.ALREADY_AUTHORIZED and again.activation_lock_id == first.activation_lock_id
    assert again.readiness_evaluated is False and db.create_calls == calls
    assert again.effective_holdout_start == first.effective_holdout_start


def test_different_target_revisions_each_need_their_own_authorization():
    db = _Db()
    _activate(db)
    a = _authorize(db, revision=OTHER_REVISION)
    b = _authorize(db, revision="ai-investment-backend-00044-ghi")
    assert a.status == b.status == act.AUTHORIZED and a.activation_lock_id != b.activation_lock_id
    assert a.effective_holdout_start == b.effective_holdout_start


def test_revision_authorization_of_the_initial_lock_is_rejected():
    db = _Db()
    _activate(db)
    before = list(db.create_calls)
    r = _authorize(db, revision=REVISION)
    assert r.status == act.BLOCKED and "CANDIDATE_IS_INITIAL_LOCK" in r.reason_codes and db.create_calls == before


@pytest.mark.parametrize("kwargs, code", [
    ({"observed_revision": "ai-investment-backend-00099-zzz"}, "RUNTIME_IDENTITY_NOT_AUTHORIZED_TARGET"),
    ({"project": "other-project"}, "NOT_A_REVISION_TRANSITION_OF_INITIAL_LOCK"),
    ({"live_scoring": lambda: BAD_HASH}, "PRODUCTION_READINESS_FAILED"),
    ({"git": "not-a-git-sha"}, "INVALID_AUTHORIZATION_INPUT"),
])
def test_revision_authorization_mismatch_is_blocked_with_zero_writes(kwargs, code):
    db = _Db()
    _activate(db)
    before = list(db.create_calls)
    r = _authorize(db, **kwargs)
    assert r.status == act.BLOCKED and code in r.reason_codes and db.create_calls == before


def test_unauthorized_new_revision_lock_is_pre_activation_for_attempts():
    db = _Db()
    _activate(db)
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    partial = _authorize(db)
    assert partial.status == act.BLOCKED and act.PARTIAL_LOCK_WITHOUT_EVENT in partial.reason_codes
    assert _attempt_service(db)._find_authorizing_event(_lock(db, partial.activation_lock_id)) is None


def test_revision_authorization_partial_recovery_completes_only_the_event():
    db = _Db()
    _activate(db)
    db.fail_next_create[EVENTS] = RuntimeError("transient")
    _authorize(db)
    before = list(db.create_calls)
    r = _authorize(db)
    assert r.status == act.AUTHORIZED and r.recovered_partial_state is True and r.lock_outcome == "PREEXISTING_VERIFIED"
    assert db.create_calls[len(before):] == [(EVENTS, r.activation_event_id)]


CLAIMS = "technical_v1_attempt_claims"


@pytest.mark.parametrize("failing_collection", [LOCKS, EVENTS, CLAIMS])
@pytest.mark.parametrize("path", ["partial_recovery", "revision"])
def test_unreadable_lock_event_or_evidence_state_is_not_tolerated(path, failing_collection):
    """Hoş görülen kapılar yalnızca OKUNMUŞ PRESENT/ABSENT durumlar içindir;
    sorgu hatası (UNKNOWN) aynı kapı koduna düşse bile yazma yapılmaz."""
    db = _Db()
    if path == "partial_recovery":
        db.fail_next_create[EVENTS] = RuntimeError("transient")
        _activate(db)
        run = _activate
    else:
        _activate(db)
        run = _authorize
    before = list(db.create_calls)
    db.fail_query.add(failing_collection)
    r = run(db)
    assert r.status == act.BLOCKED and db.create_calls == before, r
    assert set(r.reason_codes) & {"PRODUCTION_READINESS_FAILED", "EXISTING_STATE_UNREADABLE"}


def test_real_create_time_outside_calendar_is_not_reported_as_success_and_repeat_is_stable():
    db = _Db()
    db.server_create_time = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)  # ön kontrol (NOW) geçti
    r = _activate(db)
    assert r.status == act.ACTIVATED_HOLDOUT_START_UNDETERMINABLE and "HOLDOUT_START_UNDETERMINABLE" in r.reason_codes
    assert r.effective_holdout_start is None and r.initial_event_create_time_observed == "2026-12-31T12:00:00+00:00"
    assert r.activation_event_id in db.store[EVENTS]  # kalıcı kayıt silinmedi
    calls = list(db.create_calls)
    again = _activate(db)
    assert again.status == act.ACTIVATED_HOLDOUT_START_UNDETERMINABLE and db.create_calls == calls
    assert again.initial_event_create_time_observed == r.initial_event_create_time_observed  # kaymadı
    before = list(db.create_calls)
    rev = _authorize(db)  # başlangıcı belirlenemeyen deneyde revision geçişi de yazmaz
    assert rev.status == act.BLOCKED and "HOLDOUT_START_UNDETERMINABLE" in rev.reason_codes and db.create_calls == before


def test_revision_authorization_tolerates_running_evidence_collection():
    db = _Db()
    _activate(db)
    db.store["technical_v1_attempt_claims"] = {"x": ({"protocol_version": V2.protocol_version}, None)}
    r = _authorize(db)
    assert r.status == act.AUTHORIZED, r
