"""TECHNICAL V2-R1 — aktivasyon öncesi release gate testleri.

Gerçek Firestore YOK: sahte, yazmayı yasaklayan okuyucular. Performans
metriği hesaplanmaz/gösterilmez. LOCAL sonucu (sentetik okuyucuyla bile)
production aktivasyonuna yetmez; PRODUCTION'da canlı kontroller zorunludur.
"""

from __future__ import annotations

import dataclasses
import io
import json
from datetime import date
from pathlib import Path

import pytest

from app.research.technical_v2_readiness import (
    ABSENT,
    FIRESTORE_READ_ONLY,
    LOCAL_CHECKS_PASSED,
    MODE_LOCAL,
    MODE_PRODUCTION,
    NOT_READY,
    NOT_RUN,
    PRESENT,
    READY,
    UNKNOWN,
    FirestoreReadOnlyActivationStateReader,
    ReadOnlySystemConfigReader,
    TechnicalV2ReadinessResult,
    live_scoring_config_hash_from,
    _run_cli,
    run_cli,
    validate_technical_v2_release_readiness,
)
from app.research.technical_versions import TECHNICAL_V1_SPEC, TECHNICAL_V2_SPEC

_V2_PROTOCOL = json.loads(TECHNICAL_V2_SPEC.protocol_path.read_text(encoding="utf-8"))
_V2_MANIFEST = json.loads(TECHNICAL_V2_SPEC.freeze_manifest_path.read_text(encoding="utf-8"))
_FROZEN_SCORING = _V2_MANIFEST["methodology_identity"]["scoring_config_hash"]
_RUNTIME = {"service": "ai-investment-backend", "revision": "ai-investment-backend-00042-abc"}


class _State:
    """Sentetik okuyucu (source = SYNTHETIC)."""

    source = "SYNTHETIC"

    def __init__(self, lock=False, event=False, running=False, fail=False):
        self.values = {"lock": lock, "event": event, "running": running}
        self.fail = fail
        self.seen: list[str] = []

    def _get(self, key, pv):
        self.seen.append(pv)
        if self.fail:
            raise RuntimeError("okunamadı")
        return self.values[key]

    def activation_lock_exists(self, pv):
        return self._get("lock", pv)

    def activation_event_exists(self, pv):
        return self._get("event", pv)

    def evidence_collection_running(self, pv):
        return self._get("running", pv)


class _ProductionLikeState(_State):
    source = FIRESTORE_READ_ONLY


def _local(**kwargs) -> TechnicalV2ReadinessResult:
    kwargs.setdefault("activation_state", _State())
    return validate_technical_v2_release_readiness(mode=MODE_LOCAL, **kwargs)


def _production(**kwargs) -> TechnicalV2ReadinessResult:
    kwargs.setdefault("activation_state", _ProductionLikeState())
    kwargs.setdefault("live_scoring_config_hash_reader", lambda: _FROZEN_SCORING)
    kwargs.setdefault("runtime_identity_reader", lambda: dict(_RUNTIME))
    return validate_technical_v2_release_readiness(mode=MODE_PRODUCTION, **kwargs)


