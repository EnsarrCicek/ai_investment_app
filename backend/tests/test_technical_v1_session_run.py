"""HATA 12N3C1 — `app/research/session_run.py` saf domain modeli
testleri (Firestore/GCS erişimi olmadan)."""

import hashlib

import pytest

from app.research.evidence_identity import compute_session_id
from app.research.session_run import SessionRunStatus, TechnicalV1SessionRunSnapshot

PROTOCOL = "TECHNICAL_V1_PROTOCOL_V1"
T_DATE = "2026-09-09"


def _h(i: int) -> str:
    return hashlib.sha256(f"eval-{i}".encode()).hexdigest()


def _session_id() -> str:
    return compute_session_id(PROTOCOL, T_DATE)


def _make_snapshot(retry_pending=(), provenance_blocked=()) -> TechnicalV1SessionRunSnapshot:
    return TechnicalV1SessionRunSnapshot(
        session_id=_session_id(),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        retry_pending_evaluation_ids=tuple(retry_pending),
        provenance_blocked_evaluation_ids=tuple(provenance_blocked),
    )


# ---------------------------------------------------------------------------
# section 31 -- valid empty snapshot
# ---------------------------------------------------------------------------


def test_empty_snapshot_is_incomplete():
    snapshot = _make_snapshot()
    assert snapshot.status == SessionRunStatus.INCOMPLETE
    assert snapshot.to_document_fields()["status"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# section 32 -- retry status
# ---------------------------------------------------------------------------


def test_nonempty_retry_only_is_finalization_retry_pending():
    ids = sorted([_h(1), _h(2)])
    snapshot = _make_snapshot(retry_pending=ids)
    assert snapshot.status == SessionRunStatus.FINALIZATION_RETRY_PENDING
    assert snapshot.to_document_fields()["status"] == "FINALIZATION_RETRY_PENDING"


# ---------------------------------------------------------------------------
# section 33 -- provenance priority
# ---------------------------------------------------------------------------


def test_nonempty_provenance_only_is_provenance_blocked():
    ids = sorted([_h(1), _h(2)])
    snapshot = _make_snapshot(provenance_blocked=ids)
    assert snapshot.status == SessionRunStatus.PROVENANCE_BLOCKED


def test_provenance_has_priority_over_retry_when_both_nonempty_disjoint():
    a, b = sorted([_h(1), _h(2)])
    snapshot = _make_snapshot(retry_pending=[a], provenance_blocked=[b])
    assert snapshot.status == SessionRunStatus.PROVENANCE_BLOCKED


# ---------------------------------------------------------------------------
# section 34 -- overlap rejected
# ---------------------------------------------------------------------------


def test_overlapping_ids_between_lists_rejected():
    shared = _h(1)
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[shared], provenance_blocked=[shared])


# ---------------------------------------------------------------------------
# section 35 -- canonical ID list validation
# ---------------------------------------------------------------------------


def test_rejects_uppercase_hash():
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[_h(1).upper()])


def test_rejects_63_char_hash():
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[_h(1)[:-1]])


def test_rejects_65_char_hash():
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[_h(1) + "a"])


def test_rejects_non_hex_hash():
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=["g" * 64])


def test_rejects_duplicate_ids_in_same_list():
    id_ = _h(1)
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[id_, id_])


def test_rejects_unsorted_ids():
    a, b = sorted([_h(1), _h(2)])
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[b, a])  # descending -- not sorted ascending


def test_rejects_non_string_id():
    with pytest.raises(ValueError):
        _make_snapshot(retry_pending=[12345])


def test_rejects_bare_string_as_id_collection():
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot(
            session_id=_session_id(),
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            retry_pending_evaluation_ids=_h(1),  # bare str, not a tuple/list of one
            provenance_blocked_evaluation_ids=(),
        )


# ---------------------------------------------------------------------------
# section 36 -- deep immutability
# ---------------------------------------------------------------------------


def test_constructor_accepts_list_and_stores_as_tuple():
    ids_list = sorted([_h(1), _h(2)])
    snapshot = TechnicalV1SessionRunSnapshot(
        session_id=_session_id(),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        retry_pending_evaluation_ids=ids_list,
        provenance_blocked_evaluation_ids=[],
    )
    assert isinstance(snapshot.retry_pending_evaluation_ids, tuple)


def test_mutating_original_list_after_construction_does_not_affect_snapshot():
    ids_list = sorted([_h(1), _h(2)])
    expected = tuple(ids_list)
    snapshot = TechnicalV1SessionRunSnapshot(
        session_id=_session_id(),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        retry_pending_evaluation_ids=ids_list,
        provenance_blocked_evaluation_ids=[],
    )
    ids_list.append(_h(3))
    ids_list.clear()
    assert snapshot.retry_pending_evaluation_ids == expected


