"""HATA 12N3A — Technical V1 saf oturum (session) domain testleri
(`app/research/session_manifest.py` + `evidence_identity.compute_session_id`).

Bu dosya HİÇBİR Firestore/GCS/dosya sistemi erişimi kurmaz -- yalnızca
saf fonksiyonları/dataclass'ları doğrudan çağırır.
"""

import hashlib
import inspect
from dataclasses import replace

import pytest

from app.research import session_manifest as sm
from app.research.canonical_hash import content_sha256
from app.research.evidence_identity import compute_evaluation_id, compute_session_id
from app.research.final_evaluation_models import (
    AttemptRequirementState,
    AttemptSummary,
    CaptureStatus,
    ClaimPresence,
    EvaluationIntegrityStatus,
    FinalEvaluation,
    ResultState,
    VerificationState,
)

PROTOCOL = "TECHNICAL_V1_PROTOCOL_V1"
T_DATE = "2026-09-09"


def _frozen_symbols(n: int = 100) -> tuple[str, ...]:
    return tuple(f"SYM{i:03d}" for i in range(n))


def _hex(i: int, salt: str) -> str:
    return hashlib.sha256(f"{salt}-{i}".encode()).hexdigest()


def _pairs(n: int = 100, id_salt: str = "id", hash_salt: str = "hash") -> list[tuple[str, str]]:
    return [(_hex(i, id_salt), _hex(i, hash_salt)) for i in range(n)]


def _make_summary(attempt_number: int) -> AttemptSummary:
    return AttemptSummary(
        attempt_number=attempt_number,
        attempt_id=f"{'a' if attempt_number == 1 else 'b'}" * 64,
        requirement_state=AttemptRequirementState.REQUIRED,
        claim_presence=ClaimPresence.MISSING,
        result_state=ResultState.NO_RESULT,
        result_classification=None,
        native_reason_code=None,
        verification_state=VerificationState.NOT_APPLICABLE,
        verification_reason_code=None,
    )


def _make_evaluation(
    symbol: str,
    protocol_version: str = PROTOCOL,
    T_session_date: str = T_DATE,
    capture_status: CaptureStatus = CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
    evaluation_integrity_status: EvaluationIntegrityStatus = EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
    technical_observation_eligible: bool = False,
) -> FinalEvaluation:
    return FinalEvaluation(
        evaluation_id=compute_evaluation_id(protocol_version, T_session_date, symbol),
        protocol_version=protocol_version,
        T_session_date=T_session_date,
        symbol=symbol,
        protocol_sha256="a" * 64,
        methodology_git_commit="c1f0d439d40a709d55007bd8ff34b4a8b2347f95",
        freeze_manifest_sha256="b" * 64,
        engine_version="1.14.0",
        scoring_config_hash="c" * 64,
        E1_date="2026-09-10",
        formal_cutoff_timestamp="2026-09-10T06:45:00+00:00",
        capture_status=capture_status,
        evaluation_integrity_status=evaluation_integrity_status,
        technical_observation_eligible=technical_observation_eligible,
        selected_evidence_integrity_complete=None,
        attempt_history_complete=False,
        selected_attempt_id=None,
        attempt_1_summary=_make_summary(1),
        attempt_2_summary=_make_summary(2),
    )


def _make_full_session(symbols: tuple[str, ...]) -> list[FinalEvaluation]:
    return [_make_evaluation(sym) for sym in symbols]


# ---------------------------------------------------------------------------
# section 38 -- compute_session_id
# ---------------------------------------------------------------------------


def test_session_id_deterministic():
    assert compute_session_id(PROTOCOL, T_DATE) == compute_session_id(PROTOCOL, T_DATE)


def test_session_id_changes_with_protocol_version():
    assert compute_session_id(PROTOCOL, T_DATE) != compute_session_id("TECHNICAL_V1_PROTOCOL_V2", T_DATE)


def test_session_id_changes_with_session_date():
    assert compute_session_id(PROTOCOL, T_DATE) != compute_session_id(PROTOCOL, "2026-09-10")


@pytest.mark.parametrize("bad_date", ["20260909", "2026-9-9", "2026-W37-4", " 2026-09-09"])
def test_session_id_rejects_malformed_date(bad_date):
    with pytest.raises(ValueError):
        compute_session_id(PROTOCOL, bad_date)