def _spec_with(tmp_path: Path, protocol_mut=None, manifest_mut=None):
    protocol = json.loads(json.dumps(_V2_PROTOCOL))
    manifest = json.loads(json.dumps(_V2_MANIFEST))
    if protocol_mut:
        protocol_mut(protocol)
    if manifest_mut:
        manifest_mut(manifest)
    pp, mp = tmp_path / "protocol.json", tmp_path / "manifest.json"
    pp.write_text(json.dumps(protocol), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    return dataclasses.replace(TECHNICAL_V2_SPEC, protocol_path=pp, freeze_manifest_path=mp)


# ------------------------------------------------------------------ scope: local vs production


def test_local_scope_with_no_live_readers_never_reports_absent_and_is_not_eligible():
    r = validate_technical_v2_release_readiness(mode=MODE_LOCAL)
    assert r.status == LOCAL_CHECKS_PASSED, r.failed_gates
    assert r.production_activation_eligible is False and r.verification_scope == MODE_LOCAL
    assert (r.activation_lock_state, r.activation_event_state, r.evidence_collection_state) == (NOT_RUN,) * 3
    assert r.activation_state_source == NOT_RUN and r.live_scoring_config_status == NOT_RUN
    assert r.runtime_identity_status == NOT_RUN
    assert {"NO_ACTIVATION_LOCK", "NO_ACTIVATION_EVENT", "NO_EVIDENCE_COLLECTION_RUNNING", "LIVE_SCORING_CONFIG",
            "DEPLOYED_RUNTIME_IDENTITY", "DEPLOYED_CONTAINER_FINGERPRINT"} <= set(r.not_run_checks)


def test_synthetic_reader_pass_is_not_production_readiness():
    r = _local()
    assert r.status == LOCAL_CHECKS_PASSED and r.status != READY
    assert r.production_activation_eligible is False
    assert r.activation_state_source == "SYNTHETIC" and r.activation_lock_state == ABSENT
    assert "PRODUCTION_ACTIVATION_STATE_READ" in r.not_run_checks


def test_production_with_synthetic_reader_is_not_ready():
    r = _production(activation_state=_State())
    assert r.status == NOT_READY and "ACTIVATION_STATE_NOT_PRODUCTION_SOURCE" in r.failed_gates


def test_production_happy_path_requires_every_live_check():
    r = _production()
    assert r.status == READY and r.production_activation_eligible is True, r.failed_gates
    assert r.not_run_checks == () and r.failed_gates == ()
    assert r.live_scoring_config_status == "MATCH" and r.runtime_identity_status == "OBSERVED"
    assert r.fingerprint_source == "RUNNING_SOURCE_BYTES"
    assert r.observed_methodology_source_fingerprint == r.methodology_source_fingerprint == \
        "8fbea7ed233ba6741fa7cd07ad0fbd3b630f3e68f7ad9a244ae6a484248884e1"


@pytest.mark.parametrize("override, gate", [
    ({"activation_state": None}, "NO_ACTIVATION_LOCK"),
    ({"live_scoring_config_hash_reader": None}, "LIVE_SCORING_CONFIG"),
    ({"runtime_identity_reader": None}, "DEPLOYED_RUNTIME_IDENTITY"),
])
def test_production_missing_live_check_blocks(override, gate):
    r = _production(**override)
    assert r.status == NOT_READY and gate in r.failed_gates and r.production_activation_eligible is False


def _raise():
    raise RuntimeError("firestore unavailable")


@pytest.mark.parametrize("reader, gate, status", [
    (_raise, "LIVE_SCORING_CONFIG_UNREADABLE", "UNREADABLE"),
    (lambda: "0" * 64, "LIVE_SCORING_CONFIG_MISMATCH", "MISMATCH"),
])
def test_production_unreadable_or_mismatched_live_config_blocks(reader, gate, status):
    r = _production(live_scoring_config_hash_reader=reader)
    assert r.status == NOT_READY and gate in r.failed_gates and r.live_scoring_config_status == status


def test_production_unreadable_firestore_state_is_unknown_and_blocks():
    r = _production(activation_state=_ProductionLikeState(fail=True))
    assert r.status == NOT_READY
    assert (r.activation_lock_state, r.activation_event_state, r.evidence_collection_state) == (UNKNOWN,) * 3
    assert {"NO_ACTIVATION_LOCK", "NO_ACTIVATION_EVENT", "NO_EVIDENCE_COLLECTION_RUNNING"} <= set(r.failed_gates)


def test_production_unobservable_runtime_identity_blocks():
    from app.research.technical_v1_runtime_identity import RuntimeIdentityUnobservableError

    def missing():
        raise RuntimeIdentityUnobservableError("K_SERVICE eksik")

    r = _production(runtime_identity_reader=missing)
    assert r.status == NOT_READY and "DEPLOYED_RUNTIME_IDENTITY_UNOBSERVABLE" in r.failed_gates


def test_production_rejects_supplied_fingerprint_or_engine_even_if_equal():
    r = _production(observed_methodology_fingerprint=_V2_MANIFEST["methodology_identity"]["methodology_source_fingerprint"])
    assert r.status == NOT_READY and "FINGERPRINT_NOT_MEASURED_FROM_RUNNING_BYTES" in r.failed_gates
    r = _production(running_engine_version="1.15.0")
    assert r.status == NOT_READY and "ENGINE_VERSION_NOT_FROM_RUNNING_BUILD" in r.failed_gates


def test_production_running_bytes_fingerprint_mismatch_is_hard_block(monkeypatch):
    import app.research.methodology_fingerprint as mf

    monkeypatch.setattr(mf, "compute_methodology_source_fingerprint", lambda normalize_newlines=False: "f" * 64)
    r = _production()
    assert r.status == NOT_READY and "METHODOLOGY_FINGERPRINT" in r.failed_gates


# ------------------------------------------------------------------ fail closed: identity (local)


@pytest.mark.parametrize("kwargs, gate", [
    ({"running_engine_version": "1.14.0"}, "ENGINE_VERSION"),
    ({"observed_methodology_fingerprint": "f" * 64}, "METHODOLOGY_FINGERPRINT"),
    ({"observed_methodology_fingerprint": "bbbe3c8d2fc5815ff70a4a2b2922c729ce7058f0f83035d24bed0c6ed88b96dc"},
     "METHODOLOGY_FINGERPRINT"),  # CRLF ham-bayt parmak izi de hard block
])
def test_identity_mismatch_is_not_ready(kwargs, gate):
    r = _local(**kwargs)
    assert r.status == NOT_READY and gate in r.failed_gates


def test_wrong_protocol_is_not_ready(tmp_path):
    r = _local(spec=_spec_with(tmp_path, protocol_mut=lambda p: p.update(scope_note=p["scope_note"] + " (tampered)")))
    assert r.status == NOT_READY and "PROTOCOL_SHA256" in r.failed_gates


def test_wrong_manifest_is_not_ready(tmp_path):
    r = _local(spec=_spec_with(tmp_path, manifest_mut=lambda m: m.update(scope="tampered")))
    assert r.status == NOT_READY and "FREEZE_MANIFEST_BINDING" in r.failed_gates


def test_manifest_with_wrong_scoring_hash_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, manifest_mut=lambda m: m["methodology_identity"].update(scoring_config_hash="0" * 64))
    r = _local(spec=spec)
    assert r.status == NOT_READY and {"SCORING_CONFIG_FROZEN", "FREEZE_MANIFEST_BINDING"} <= set(r.failed_gates)


