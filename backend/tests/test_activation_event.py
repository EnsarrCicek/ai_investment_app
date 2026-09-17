"""HATA 13B — `app/research/activation_event.py` saf domain modeli testleri
(Firestore/dosya sistemi/ortam erişimi olmadan)."""

import pytest

from app.research.activation_event import (
    TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
    ActivationEventType,
    TechnicalV1ActivationEvent,
    build_initial_activation_event,
    build_lock_authorized_event,
    compute_initial_activation_event_id,
    compute_lock_authorized_activation_event_id,
)
from app.research.canonical_hash import content_sha256

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_OTHER_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V2"
_LOCK_A = "a" * 64
_LOCK_B = "b" * 64


# ---------------------------------------------------------------------------
# INITIAL event ID (section 6, section 30)
# ---------------------------------------------------------------------------


def test_initial_event_id_is_deterministic_for_same_protocol_version():
    event_a = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_a_again = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert event_a.activation_event_id == event_a_again.activation_event_id
    assert event_a.record_content_sha256 == event_a_again.record_content_sha256


def test_initial_event_id_depends_only_on_protocol_version_not_lock():
    """HATA 13B section 6 -- KİLİTLİ, kasıtlı davranış: activation_lock_id
    DEĞİŞSE BİLE INITIAL event ID AYNI kalır (yalnızca İÇERİK değişir)."""
    event_lock_a = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_lock_b = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)

    assert event_lock_a.activation_event_id == event_lock_b.activation_event_id
    assert event_lock_a.record_content_sha256 != event_lock_b.record_content_sha256


def test_initial_event_id_changes_with_protocol_version():
    event_v1 = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_v2 = build_initial_activation_event(protocol_version=_OTHER_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert event_v1.activation_event_id != event_v2.activation_event_id


def test_initial_event_id_matches_manually_computed_formula():
    expected = content_sha256(
        {
            "activation_event_identity": {
                "activation_event_schema_version": TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
                "event_type": "INITIAL",
                "protocol_version": _PROTOCOL_VERSION,
            }
        }
    )
    assert compute_initial_activation_event_id(protocol_version=_PROTOCOL_VERSION) == expected


# ---------------------------------------------------------------------------
# LOCK_AUTHORIZED event ID (section 7, section 31)
# ---------------------------------------------------------------------------


def test_lock_authorized_event_id_is_deterministic_for_same_inputs():
    event_a = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_a_again = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert event_a.activation_event_id == event_a_again.activation_event_id


def test_lock_authorized_event_id_changes_with_activation_lock_id():
    event_lock_a = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_lock_b = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)
    assert event_lock_a.activation_event_id != event_lock_b.activation_event_id


def test_lock_authorized_event_id_changes_with_protocol_version():
    event_v1 = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    event_v2 = build_lock_authorized_event(protocol_version=_OTHER_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert event_v1.activation_event_id != event_v2.activation_event_id


def test_lock_authorized_event_id_matches_manually_computed_formula():
    expected = content_sha256(
        {
            "activation_event_identity": {
                "activation_event_schema_version": TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
                "event_type": "LOCK_AUTHORIZED",
                "protocol_version": _PROTOCOL_VERSION,
                "activation_lock_id": _LOCK_A,
            }
        }
    )
    assert compute_lock_authorized_activation_event_id(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A) == expected


def test_initial_and_lock_authorized_ids_never_collide_for_same_inputs():
    initial = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    lock_authorized = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    assert initial.activation_event_id != lock_authorized.activation_event_id


# ---------------------------------------------------------------------------
# Domain tamper rejection (section 32)
# ---------------------------------------------------------------------------


def test_rejects_wrong_activation_event_id():
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            activation_event_id="f" * 64,  # yanlış -- yeniden hesaplanan ile eşleşmiyor
            event_type=ActivationEventType.INITIAL,
            protocol_version=_PROTOCOL_VERSION,
            activation_lock_id=_LOCK_A,
        )


def test_rejects_wrong_schema_version():
    event_id = compute_initial_activation_event_id(protocol_version=_PROTOCOL_VERSION)
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version="technical_v1_activation_event_v2",
            activation_event_id=event_id,
            event_type=ActivationEventType.INITIAL,
            protocol_version=_PROTOCOL_VERSION,
            activation_lock_id=_LOCK_A,
        )


def test_rejects_malformed_event_type_raw_string():
    """`event_type` TAM OLARAK bir `ActivationEventType` üyesi olmalı --
    ham, eşleşen bir string BİLE (normalizasyon YOK) doğrudan constructor'a
    verilirse reddedilir."""
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            activation_event_id=compute_initial_activation_event_id(protocol_version=_PROTOCOL_VERSION),
            event_type="INITIAL",  # ham string, enum üyesi DEĞİL
            protocol_version=_PROTOCOL_VERSION,
            activation_lock_id=_LOCK_A,
        )


def test_from_document_fields_rejects_unknown_event_type():
    fields = build_initial_activation_event(
        protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A
    ).to_document_fields()
    fields["event_type"] = "REVOKED"
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent.from_document_fields(fields)


def test_rejects_malformed_activation_lock_id():
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            activation_event_id=compute_initial_activation_event_id(protocol_version=_PROTOCOL_VERSION),
            event_type=ActivationEventType.INITIAL,
            protocol_version=_PROTOCOL_VERSION,
            activation_lock_id="not-a-sha256",
        )


def test_rejects_malformed_protocol_version():
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            activation_event_id=compute_initial_activation_event_id(protocol_version=" padded "),
            event_type=ActivationEventType.INITIAL,
            protocol_version=" padded ",
            activation_lock_id=_LOCK_A,
        )


def test_rejects_empty_protocol_version():
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent(
            activation_event_schema_version=TECHNICAL_V1_ACTIVATION_EVENT_SCHEMA_VERSION,
            activation_event_id=compute_initial_activation_event_id(protocol_version=""),
            event_type=ActivationEventType.INITIAL,
            protocol_version="",
            activation_lock_id=_LOCK_A,
        )


def test_from_document_fields_rejects_tampered_record_content_hash():
    fields = build_initial_activation_event(
        protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A
    ).to_document_fields()
    fields["record_content_sha256"] = "d" * 64
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent.from_document_fields(fields)


def test_from_document_fields_rejects_missing_field():
    fields = build_initial_activation_event(
        protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A
    ).to_document_fields()
    del fields["activation_lock_id"]
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent.from_document_fields(fields)


def test_from_document_fields_rejects_unexpected_extra_field():
    fields = build_initial_activation_event(
        protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A
    ).to_document_fields()
    fields["actor_email"] = "someone@example.com"
    with pytest.raises(ValueError):
        TechnicalV1ActivationEvent.from_document_fields(fields)


def test_round_trip_through_document_fields():
    event = build_lock_authorized_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_B)
    reconstructed = TechnicalV1ActivationEvent.from_document_fields(event.to_document_fields())
    assert reconstructed == event


# ---------------------------------------------------------------------------
# No timestamps / no user identity in the domain model (section 8)
# ---------------------------------------------------------------------------


def test_domain_model_carries_no_timestamp_or_user_identity_fields():
    event = build_initial_activation_event(protocol_version=_PROTOCOL_VERSION, activation_lock_id=_LOCK_A)
    fields = event.to_document_fields()
    for forbidden in ("create_time", "created_at", "updated_at", "user_id", "actor", "email", "notes"):
        assert forbidden not in fields