def test_session_id_is_canonical_sha256_hex():
    session_id = compute_session_id(PROTOCOL, T_DATE)
    assert len(session_id) == 64
    assert session_id == session_id.lower()
    int(session_id, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# section 39 -- validate_frozen_universe
# ---------------------------------------------------------------------------


def test_validate_frozen_universe_accepts_100_unique_valid_symbols():
    symbols = _frozen_symbols()
    result = sm.validate_frozen_universe(symbols)
    assert result == symbols
    assert isinstance(result, tuple)


def test_validate_frozen_universe_rejects_99():
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(_frozen_symbols(99))


def test_validate_frozen_universe_rejects_101():
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(_frozen_symbols(101))


def test_validate_frozen_universe_rejects_duplicate():
    symbols = list(_frozen_symbols(99)) + ["SYM000"]
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(symbols)


def test_validate_frozen_universe_rejects_empty_symbol():
    symbols = list(_frozen_symbols(99)) + [""]
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(symbols)


def test_validate_frozen_universe_rejects_whitespace_wrapped_symbol():
    symbols = list(_frozen_symbols(99)) + [" SYM100"]
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(symbols)


def test_validate_frozen_universe_rejects_non_string():
    symbols = list(_frozen_symbols(99)) + [12345]
    with pytest.raises(ValueError):
        sm.validate_frozen_universe(symbols)


def test_validate_frozen_universe_preserves_supplied_order():
    symbols = tuple(reversed(_frozen_symbols()))
    result = sm.validate_frozen_universe(symbols)
    assert result == symbols  # NOT sorted back into ascending order


# ---------------------------------------------------------------------------
# section 40 -- derive_expected_evaluation_ids
# ---------------------------------------------------------------------------


def test_derive_expected_evaluation_ids_produces_100_unique_ids():
    ids = sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, _frozen_symbols())
    assert len(ids) == 100
    assert len(set(ids)) == 100


def test_derive_expected_evaluation_ids_matches_direct_computation():
    symbols = _frozen_symbols()
    ids = sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, symbols)
    for symbol, evaluation_id in zip(symbols, ids):
        assert evaluation_id == compute_evaluation_id(PROTOCOL, T_DATE, symbol)


# ---------------------------------------------------------------------------
# section 41 -- compute_expected_evaluation_ids_sha256
# ---------------------------------------------------------------------------


def test_expected_id_hash_is_order_independent():
    ids = sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, _frozen_symbols())
    assert sm.compute_expected_evaluation_ids_sha256(ids) == sm.compute_expected_evaluation_ids_sha256(
        tuple(reversed(ids))
    )


def test_expected_id_hash_changes_when_one_id_changes():
    ids = list(sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, _frozen_symbols()))
    h1 = sm.compute_expected_evaluation_ids_sha256(ids)
    other_id = compute_evaluation_id(PROTOCOL, T_DATE, "FOREIGN_SYMBOL")
    ids2 = ids[:-1] + [other_id]
    assert h1 != sm.compute_expected_evaluation_ids_sha256(ids2)


def test_expected_id_hash_rejects_wrong_count():
    ids = list(sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, _frozen_symbols()))[:99]
    with pytest.raises(ValueError):
        sm.compute_expected_evaluation_ids_sha256(ids)


def test_expected_id_hash_rejects_malformed_hex():
    ids = list(sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, _frozen_symbols()))
    ids[0] = "not-a-valid-sha256"
    with pytest.raises(ValueError):
        sm.compute_expected_evaluation_ids_sha256(ids)


# ---------------------------------------------------------------------------
# section 42 -- compute_final_evaluation_records_sha256 (pair binding)
# ---------------------------------------------------------------------------


def test_final_record_set_hash_is_order_independent():
    pairs = _pairs()
    assert sm.compute_final_evaluation_records_sha256(pairs) == sm.compute_final_evaluation_records_sha256(
        list(reversed(pairs))
    )


def test_final_record_set_hash_changes_when_one_record_hash_changes():
    pairs = _pairs()
    h1 = sm.compute_final_evaluation_records_sha256(pairs)
    mutated = list(pairs)
    mutated[0] = (mutated[0][0], _hex(999, "hash"))
    assert h1 != sm.compute_final_evaluation_records_sha256(mutated)