def test_manifest_with_wrong_fingerprint_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, manifest_mut=lambda m: m["methodology_identity"].update(methodology_source_fingerprint="f" * 64))
    r = _local(spec=spec)
    assert r.status == NOT_READY and "METHODOLOGY_FINGERPRINT" in r.failed_gates


def test_v1_identity_is_not_ready():
    r = _local(spec=TECHNICAL_V1_SPEC)
    assert r.status == NOT_READY
    assert {"TECHNICAL_VERSION", "PROTOCOL_VERSION", "PROTOCOL_SHA256", "ENGINE_VERSION"} <= set(r.failed_gates)


# ------------------------------------------------------------------ fail closed: universe


def _set_universe(symbols):
    def mut(p):
        p["universe"]["frozen_symbol_list"] = symbols
        p["universe"]["constituent_count"] = len(symbols)
        p["universe"]["unique_ticker_count"] = len(set(symbols))
    return mut


@pytest.mark.parametrize("symbols, gate", [
    (_V2_PROTOCOL["universe"]["frozen_symbol_list"][:99], "UNIVERSE_COUNT"),
    (_V2_PROTOCOL["universe"]["frozen_symbol_list"] + ["NEWCO"], "UNIVERSE_COUNT"),
    (_V2_PROTOCOL["universe"]["frozen_symbol_list"][:99] + ["AKBNK"], "UNIVERSE_UNIQUE"),
])
def test_bad_universe_is_not_ready(tmp_path, symbols, gate):
    r = _local(spec=_spec_with(tmp_path, protocol_mut=_set_universe(symbols)))
    assert r.status == NOT_READY and gate in r.failed_gates and "UNIVERSE_MATCHES_PROTOCOL" in r.failed_gates


