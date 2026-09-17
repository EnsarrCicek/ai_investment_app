"""HATA 13B — `app/research/preclaim_authorization.py` saf pre-claim
yetkilendirme katmanı testleri (Firestore/dosya sistemi/ortam erişimi/
provider erişimi olmadan)."""

import ast
import inspect
import textwrap

import pytest

from app.research.activation_event import build_initial_activation_event, build_lock_authorized_event
from app.research.activation_lock import TechnicalV1ActivationLock, compute_activation_lock_id
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError
from app.research.preclaim_authorization import (
    PreClaimAuthorization,
    PreClaimStatus,
    authorize_pre_claim,
)
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol

LOCKED_PROTOCOL_SHA256 = "ee13afdde2a251bd86fc684e0786f01a9d0b12f7a52ebb2b7771693cb1d38f79"

_PROTOCOL_VERSION = "TECHNICAL_V1_PROTOCOL_V1"
_METHODOLOGY_FINGERPRINT = "a" * 64
_PROJECT_ID = "ai-investment-app-2026"
_RUNTIME_SERVICE = "backend-api"
_RUNTIME_REVISION = "backend-api-00042-xyz"
_GIT_SHA = "730ef262f350b97b9290adddbd7c6a38c024729b"

_REAL_FROZEN_MEMBER = "THYAO"
_NOT_A_MEMBER = "FAKE"


@pytest.fixture(scope="module")
def trusted_protocol():
    return load_verified_technical_v1_protocol(LOCKED_PROTOCOL_SHA256)


def _make_lock(
    *, protocol_version, protocol_sha256, authorized_runtime_revision=_RUNTIME_REVISION
) -> TechnicalV1ActivationLock:
    activation_lock_id = compute_activation_lock_id(
        protocol_version=protocol_version,
        authorized_methodology_source_fingerprint=_METHODOLOGY_FINGERPRINT,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=authorized_runtime_revision,
    )
    return TechnicalV1ActivationLock(
        activation_lock_schema_version="technical_v1_activation_lock_v1",
        activation_lock_id=activation_lock_id,
        protocol_version=protocol_version,
        protocol_sha256=protocol_sha256,
        freeze_manifest_sha256="c" * 64,
        methodology_git_commit=_GIT_SHA,
        authorized_methodology_source_fingerprint=_METHODOLOGY_FINGERPRINT,
        authorized_project_id=_PROJECT_ID,
        authorized_runtime_service=_RUNTIME_SERVICE,
        authorized_runtime_revision=authorized_runtime_revision,
        methodology_approval_reference=_GIT_SHA,
    )


def _matching_lock(trusted_protocol) -> TechnicalV1ActivationLock:
    return _make_lock(protocol_version=trusted_protocol.protocol_version, protocol_sha256=trusted_protocol.protocol_sha256)


def _other_lock(trusted_protocol) -> TechnicalV1ActivationLock:
    """`_matching_lock`'tan GERÇEKTEN farklı bir `activation_lock_id`
    üreten ikinci bir kilit -- yalnızca ID string'i override edilerek DEĞİL,
    kimlik-taşıyan alanlardan biri (`authorized_runtime_revision`)
    değiştirilerek (self-consistent kalması için, bkz. `TechnicalV1
    ActivationLock.__post_init__`'in kendi ID yeniden-türetme kontrolü)."""
    return _make_lock(
        protocol_version=trusted_protocol.protocol_version,
        protocol_sha256=trusted_protocol.protocol_sha256,
        authorized_runtime_revision="backend-api-00099-other",
    )


# ---------------------------------------------------------------------------
# section 36 -- no event -> PRE_ACTIVATION
# ---------------------------------------------------------------------------


def test_no_event_is_pre_activation(trusted_protocol):
    lock = _matching_lock(trusted_protocol)
    result = authorize_pre_claim(
        activation_lock=lock, activation_event=None, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
    )
    assert result == PreClaimAuthorization(status=PreClaimStatus.PRE_ACTIVATION)
    assert result.status != PreClaimStatus.AUTHORIZED