def test_final_record_set_hash_changes_when_hashes_swapped_between_ids():
    """HATA 12N3-A4 section 3: yalnızca ID<->hash BAĞI korunursa bu test
    anlamlıdır -- hash'ler kimlikler arasında yer değiştirdiğinde digest
    DEĞİŞMELİDİR (aksi halde bağ hash'lenmiyor demektir)."""
    pairs = _pairs()
    h1 = sm.compute_final_evaluation_records_sha256(pairs)
    swapped = list(pairs)
    id0, hash0 = swapped[0]
    id1, hash1 = swapped[1]
    swapped[0] = (id0, hash1)
    swapped[1] = (id1, hash0)
    assert h1 != sm.compute_final_evaluation_records_sha256(swapped)


def test_final_record_set_hash_rejects_wrong_count():
    with pytest.raises(ValueError):
        sm.compute_final_evaluation_records_sha256(_pairs(99))


def test_final_record_set_hash_rejects_duplicate_evaluation_id():
    pairs = _pairs(99) + [(_pairs(1)[0][0], _hex(999, "hash"))]
    with pytest.raises(ValueError):
        sm.compute_final_evaluation_records_sha256(pairs)


# ---------------------------------------------------------------------------
# section 43 -- session accounting
# ---------------------------------------------------------------------------


def test_accounting_all_verified_is_complete():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids}
    result = sm.derive_session_accounting("session-x", ids, states)
    assert result.status == sm.SessionAccountingStatus.COMPLETE
    assert (result.verified_count, result.absent_count, result.conflict_count) == (100, 0, 0)


def test_accounting_99_verified_1_absent_is_missing_final_records():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids}
    states[ids[0]] = sm.ExpectedEvaluationState.ABSENT
    result = sm.derive_session_accounting("session-x", ids, states)
    assert result.status == sm.SessionAccountingStatus.MISSING_FINAL_RECORDS


def test_accounting_99_verified_1_conflict_is_repository_provenance_conflict():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids}
    states[ids[0]] = sm.ExpectedEvaluationState.CONFLICT
    result = sm.derive_session_accounting("session-x", ids, states)
    assert result.status == sm.SessionAccountingStatus.REPOSITORY_PROVENANCE_CONFLICT


def test_accounting_absent_and_conflict_together_prioritizes_conflict():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids}
    states[ids[0]] = sm.ExpectedEvaluationState.ABSENT
    states[ids[1]] = sm.ExpectedEvaluationState.CONFLICT
    result = sm.derive_session_accounting("session-x", ids, states)
    assert result.status == sm.SessionAccountingStatus.REPOSITORY_PROVENANCE_CONFLICT
    assert (result.verified_count, result.absent_count, result.conflict_count) == (98, 1, 1)


def test_accounting_rejects_foreign_key():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids}
    del states[ids[0]]
    states["foreign-key-not-in-expected-set"] = sm.ExpectedEvaluationState.VERIFIED
    with pytest.raises(ValueError):
        sm.derive_session_accounting("session-x", ids, states)


def test_accounting_rejects_missing_map_entry():
    ids = [_hex(i, "id") for i in range(100)]
    states = {id_: sm.ExpectedEvaluationState.VERIFIED for id_ in ids[:-1]}
    with pytest.raises(ValueError):
        sm.derive_session_accounting("session-x", ids, states)


def test_session_accounting_result_rejects_inconsistent_sum():
    with pytest.raises(ValueError):
        sm.SessionAccountingResult(
            session_id="x",
            expected_symbol_count=100,
            verified_count=50,
            absent_count=40,
            conflict_count=5,
            status=sm.SessionAccountingStatus.COMPLETE,
        )


# ---------------------------------------------------------------------------
# section 44 -- manifest happy path
# ---------------------------------------------------------------------------