def test_frozen_universe_is_not_refreshed_after_membership_period_end():
    r = _production(today=date(2026, 12, 15))
    assert r.status == READY and r.universe_count == 100
    assert "UNIVERSE_MEMBERSHIP_PERIOD_ENDED_UNIVERSE_REMAINS_FROZEN_BY_PROTOCOL" in r.warnings
    assert _V2_PROTOCOL["universe"]["membership_period_end"] == "2026-09-30"


def test_changing_universe_under_same_protocol_version_requires_new_protocol_revision(tmp_path):
    live = [s for s in _V2_PROTOCOL["universe"]["frozen_symbol_list"] if s != "ZOREN"] + ["NEWCO"]
    r = _local(spec=_spec_with(tmp_path, protocol_mut=_set_universe(live)))
    assert r.status == NOT_READY and "PROTOCOL_SHA256" in r.failed_gates


# ------------------------------------------------------------------ fail closed: activation state


@pytest.mark.parametrize("mut, gate", [
    (lambda p: p["holdout_status"].update(prospective_holdout_started=True), "HOLDOUT_INACTIVE"),
    (lambda p: p["holdout_status"].update(effective_holdout_start="2026-10-01"), "HOLDOUT_START_NULL"),
])
def test_active_holdout_is_not_ready(tmp_path, mut, gate):
    r = _local(spec=_spec_with(tmp_path, protocol_mut=mut))
    assert r.status == NOT_READY and gate in r.failed_gates


@pytest.mark.parametrize("state, gate", [
    (_ProductionLikeState(lock=True), "NO_ACTIVATION_LOCK"),
    (_ProductionLikeState(event=True), "NO_ACTIVATION_EVENT"),
    (_ProductionLikeState(running=True), "NO_EVIDENCE_COLLECTION_RUNNING"),
])
def test_existing_activation_state_is_not_ready(state, gate):
    r = _production(activation_state=state)
    assert r.status == NOT_READY and r.failed_gates == (gate,)
    assert PRESENT in (r.activation_lock_state, r.activation_event_state, r.evidence_collection_state)


# ------------------------------------------------------------------ read-only Firestore reader + CLI


class _ReadOnlyDb:
    """Yazma yollarını (document().set/create/update/delete, add, batch,
    transaction) yasaklayan sahte Firestore. document().get() okumaya izinli."""

    def __init__(self, docs_by_collection=None, config_docs=None):
        self.docs = docs_by_collection or {}
        self.config_docs = config_docs or {}
        self.queries: list[tuple] = []

    def collection(self, name):
        db = self

        class _Doc:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self):
                data = db.config_docs.get(self.doc_id) if name == "system_config" else None
                return type("Snap", (), {"exists": data is not None, "to_dict": lambda _s: data})()

            def __getattr__(self, attr):
                raise AssertionError(f"yazma yolu çağrıldı: document.{attr}")

        class _Q:
            def __init__(self):
                self.filters = []

            def where(self, field, op, value):
                self.filters.append((field, op, value))
                return self

            def limit(self, n):
                return self

            def get(self):
                db.queries.append((name, tuple(self.filters)))
                return [d for d in db.docs.get(name, []) if all(d.get(f) == v for f, _, v in self.filters)]

            def document(self, doc_id):
                return _Doc(doc_id)

            def __getattr__(self, attr):
                raise AssertionError(f"yazma yolu çağrıldı: collection.{attr}")

        return _Q()

    def __getattr__(self, attr):
        raise AssertionError(f"yazma yolu çağrıldı: db.{attr}")


def _frozen_config_docs():
    return {"technical_indicator_weights": dict(_V2_MANIFEST["technical_indicator_weights"]),
            "technical_family_weights": dict(_V2_MANIFEST["technical_family_weights"])}


def test_real_firestore_reader_and_live_config_are_read_only_and_ready_when_empty():
    db = _ReadOnlyDb(config_docs=_frozen_config_docs())
    r = _production(activation_state=FirestoreReadOnlyActivationStateReader(db),
                    live_scoring_config_hash_reader=live_scoring_config_hash_from(db))
    assert r.status == READY, r.failed_gates
    assert r.activation_state_source == FIRESTORE_READ_ONLY and r.live_scoring_config_status == "MATCH"
    assert db.queries and all(f == (("protocol_version", "==", "TECHNICAL_V2_PROTOCOL_V1"),) for _, f in db.queries)


