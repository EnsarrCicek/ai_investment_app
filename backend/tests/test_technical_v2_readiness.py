"""TECHNICAL V2-R1 — aktivasyon öncesi release gate testleri.

Gerçek Firestore YOK: sahte, yazmayı yasaklayan okuyucular. Performans
metriği hesaplanmaz/gösterilmez.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest

from app.research.technical_v2_readiness import (
    NOT_READY,
    READY,
    FirestoreReadOnlyActivationStateReader,
    TechnicalV2ReadinessResult,
    validate_technical_v2_release_readiness,
)
from app.research.technical_versions import TECHNICAL_V1_SPEC, TECHNICAL_V2_SPEC

_V2_PROTOCOL = json.loads(TECHNICAL_V2_SPEC.protocol_path.read_text(encoding="utf-8"))
_V2_MANIFEST = json.loads(TECHNICAL_V2_SPEC.freeze_manifest_path.read_text(encoding="utf-8"))


class _State:
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


def _run(**kwargs) -> TechnicalV2ReadinessResult:
    kwargs.setdefault("activation_state", _State())
    return validate_technical_v2_release_readiness(**kwargs)


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


# ------------------------------------------------------------------ happy path


def test_current_build_is_ready_in_pre_activation_state():
    state = _State()
    r = _run(activation_state=state)
    assert r.status == READY, r.failed_gates
    assert r.failed_gates == ()
    assert (r.technical_version, r.protocol_version, r.engine_version) == ("TECHNICAL_V2", "TECHNICAL_V2_PROTOCOL_V1", "1.15.0")
    assert r.protocol_sha256 == "50b5b4e336f48c4043fe6802067b14b86ad8e0beb2cc78a6d56fec8209b395b8"
    assert r.freeze_manifest_sha256 == "41d75cbb06433927d9cc164f2fad56196e6fc8864dcb5e0739bece9278ade0b3"
    assert r.scoring_config_sha256 == "90ba569cf09eb771e6a40de7e5c8a75e3ac97629315c4d59b2607e53a88d9850"
    assert r.methodology_source_fingerprint == r.observed_methodology_source_fingerprint == \
        "8fbea7ed233ba6741fa7cd07ad0fbd3b630f3e68f7ad9a244ae6a484248884e1"
    assert r.fingerprint_normalized is True and r.universe_count == 100
    assert r.holdout_active is False and r.effective_holdout_start is None
    assert (r.activation_lock_present, r.activation_event_present, r.evidence_collection_running) == (False, False, False)
    assert set(state.seen) == {"TECHNICAL_V2_PROTOCOL_V1"}


# ------------------------------------------------------------------ fail closed: identity


@pytest.mark.parametrize("kwargs, gate", [
    ({"running_engine_version": "1.14.0"}, "ENGINE_VERSION"),
    ({"observed_scoring_config_hash": "0" * 64}, "SCORING_CONFIG"),
    ({"observed_methodology_fingerprint": "f" * 64}, "METHODOLOGY_FINGERPRINT"),
    ({"observed_methodology_fingerprint": "bbbe3c8d2fc5815ff70a4a2b2922c729ce7058f0f83035d24bed0c6ed88b96dc"},
     "METHODOLOGY_FINGERPRINT"),  # CRLF ham-bayt parmak izi de hard block
])
def test_runtime_identity_mismatch_is_not_ready(kwargs, gate):
    r = _run(**kwargs)
    assert r.status == NOT_READY and gate in r.failed_gates


def test_wrong_protocol_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, protocol_mut=lambda p: p.update(scope_note=p["scope_note"] + " (tampered)"))
    r = _run(spec=spec)
    assert r.status == NOT_READY and "PROTOCOL_SHA256" in r.failed_gates


def test_wrong_manifest_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, manifest_mut=lambda m: m.update(scope="tampered"))
    r = _run(spec=spec)
    assert r.status == NOT_READY and "FREEZE_MANIFEST_BINDING" in r.failed_gates


def test_manifest_with_wrong_scoring_hash_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, manifest_mut=lambda m: m["methodology_identity"].update(scoring_config_hash="0" * 64))
    r = _run(spec=spec)
    assert r.status == NOT_READY and {"SCORING_CONFIG", "FREEZE_MANIFEST_BINDING"} <= set(r.failed_gates)


def test_manifest_with_wrong_fingerprint_is_not_ready(tmp_path):
    spec = _spec_with(tmp_path, manifest_mut=lambda m: m["methodology_identity"].update(methodology_source_fingerprint="f" * 64))
    r = _run(spec=spec)
    assert r.status == NOT_READY and "METHODOLOGY_FINGERPRINT" in r.failed_gates


def test_v1_identity_is_not_ready():
    r = _run(spec=TECHNICAL_V1_SPEC)
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
    r = _run(spec=_spec_with(tmp_path, protocol_mut=_set_universe(symbols)))
    assert r.status == NOT_READY and gate in r.failed_gates and "UNIVERSE_MATCHES_PROTOCOL" in r.failed_gates


def test_frozen_universe_is_not_refreshed_after_membership_period_end():
    r = _run(today=date(2026, 12, 15))
    assert r.status == READY and r.universe_count == 100
    assert "UNIVERSE_MEMBERSHIP_PERIOD_ENDED_UNIVERSE_REMAINS_FROZEN_BY_PROTOCOL" in r.warnings
    assert _V2_PROTOCOL["universe"]["membership_period_end"] == "2026-09-30"
    # kapı canlı üyelik girdisi almaz: tarih ne olursa olsun evren protokoldeki listedir
    assert "membership" not in " ".join(validate_technical_v2_release_readiness.__code__.co_varnames[:6])


def test_changing_universe_under_same_protocol_version_requires_new_protocol_revision(tmp_path):
    live = [s for s in _V2_PROTOCOL["universe"]["frozen_symbol_list"] if s != "ZOREN"] + ["NEWCO"]
    r = _run(spec=_spec_with(tmp_path, protocol_mut=_set_universe(live)))
    assert r.status == NOT_READY and "PROTOCOL_SHA256" in r.failed_gates


# ------------------------------------------------------------------ fail closed: activation state


@pytest.mark.parametrize("mut, gate", [
    (lambda p: p["holdout_status"].update(prospective_holdout_started=True), "HOLDOUT_INACTIVE"),
    (lambda p: p["holdout_status"].update(effective_holdout_start="2026-10-01"), "HOLDOUT_START_NULL"),
])
def test_active_holdout_is_not_ready(tmp_path, mut, gate):
    r = _run(spec=_spec_with(tmp_path, protocol_mut=mut))
    assert r.status == NOT_READY and gate in r.failed_gates


@pytest.mark.parametrize("state, gate", [
    (_State(lock=True), "NO_ACTIVATION_LOCK"),
    (_State(event=True), "NO_ACTIVATION_EVENT"),
    (_State(running=True), "NO_EVIDENCE_COLLECTION_RUNNING"),
])
def test_existing_activation_state_is_not_ready(state, gate):
    r = _run(activation_state=state)
    assert r.status == NOT_READY and r.failed_gates == (gate,)


def test_unreadable_activation_state_fails_closed():
    r = _run(activation_state=_State(fail=True))
    assert r.status == NOT_READY
    assert {"NO_ACTIVATION_LOCK", "NO_ACTIVATION_EVENT", "NO_EVIDENCE_COLLECTION_RUNNING"} <= set(r.failed_gates)
    assert r.activation_lock_present is None


# ------------------------------------------------------------------ read-only Firestore reader


class _ReadOnlyDb:
    def __init__(self, docs_by_collection=None):
        self.docs = docs_by_collection or {}
        self.queries: list[tuple] = []

    def collection(self, name):
        db = self

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

            def __getattr__(self, attr):
                if attr in ("document", "add", "set", "update", "delete", "create"):
                    raise AssertionError(f"yazma yolu çağrıldı: {attr}")
                raise AttributeError(attr)

        return _Q()

    def __getattr__(self, attr):
        if attr in ("batch", "transaction", "bulk_writer"):
            raise AssertionError(f"yazma yolu çağrıldı: {attr}")
        raise AttributeError(attr)


def test_firestore_reader_is_read_only_and_ready_when_empty():
    db = _ReadOnlyDb()
    r = _run(activation_state=FirestoreReadOnlyActivationStateReader(db))
    assert r.status == READY
    assert db.queries and all(f == (("protocol_version", "==", "TECHNICAL_V2_PROTOCOL_V1"),) for _, f in db.queries)


def test_firestore_reader_ignores_v1_records_and_detects_v2_records():
    v1_only = _ReadOnlyDb({"technical_v1_activation_locks": [{"protocol_version": "TECHNICAL_V1_PROTOCOL_V1"}]})
    assert _run(activation_state=FirestoreReadOnlyActivationStateReader(v1_only)).status == READY
    v2 = _ReadOnlyDb({"technical_v1_attempt_claims": [{"protocol_version": "TECHNICAL_V2_PROTOCOL_V1"}]})
    r = _run(activation_state=FirestoreReadOnlyActivationStateReader(v2))
    assert r.status == NOT_READY and r.failed_gates == ("NO_EVIDENCE_COLLECTION_RUNNING",)


# ------------------------------------------------------------------ blinding


def test_result_exposes_no_performance_fields():
    names = {f.name for f in dataclasses.fields(TechnicalV2ReadinessResult)}
    for token in ("hit", "return", "accuracy", "benchmark", "pnl", "performance", "ic"):
        assert not [n for n in names if token in n.split("_")], token