def test_build_session_manifest_happy_path():
    symbols = _frozen_symbols()
    evaluations = []
    for i, symbol in enumerate(symbols):
        if i < 60:
            evaluations.append(
                _make_evaluation(
                    symbol,
                    capture_status=CaptureStatus.VALID_CAPTURE_AVAILABLE,
                    evaluation_integrity_status=EvaluationIntegrityStatus.CLEAN,
                    technical_observation_eligible=True,
                )
            )
        elif i < 90:
            evaluations.append(
                _make_evaluation(
                    symbol,
                    capture_status=CaptureStatus.NO_VALID_CAPTURE_AVAILABLE,
                    evaluation_integrity_status=EvaluationIntegrityStatus.AUDIT_INCOMPLETE,
                    technical_observation_eligible=False,
                )
            )
        else:
            evaluations.append(
                _make_evaluation(
                    symbol,
                    capture_status=CaptureStatus.INFRASTRUCTURE_BLOCKED,
                    evaluation_integrity_status=EvaluationIntegrityStatus.CLEAN,
                    technical_observation_eligible=False,
                )
            )

    manifest = sm.build_session_manifest(
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        protocol_sha256="a" * 64,
        freeze_manifest_sha256="b" * 64,
        frozen_symbols=symbols,
        final_evaluations=evaluations,
    )

    assert manifest.manifest_schema_version == sm.TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION
    assert manifest.session_id == compute_session_id(PROTOCOL, T_DATE)
    assert manifest.expected_symbol_count == 100
    assert sum(manifest.capture_status_counts.values()) == 100
    assert sum(manifest.evaluation_integrity_status_counts.values()) == 100
    assert manifest.technical_observation_eligible_count == 60
    assert manifest.technical_observation_eligible_count == manifest.capture_status_counts["VALID_CAPTURE_AVAILABLE"]

    expected_ids = sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, symbols)
    assert manifest.expected_evaluation_ids_sha256 == sm.compute_expected_evaluation_ids_sha256(expected_ids)

    pairs = [(evaluation.evaluation_id, evaluation.record_content_sha256) for evaluation in evaluations]
    assert manifest.final_evaluation_records_sha256 == sm.compute_final_evaluation_records_sha256(pairs)

    content = manifest.to_document_fields()
    stored_hash = content.pop("record_content_sha256")
    assert content_sha256(content) == manifest.record_content_sha256 == stored_hash


# ---------------------------------------------------------------------------
# section 45 -- wrong session
# ---------------------------------------------------------------------------


def test_build_session_manifest_rejects_wrong_session_date_record():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)
    evaluations[-1] = _make_evaluation(symbols[-1], T_session_date="2026-09-10")
    with pytest.raises(ValueError):
        sm.build_session_manifest(
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            protocol_sha256="a" * 64,
            freeze_manifest_sha256="b" * 64,
            frozen_symbols=symbols,
            final_evaluations=evaluations,
        )


# ---------------------------------------------------------------------------
# section 46 -- wrong protocol
# ---------------------------------------------------------------------------


def test_build_session_manifest_rejects_wrong_protocol_version_record():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)
    evaluations[-1] = _make_evaluation(symbols[-1], protocol_version="TECHNICAL_V1_PROTOCOL_V2")
    with pytest.raises(ValueError):
        sm.build_session_manifest(
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            protocol_sha256="a" * 64,
            freeze_manifest_sha256="b" * 64,
            frozen_symbols=symbols,
            final_evaluations=evaluations,
        )


# ---------------------------------------------------------------------------
# section 47 -- duplicate record, no dedupe
# ---------------------------------------------------------------------------


def test_build_session_manifest_rejects_duplicate_evaluation_id_no_dedupe():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)
    evaluations[-1] = evaluations[0]  # duplicate; one expected symbol now missing
    with pytest.raises(ValueError):
        sm.build_session_manifest(
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            protocol_sha256="a" * 64,
            freeze_manifest_sha256="b" * 64,
            frozen_symbols=symbols,
            final_evaluations=evaluations,
        )


# ---------------------------------------------------------------------------
# section 48 -- foreign symbol
# ---------------------------------------------------------------------------


def test_build_session_manifest_rejects_foreign_symbol_record():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)
    evaluations[-1] = _make_evaluation("FOREIGN_SYMBOL_NOT_IN_UNIVERSE")
    with pytest.raises(ValueError):
        sm.build_session_manifest(
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            protocol_sha256="a" * 64,
            freeze_manifest_sha256="b" * 64,
            frozen_symbols=symbols,
            final_evaluations=evaluations,
        )


# ---------------------------------------------------------------------------
# section 49 -- count maps always include zero keys
# ---------------------------------------------------------------------------