def test_live_config_drift_from_firestore_blocks():
    docs = _frozen_config_docs()
    docs["technical_indicator_weights"]["rsi"] = 0.5
    db = _ReadOnlyDb(config_docs=docs)
    r = _production(activation_state=FirestoreReadOnlyActivationStateReader(db),
                    live_scoring_config_hash_reader=live_scoring_config_hash_from(db))
    assert r.status == NOT_READY and r.live_scoring_config_status in ("MISMATCH", "UNREADABLE")


def test_missing_live_config_documents_block_instead_of_default_seeding():
    db = _ReadOnlyDb(config_docs={})  # REQUIRED technical_indicator_weights yok
    assert ReadOnlySystemConfigReader(db).get_raw("technical_indicator_weights") is None
    r = _production(activation_state=FirestoreReadOnlyActivationStateReader(db),
                    live_scoring_config_hash_reader=live_scoring_config_hash_from(db))
    assert r.status == NOT_READY and r.live_scoring_config_status == "UNREADABLE"


def test_firestore_reader_ignores_v1_records_and_detects_v2_records():
    v1_only = _ReadOnlyDb({"technical_v1_activation_locks": [{"protocol_version": "TECHNICAL_V1_PROTOCOL_V1"}]})
    assert _production(activation_state=FirestoreReadOnlyActivationStateReader(v1_only)).status == READY
    v2 = _ReadOnlyDb({"technical_v1_attempt_claims": [{"protocol_version": "TECHNICAL_V2_PROTOCOL_V1"}]})
    r = _production(activation_state=FirestoreReadOnlyActivationStateReader(v2))
    assert r.status == NOT_READY and r.failed_gates == ("NO_EVIDENCE_COLLECTION_RUNNING",)


def test_cli_local_exit_code_is_not_success():
    out = io.StringIO()
    code = _run_cli(["--mode", "local"], out=out)
    payload = json.loads(out.getvalue())
    assert code == 3 and payload["status"] == LOCAL_CHECKS_PASSED and payload["production_activation_eligible"] is False


def test_cli_production_fails_closed_when_firestore_client_unavailable():
    def no_client():
        raise RuntimeError("secret-bearing message that must not be printed")

    out = io.StringIO()
    code = _run_cli(["--mode", "production"], firestore_client_factory=no_client,
                   runtime_identity_reader=lambda: dict(_RUNTIME), out=out)
    text = out.getvalue()
    payload = json.loads(text)
    assert code == 1 and payload["status"] == NOT_READY
    assert payload["firestore_client_error_type"] == "RuntimeError" and "secret-bearing" not in text


def test_cli_production_ready_with_read_only_client():
    db = _ReadOnlyDb(config_docs=_frozen_config_docs())
    out = io.StringIO()
    code = _run_cli(["--mode", "production"], firestore_client_factory=lambda: db,
                   runtime_identity_reader=lambda: dict(_RUNTIME), out=out)
    payload = json.loads(out.getvalue())
    assert code == 0 and payload["status"] == READY and payload["production_activation_eligible"] is True


def test_cli_production_without_deploy_runtime_env_is_not_ready(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("K_REVISION", raising=False)
    db = _ReadOnlyDb(config_docs=_frozen_config_docs())
    out = io.StringIO()
    code = _run_cli(["--mode", "production"], firestore_client_factory=lambda: db, out=out)
    payload = json.loads(out.getvalue())
    assert code == 1 and "DEPLOYED_RUNTIME_IDENTITY_UNOBSERVABLE" in payload["failed_gates"]


# ------------------------------------------------------------------ blinding


def test_result_exposes_no_performance_fields():
    names = {f.name for f in dataclasses.fields(TechnicalV2ReadinessResult)}
    for token in ("hit", "return", "accuracy", "benchmark", "pnl", "performance", "ic"):
        assert not [n for n in names if token in n.split("_")], token


def test_public_cli_entry_accepts_no_injected_dependencies():
    import inspect

    assert list(inspect.signature(run_cli).parameters) == ["argv"]