def test_internal_tuple_cannot_be_item_mutated():
    snapshot = _make_snapshot(retry_pending=[_h(1)])
    with pytest.raises(TypeError):
        snapshot.retry_pending_evaluation_ids[0] = _h(2)


def test_mutating_serialized_output_list_does_not_affect_snapshot():
    snapshot = _make_snapshot(retry_pending=[_h(1)])
    fields = snapshot.to_document_fields()
    fields["retry_pending_evaluation_ids"].append(_h(2))
    fields["provenance_blocked_evaluation_ids"].append(_h(3))
    assert snapshot.retry_pending_evaluation_ids == (_h(1),)
    assert snapshot.provenance_blocked_evaluation_ids == ()


# ---------------------------------------------------------------------------
# section 37 -- identity
# ---------------------------------------------------------------------------


def test_rejects_wrong_session_id_for_protocol_and_date():
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot(
            session_id="d" * 64,
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            retry_pending_evaluation_ids=(),
            provenance_blocked_evaluation_ids=(),
        )


@pytest.mark.parametrize(
    "malformed_date", ["20260909", "2026-9-9", "2026-W37-4", " 2026-09-09", "2026-09-09T00:00:00"]
)
def test_rejects_malformed_canonical_session_date(malformed_date):
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot(
            session_id="d" * 64,
            protocol_version=PROTOCOL,
            T_session_date=malformed_date,
            retry_pending_evaluation_ids=(),
            provenance_blocked_evaluation_ids=(),
        )


def test_rejects_empty_protocol_version():
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot(
            session_id="d" * 64,
            protocol_version="",
            T_session_date=T_DATE,
            retry_pending_evaluation_ids=(),
            provenance_blocked_evaluation_ids=(),
        )


# ---------------------------------------------------------------------------
# Reconstruction (from_document_fields) -- exact roundtrip + inconsistency
# ---------------------------------------------------------------------------


def test_round_trip_is_exact():
    ids = sorted([_h(1), _h(2)])
    snapshot = _make_snapshot(retry_pending=ids)
    doc = snapshot.to_document_fields()
    reconstructed = TechnicalV1SessionRunSnapshot.from_document_fields(doc)
    assert reconstructed == snapshot
    assert reconstructed.to_document_fields() == doc


def test_from_document_fields_rejects_unknown_key():
    doc = _make_snapshot().to_document_fields()
    doc["unexpected_field"] = "x"
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


def test_from_document_fields_rejects_missing_key():
    doc = _make_snapshot().to_document_fields()
    del doc["provenance_blocked_evaluation_ids"]
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


def test_from_document_fields_rejects_invalid_status_literal():
    doc = _make_snapshot().to_document_fields()
    doc["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


def test_from_document_fields_rejects_incomplete_status_with_nonempty_retry():
    ids = [_h(1)]
    doc = _make_snapshot(retry_pending=ids).to_document_fields()
    doc["status"] = "INCOMPLETE"  # tutarsız: liste dolu ama status INCOMPLETE
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


def test_from_document_fields_rejects_retry_pending_status_with_empty_lists():
    doc = _make_snapshot().to_document_fields()
    doc["status"] = "FINALIZATION_RETRY_PENDING"  # her iki liste de bos
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


def test_from_document_fields_rejects_provenance_blocked_status_with_empty_provenance_list():
    ids = [_h(1)]
    doc = _make_snapshot(retry_pending=ids).to_document_fields()
    doc["status"] = "PROVENANCE_BLOCKED"  # provenance list bos, retry dolu
    with pytest.raises(ValueError):
        TechnicalV1SessionRunSnapshot.from_document_fields(doc)


# ---------------------------------------------------------------------------
# Source inspection -- section 43
# ---------------------------------------------------------------------------


def test_session_run_module_imports_no_firestore_or_cloud():
    from app.research import session_run as session_run_module

    module_names = set(vars(session_run_module))
    forbidden_names = {"firestore", "SERVER_TIMESTAMP"}
    assert forbidden_names.isdisjoint(module_names)

    forbidden_modules = {"firebase_admin", "google.cloud.firestore"}
    for name, value in vars(session_run_module).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"


def test_session_run_snapshot_has_no_record_content_sha256():
    snapshot = _make_snapshot()
    assert not hasattr(snapshot, "record_content_sha256")


def test_session_run_snapshot_has_no_updated_at_field():
    snapshot = _make_snapshot()
    assert "updated_at" not in snapshot.to_document_fields()
    assert not hasattr(snapshot, "updated_at")