def test_manifest_count_maps_include_zero_keys():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)  # all NO_VALID_CAPTURE_AVAILABLE / AUDIT_INCOMPLETE / not eligible
    manifest = sm.build_session_manifest(
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        protocol_sha256="a" * 64,
        freeze_manifest_sha256="b" * 64,
        frozen_symbols=symbols,
        final_evaluations=evaluations,
    )
    assert set(manifest.capture_status_counts.keys()) == {
        "VALID_CAPTURE_AVAILABLE",
        "NO_VALID_CAPTURE_AVAILABLE",
        "INFRASTRUCTURE_BLOCKED",
    }
    assert manifest.capture_status_counts["VALID_CAPTURE_AVAILABLE"] == 0
    assert manifest.capture_status_counts["INFRASTRUCTURE_BLOCKED"] == 0
    assert set(manifest.evaluation_integrity_status_counts.keys()) == {
        "CLEAN",
        "AUDIT_INCOMPLETE",
        "EVIDENCE_INTEGRITY_FAILURE",
        "PROVENANCE_CONFLICT",
    }
    assert manifest.evaluation_integrity_status_counts["CLEAN"] == 0


# ---------------------------------------------------------------------------
# section 50 -- eligible invariant enforced by the builder
# ---------------------------------------------------------------------------


def test_build_session_manifest_rejects_inconsistent_eligible_flag():
    symbols = _frozen_symbols()
    evaluations = _make_full_session(symbols)
    # el-yapımı tutarsızlık: capture_status VALID_CAPTURE_AVAILABLE DEĞİLKEN
    # technical_observation_eligible=True -- FinalEvaluation'ın KENDİSİ bunu
    # engellemez (__post_init__ yok), builder REDDETMELİDİR.
    evaluations[0] = replace(evaluations[0], technical_observation_eligible=True)
    with pytest.raises(ValueError):
        sm.build_session_manifest(
            protocol_version=PROTOCOL,
            T_session_date=T_DATE,
            protocol_sha256="a" * 64,
            freeze_manifest_sha256="b" * 64,
            frozen_symbols=symbols,
            final_evaluations=evaluations,
        )


# ---------------------------------------------------------------------------
# section 51 -- trusted-input statement verified by import inspection
# ---------------------------------------------------------------------------


def test_session_manifest_module_imports_no_repository_or_cloud_layer():
    forbidden_names = {
        "TechnicalV1EvaluationRepository",
        "PersistedFinalEvaluation",
        "EvidenceObjectStore",
        "TechnicalV1AttemptRepository",
    }
    assert forbidden_names.isdisjoint(set(vars(sm)))

    forbidden_modules = {
        "app.repositories.technical_v1_evaluation_repository",
        "app.repositories.technical_v1_attempt_repository",
        "app.research.evidence_object_store",
        "firebase_admin",
        "google.cloud.firestore",
        "google.cloud.storage",
    }
    for name, value in vars(sm).items():
        module = getattr(value, "__module__", None)
        assert module not in forbidden_modules, f"{name} comes from forbidden module {module}"


def test_session_manifest_module_has_no_filesystem_or_cloud_literal_imports():
    source = inspect.getsource(sm)
    for forbidden_token in ("import pathlib", "from pathlib", "json.load", "open(", "import os", "from os "):
        assert forbidden_token not in source
    for forbidden_module_literal in ("firebase_admin", "google.cloud.firestore", "google.cloud.storage"):
        assert forbidden_module_literal not in source


# ---------------------------------------------------------------------------
# Ekstra -- TechnicalV1SessionManifest'in KENDİ __post_init__ doğrulamaları
# (builder'dan bağımsız, doğrudan yapı testleri)
# ---------------------------------------------------------------------------