# ---------------------------------------------------------------------------
# section 37 -- INITIAL authorizes its own lock
# ---------------------------------------------------------------------------


def test_initial_event_authorizes_its_own_lock(trusted_protocol):
    lock = _matching_lock(trusted_protocol)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    result = authorize_pre_claim(
        activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
    )
    assert result.status == PreClaimStatus.AUTHORIZED


# ---------------------------------------------------------------------------
# section 38 -- INITIAL binding lock A does not authorize lock B
# ---------------------------------------------------------------------------


def test_initial_event_does_not_authorize_a_different_lock(trusted_protocol):
    lock_a = _matching_lock(trusted_protocol)
    lock_b = _other_lock(trusted_protocol)
    assert lock_a.activation_lock_id != lock_b.activation_lock_id
    event_for_a = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock_a.activation_lock_id
    )

    with pytest.raises(ProvenanceConflictError):
        authorize_pre_claim(
            activation_lock=lock_b,
            activation_event=event_for_a,
            trusted_protocol=trusted_protocol,
            symbol=_REAL_FROZEN_MEMBER,
        )


# ---------------------------------------------------------------------------
# section 39 -- a later LOCK_AUTHORIZED lock authorizes fine, no INITIAL needed
# ---------------------------------------------------------------------------


def test_lock_authorized_event_authorizes_the_later_lock(trusted_protocol):
    lock_b = _other_lock(trusted_protocol)
    event = build_lock_authorized_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock_b.activation_lock_id
    )
    result = authorize_pre_claim(
        activation_lock=lock_b, activation_event=event, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
    )
    assert result.status == PreClaimStatus.AUTHORIZED


# ---------------------------------------------------------------------------
# section 40 -- lock/protocol identity mismatch
# ---------------------------------------------------------------------------


def test_lock_protocol_sha256_mismatch_is_provenance_conflict(trusted_protocol):
    lock = _make_lock(protocol_version=trusted_protocol.protocol_version, protocol_sha256="f" * 64)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    with pytest.raises(ProvenanceConflictError):
        authorize_pre_claim(
            activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
        )


def test_lock_protocol_version_mismatch_is_provenance_conflict(trusted_protocol):
    lock = _make_lock(protocol_version="TECHNICAL_V1_PROTOCOL_V2", protocol_sha256=trusted_protocol.protocol_sha256)
    event = build_initial_activation_event(
        protocol_version="TECHNICAL_V1_PROTOCOL_V2", activation_lock_id=lock.activation_lock_id
    )
    with pytest.raises(ProvenanceConflictError):
        authorize_pre_claim(
            activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
        )


def test_lock_protocol_mismatch_is_checked_even_without_an_event(trusted_protocol):
    """section 24 -- lock/protocol iç tutarlılığı, event var/yok'tan
    BAĞIMSIZ kontrol edilir; PRE_ACTIVATION'a sessizce düşmez."""
    lock = _make_lock(protocol_version=trusted_protocol.protocol_version, protocol_sha256="f" * 64)
    with pytest.raises(ProvenanceConflictError):
        authorize_pre_claim(
            activation_lock=lock, activation_event=None, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
        )


# ---------------------------------------------------------------------------
# section 41/42/43 -- frozen universe membership, exact match only
# ---------------------------------------------------------------------------


def test_real_frozen_member_is_authorized(trusted_protocol):
    assert _REAL_FROZEN_MEMBER in trusted_protocol.frozen_symbols
    lock = _matching_lock(trusted_protocol)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    result = authorize_pre_claim(
        activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=_REAL_FROZEN_MEMBER
    )
    assert result.status == PreClaimStatus.AUTHORIZED


def test_symbol_outside_frozen_universe(trusted_protocol):
    assert _NOT_A_MEMBER not in trusted_protocol.frozen_symbols
    lock = _matching_lock(trusted_protocol)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    result = authorize_pre_claim(
        activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=_NOT_A_MEMBER
    )
    assert result.status == PreClaimStatus.OUTSIDE_FROZEN_UNIVERSE