def _valid_manifest_kwargs() -> dict:
    symbols = _frozen_symbols()
    ids = sm.derive_expected_evaluation_ids(PROTOCOL, T_DATE, symbols)
    expected_hash = sm.compute_expected_evaluation_ids_sha256(ids)
    records_hash = sm.compute_final_evaluation_records_sha256([(id_, id_) for id_ in ids])
    return dict(
        manifest_schema_version=sm.TECHNICAL_V1_SESSION_MANIFEST_SCHEMA_VERSION,
        session_id=compute_session_id(PROTOCOL, T_DATE),
        protocol_version=PROTOCOL,
        T_session_date=T_DATE,
        protocol_sha256="a" * 64,
        freeze_manifest_sha256="b" * 64,
        expected_symbol_count=100,
        expected_evaluation_ids_sha256=expected_hash,
        final_evaluation_records_sha256=records_hash,
        capture_status_counts={
            "VALID_CAPTURE_AVAILABLE": 0,
            "NO_VALID_CAPTURE_AVAILABLE": 100,
            "INFRASTRUCTURE_BLOCKED": 0,
        },
        evaluation_integrity_status_counts={
            "CLEAN": 0,
            "AUDIT_INCOMPLETE": 100,
            "EVIDENCE_INTEGRITY_FAILURE": 0,
            "PROVENANCE_CONFLICT": 0,
        },
        technical_observation_eligible_count=0,
    )


def test_manifest_direct_construction_accepts_valid_kwargs():
    manifest = sm.TechnicalV1SessionManifest(**_valid_manifest_kwargs())
    assert manifest.session_id == compute_session_id(PROTOCOL, T_DATE)


def test_manifest_rejects_wrong_schema_version():
    kwargs = {**_valid_manifest_kwargs(), "manifest_schema_version": "some_other_version"}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_untrusted_session_id():
    kwargs = {**_valid_manifest_kwargs(), "session_id": "d" * 64}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_wrong_expected_symbol_count():
    kwargs = {**_valid_manifest_kwargs(), "expected_symbol_count": 99}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_missing_capture_status_key():
    counts = dict(_valid_manifest_kwargs()["capture_status_counts"])
    del counts["INFRASTRUCTURE_BLOCKED"]
    kwargs = {**_valid_manifest_kwargs(), "capture_status_counts": counts}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_extra_capture_status_key():
    counts = dict(_valid_manifest_kwargs()["capture_status_counts"])
    counts["SOME_EXTRA_KEY"] = 0
    kwargs = {**_valid_manifest_kwargs(), "capture_status_counts": counts}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_bool_as_count():
    counts = dict(_valid_manifest_kwargs()["capture_status_counts"])
    counts["VALID_CAPTURE_AVAILABLE"] = True
    counts["NO_VALID_CAPTURE_AVAILABLE"] = 99
    kwargs = {**_valid_manifest_kwargs(), "capture_status_counts": counts}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_negative_count():
    counts = dict(_valid_manifest_kwargs()["capture_status_counts"])
    counts["VALID_CAPTURE_AVAILABLE"] = -1
    counts["NO_VALID_CAPTURE_AVAILABLE"] = 101
    kwargs = {**_valid_manifest_kwargs(), "capture_status_counts": counts}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_capture_sum_not_matching_expected_symbol_count():
    counts = {"VALID_CAPTURE_AVAILABLE": 1, "NO_VALID_CAPTURE_AVAILABLE": 1, "INFRASTRUCTURE_BLOCKED": 1}
    kwargs = {**_valid_manifest_kwargs(), "capture_status_counts": counts, "technical_observation_eligible_count": 1}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_rejects_eligible_count_mismatch_with_valid_capture_count():
    kwargs = {**_valid_manifest_kwargs(), "technical_observation_eligible_count": 1}
    with pytest.raises(ValueError):
        sm.TechnicalV1SessionManifest(**kwargs)


def test_manifest_record_content_sha256_regression():
    manifest = sm.TechnicalV1SessionManifest(**_valid_manifest_kwargs())
    content = manifest.to_document_fields()
    stored_hash = content.pop("record_content_sha256")
    assert content_sha256(content) == manifest.record_content_sha256 == stored_hash


def test_manifest_to_content_fields_excludes_record_content_sha256():
    manifest = sm.TechnicalV1SessionManifest(**_valid_manifest_kwargs())
    assert "record_content_sha256" not in manifest.to_content_fields()
    assert "record_content_sha256" in manifest.to_document_fields()


def test_manifest_has_no_session_status_or_operational_fields():
    manifest = sm.TechnicalV1SessionManifest(**_valid_manifest_kwargs())
    forbidden = {"session_status", "retry", "completion_flag", "operational_error", "last_error"}
    content_keys = {key.lower() for key in manifest.to_content_fields()}
    assert forbidden.isdisjoint(content_keys)