@pytest.mark.parametrize(
    "malformed_form",
    ["thyao", "THYAO.IS", " THYAO", "THYAO "],
    ids=["lowercase", "dotIS_suffix", "leading_space", "trailing_space"],
)
def test_no_symbol_normalization_performed(trusted_protocol, malformed_form):
    assert _REAL_FROZEN_MEMBER in trusted_protocol.frozen_symbols
    lock = _matching_lock(trusted_protocol)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    result = authorize_pre_claim(
        activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=malformed_form
    )
    assert result.status == PreClaimStatus.OUTSIDE_FROZEN_UNIVERSE


# ---------------------------------------------------------------------------
# section 44 -- malformed symbol input fails loudly, never a domain status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("malformed_symbol", [None, 123, ""], ids=["none", "int", "empty_string"])
def test_malformed_symbol_fails_loudly(trusted_protocol, malformed_symbol):
    lock = _matching_lock(trusted_protocol)
    event = build_initial_activation_event(
        protocol_version=trusted_protocol.protocol_version, activation_lock_id=lock.activation_lock_id
    )
    with pytest.raises(EvidenceIntegrityError):
        authorize_pre_claim(
            activation_lock=lock, activation_event=event, trusted_protocol=trusted_protocol, symbol=malformed_symbol
        )


# ---------------------------------------------------------------------------
# section 21 -- closed status enum, no reuse of attempt-result semantics
# ---------------------------------------------------------------------------


def test_preclaim_status_is_a_closed_three_member_enum():
    assert {member.value for member in PreClaimStatus} == {"AUTHORIZED", "PRE_ACTIVATION", "OUTSIDE_FROZEN_UNIVERSE"}


def _function_body_source_without_docstring(func) -> str:
    """Docstring'in METİN olarak yasaklı isimleri AÇIKLAMAK için anması
    (bu oturumda tekrar tekrar karşılaşılan, naif substring-arama yanlış-
    pozitifi) ile fonksiyonun GERÇEKTEN ÇALIŞTIRILABİLİR gövdesini karıştırmamak
    için `ast` ile docstring node'u (varsa) açıkça atlanır."""
    source = textwrap.dedent(inspect.getsource(func))
    func_def = ast.parse(source).body[0]
    body = func_def.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_function_body_does_not_reference_attempt_result_classification_or_native_reason_code():
    body = _function_body_source_without_docstring(authorize_pre_claim)
    assert "AttemptResultClassification" not in body
    assert "native_reason_code" not in body
    assert "SYMBOL_NOT_IN_FROZEN_UNIVERSE" not in body


# ---------------------------------------------------------------------------
# section 29 -- CONFIG/METHODOLOGY/RUNTIME/post-claim UNIVERSE gates not
# duplicated here
# ---------------------------------------------------------------------------


def test_module_does_not_import_identity_gates():
    import app.research.preclaim_authorization as module

    import_lines = [
        line.strip() for line in inspect.getsource(module).splitlines() if line.strip().startswith(("import ", "from "))
    ]
    assert not any("identity_gates" in line for line in import_lines)


# ---------------------------------------------------------------------------
# section 45 -- dependency isolation
# ---------------------------------------------------------------------------


def test_module_performs_no_io_and_does_not_import_attempt_or_provider_modules():
    import app.research.preclaim_authorization as module

    import_lines = [
        line.strip() for line in inspect.getsource(module).splitlines() if line.strip().startswith(("import ", "from "))
    ]
    forbidden_substrings = (
        "firestore",
        "requests",
        "httpx",
        "yfinance",
        "market_data",
        "os.environ",
        "attempt_repository",
        "attempt_models",
        "asset_repository",
        "google.cloud",
    )
    for line in import_lines:
        lowered = line.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"yasaklı bağımlılık bulundu: {line!r}"


def test_module_never_calls_claim_attempt():
    body = _function_body_source_without_docstring(authorize_pre_claim)
    assert "claim_attempt" not in body
