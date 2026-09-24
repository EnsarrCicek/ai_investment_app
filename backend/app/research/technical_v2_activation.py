"""TECHNICAL V2-R1 — aktivasyon orkestrasyonu (HENÜZ HİÇBİR YERDEN ÇAĞRILMIYOR).

Mevcut sözleşme (activation_lock.py / activation_event.py, HATA 12N3C2/13B):
aktivasyon = (1) create-only aktivasyon KİLİDİ (kimlik: protocol_version ×
metodoloji parmak izi × proje × Cloud Run servis × revision) + (2) o kilidi
bağlayan, protocol_version başına SINGLETON `INITIAL` aktivasyon OLAYI. Attempt
execution yalnızca bir olayın yetkilendirdiği kilitle claim yapar.

Bu modül:
  * Hiçbir yazmadan ÖNCE: V2 kimliği + çalışan motor, runtime kimliği
    (mevcut `observe_runtime_fingerprint` ilkeli; operatörün yetkilendirdiği
    beklenen proje/servis/revision ile BİREBİR), yetki girdileri (git sha
    biçimi), mevcut kilit/olay durumu (salt okuma) ve PRODUCTION readiness
    (gerçek Firestore okuyucusu + canlı scoring config + runtime) doğrulanır.
    Herhangi biri başarısız/okunamaz ise akış DURUR -- sıfır yazma.
  * Yazma yalnızca mevcut repository'lerin atomik `DocumentReference.create()`
    yolundan yapılır; AlreadyExists -> tam doğrulama + içerik hash'i; çakışma
    -> ProvenanceConflictError (kör silme/overwrite/rollback YOK).
  * Kısmi durum (kilit yazıldı, olay yazılamadı): AYNI yetkilendirme isteğinin
    tekrarı, YALNIZCA TAM o aday kilit (içerik eşit) mevcutsa ve başka hiçbir V2
    kilidi/olayı/kanıt kaydı yoksa olayı tamamlar -- config/runtime/metodoloji
    kontrolleri (taze readiness) atlanmaz. Başka her şey BLOCKED.
  * Aynı istek zaten tamamlanmışsa (INITIAL olay bu adayı bağlıyor, kilit
    içerik-eşit) ALREADY_ACTIVATED döner -- sıfır yazma; bu yalnızca MEVCUT
    kaydın raporudur, readiness yeniden değerlendirilmez (`readiness_evaluated`
    False) ve güncel uygunluk iddia edilmez.
  * `effective_holdout_start` burada kural olarak uygulanmaz; `technical_holdout`
    (tek uygulama yeri) ile INITIAL olayın create_time'ından TÜRETİLİP raporlanır
    -- attempt execution aynı fonksiyonu kullanır. Yazmadan önce yerel saatle
    yalnızca ön kontrol yapılır (belirlenemiyorsa BLOCKED); gerçek create_time
    için belirlenemezse sonuç ACTIVATED_HOLDOUT_START_UNDETERMINABLE olur.
  * Proje kimliği: public girişte FIREBASE_PROJECT_ID açıkça ayarlanmış (sessiz
    config varsayılanı DEĞİL), beklenen projeye eşit ve Firestore istemcisinin
    gerçek projesiyle aynı olmalıdır; aksi halde Firestore bağımlılıkları hiç
    kurulmaz. K_SERVICE/K_REVISION Cloud Run runtime BAĞLAMIDIR (platformun ortam
    değişkenleri), bağımsız bir kimlik kanıtı/attestation DEĞİLDİR.
  * Revision geçişi (`run_technical_v2_revision_authorization`): mevcut
    sözleşmenin `LOCK_AUTHORIZED` olayı ile, INITIAL kilitle yalnızca runtime
    revision'ı farklı yeni bir kilit TAZE PRODUCTION readiness ile
    yetkilendirilir. INITIAL olay ve holdout başlangıcı değişmez, yeni deney
    başlamaz. Önceki kilidin yetkisini geri alma sözleşmede tanımlı DEĞİLDİR --
    önceki kilit yetkili kalır.

Readiness kontrolü tek başına yarışları önlemez: iki eşzamanlı istek aynı adayla
gelirse repository create'leri CREATED/IDEMPOTENT_REUSE ayrımını yapar; farklı
adaylarla gelirse INITIAL singleton'ı yalnızca birini yetkilendirir, diğeri
ProvenanceConflictError ile BLOCKED olur (yazılmış yetkisiz kilidi SİLİNMEZ;
temizlik ayrı bir bakım maddesidir).

Production giriş noktaları bağımlılıklarını KENDİLERİ kurar; readiness
raporu/okuyucu/override ALMAZ. `_activate` / `_authorize_revision` yalnızca
modül-içi test enjeksiyonudur.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ACTIVATED = "ACTIVATED"
ALREADY_ACTIVATED = "ALREADY_ACTIVATED"
AUTHORIZED = "AUTHORIZED"
ALREADY_AUTHORIZED = "ALREADY_AUTHORIZED"
# INITIAL olay KALICI olarak yazıldı ama gerçek create_time için başlangıç
# authoritative takvimle belirlenemiyor: başarı/kanıt uygunluğu DEĞİL.
ACTIVATED_HOLDOUT_START_UNDETERMINABLE = "ACTIVATED_HOLDOUT_START_UNDETERMINABLE"
BLOCKED = "BLOCKED"
PARTIAL_LOCK_WITHOUT_EVENT = "PARTIAL_LOCK_WITHOUT_EVENT"

_EXISTING_RECORD_NOTE = (
    "Reports the existing record only; current readiness/eligibility was NOT re-evaluated and no write was performed."
)


class _Stop(Exception):
    def __init__(self, *codes: str):
        super().__init__(",".join(codes))
        self.codes = codes


@dataclass(frozen=True)
class TechnicalV2ActivationReport:
    status: str
    reason_codes: tuple[str, ...] = ()
    activation_lock_id: str | None = None
    activation_event_id: str | None = None
    lock_outcome: str | None = None
    event_outcome: str | None = None
    recovered_partial_state: bool = False
    readiness_failed_gates: tuple[str, ...] = ()
    readiness_evaluated: bool = False
    initial_event_create_time_observed: str | None = None
    effective_holdout_start: str | None = None
    writes_attempted: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


def run_technical_v2_activation(
    *,
    expected_project_id: str,
    expected_runtime_service: str,
    expected_runtime_revision: str,
    methodology_git_commit: str,
    methodology_approval_reference: str,
) -> TechnicalV2ActivationReport:
    """PRODUCTION giriş noktası -- deploy edilmiş hedef revision'ın İÇİNDE
    çalışmalıdır. Beklenen proje/servis/revision ve iki git sha'sı operatörün
    YETKİLENDİRME girdileridir (gözlenen runtime ile BİREBİR eşleşmek zorundadır);
    kimlik/parmak izi/config/durum burada ölçülür, dışarıdan alınmaz."""
    deps = _production_dependencies(expected_project_id)
    if isinstance(deps, TechnicalV2ActivationReport):
        return deps
    return _activate(
        expected_project_id=expected_project_id,
        expected_runtime_service=expected_runtime_service,
        expected_runtime_revision=expected_runtime_revision,
        methodology_git_commit=methodology_git_commit,
        methodology_approval_reference=methodology_approval_reference,
        **deps,
    )


def run_technical_v2_revision_authorization(
    *,
    expected_project_id: str,
    expected_runtime_service: str,
    expected_runtime_revision: str,
    methodology_git_commit: str,
    methodology_approval_reference: str,
) -> TechnicalV2ActivationReport:
    """PRODUCTION giriş noktası (revision geçişi) -- YENİ hedef revision'ın
    İÇİNDE çalışmalıdır; aynı güven sınırı ve aynı yetki girdileri."""
    deps = _production_dependencies(expected_project_id)
    if isinstance(deps, TechnicalV2ActivationReport):
        return deps
    return _authorize_revision(
        expected_project_id=expected_project_id,
        expected_runtime_service=expected_runtime_service,
        expected_runtime_revision=expected_runtime_revision,
        methodology_git_commit=methodology_git_commit,
        methodology_approval_reference=methodology_approval_reference,
        **deps,
    )


def _production_dependencies(expected_project_id: str):
    """Proje kimliği üç kaynakta (beklenen / açık runtime env / Firestore
    istemcisi) tutarlı olmadıkça bağımlılıklar KURULMAZ -- okuma/yazma yok."""
    import os

    from app.core.firebase import get_firestore_client
    from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
    from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
    from app.research.technical_v1_runtime_identity import observe_runtime_fingerprint
    from app.research.technical_v2_readiness import (
        FirestoreReadOnlyActivationStateReader,
        live_scoring_config_hash_from,
        observe_runtime_identity,
    )

    # config.FIREBASE_PROJECT_ID, ortam değişkeni yoksa sessizce kod içi
    # varsayılana düşer; aktivasyon yolu bu varsayılanı kabul etmez.
    env_project = os.environ.get("FIREBASE_PROJECT_ID")
    if not env_project:
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=("RUNTIME_PROJECT_ID_NOT_EXPLICIT",))
    if env_project != expected_project_id:
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=("RUNTIME_PROJECT_ID_MISMATCH",))
    try:
        db = get_firestore_client()
    except Exception as exc:  # noqa: BLE001 -- fail closed, mesaj yazdırılmaz
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=("FIRESTORE_CLIENT_UNAVAILABLE", type(exc).__name__))
    if getattr(db, "project", None) != expected_project_id:
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=("FIRESTORE_CLIENT_PROJECT_MISMATCH",))
    return {
        "lock_repo": TechnicalV1ActivationLockRepository(db=db),
        "event_repo": TechnicalV1ActivationEventRepository(db=db),
        "state_reader": FirestoreReadOnlyActivationStateReader(db),
        "live_scoring_config_hash_reader": live_scoring_config_hash_from(db),
        "runtime_identity_reader": observe_runtime_identity,
        "runtime_fingerprint_observer": observe_runtime_fingerprint,
    }


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _prepare_candidate(
    *,
    expected_project_id: str,
    expected_runtime_service: str,
    expected_runtime_revision: str,
    methodology_git_commit: str,
    methodology_approval_reference: str,
    runtime_fingerprint_observer,
):
    """Aktivasyon ve revision geçişi için ORTAK ön kontroller; hata -> _Stop."""
    from app.research.activation_lock import (
        TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION,
        TechnicalV1ActivationLock,
        compute_activation_lock_id,
        compute_runtime_fingerprint,
    )
    from app.research.technical_versions import (
        TECHNICAL_V2_SPEC,
        assert_identity_matches_running_engine,
        load_evaluation_identity,
        validate_lock_identity,
    )

    # ---- 1) V2 kimliği + çalışan motor
    try:
        identity = load_evaluation_identity(TECHNICAL_V2_SPEC)
        assert_identity_matches_running_engine(identity)
    except Exception as exc:  # noqa: BLE001
        raise _Stop("V2_IDENTITY_OR_ENGINE_MISMATCH", type(exc).__name__) from exc

    # ---- 2) runtime kimliği: mevcut ilkel + operatörün yetkilendirdiği değerler
    try:
        observed = runtime_fingerprint_observer()
    except Exception as exc:  # noqa: BLE001
        raise _Stop("RUNTIME_IDENTITY_UNOBSERVABLE", type(exc).__name__) from exc
    try:
        expected = compute_runtime_fingerprint(expected_project_id, expected_runtime_service, expected_runtime_revision)
    except Exception as exc:  # noqa: BLE001
        raise _Stop("INVALID_AUTHORIZATION_INPUT", type(exc).__name__) from exc
    if observed != expected:
        raise _Stop("RUNTIME_IDENTITY_NOT_AUTHORIZED_TARGET")

    # ---- 3) aday kilit (yetki girdileri kilidin kendi doğrulamasından geçer)
    try:
        lock_id = compute_activation_lock_id(
            protocol_version=identity.protocol_version,
            authorized_methodology_source_fingerprint=identity.methodology_source_fingerprint,
            authorized_project_id=expected_project_id,
            authorized_runtime_service=expected_runtime_service,
            authorized_runtime_revision=expected_runtime_revision,
        )
        candidate = TechnicalV1ActivationLock(
            activation_lock_schema_version=TECHNICAL_V1_ACTIVATION_LOCK_SCHEMA_VERSION,
            activation_lock_id=lock_id,
            protocol_version=identity.protocol_version,
            protocol_sha256=identity.protocol_sha256,
            freeze_manifest_sha256=identity.freeze_manifest_sha256,
            methodology_git_commit=methodology_git_commit,
            authorized_methodology_source_fingerprint=identity.methodology_source_fingerprint,
            authorized_project_id=expected_project_id,
            authorized_runtime_service=expected_runtime_service,
            authorized_runtime_revision=expected_runtime_revision,
            methodology_approval_reference=methodology_approval_reference,
        )
        validate_lock_identity(candidate, identity)
    except Exception as exc:  # noqa: BLE001
        raise _Stop("INVALID_AUTHORIZATION_INPUT", type(exc).__name__) from exc
    return identity, candidate


def _lock_hash(lock) -> str:
    return lock.to_document_fields()["record_content_sha256"]


def _holdout_start_or_stop(activation_time) -> str:
    from app.research.technical_holdout import compute_effective_holdout_start

    try:
        return compute_effective_holdout_start(activation_time).isoformat()
    except Exception as exc:  # noqa: BLE001 -- kural uydurulmaz; belirlenemiyorsa durur
        raise _Stop("HOLDOUT_START_UNDETERMINABLE", type(exc).__name__) from exc


def _initial_record_report(status: str, persisted_event, *, notes: tuple[str, ...], **fields) -> TechnicalV2ActivationReport:
    """INITIAL kaydını, başlangıcı GERÇEK create_time'ından türeterek raporlar.
    Türetilemiyorsa (okunamadı / takvim kapsamı dışı) başarı DEĞİL:
    ACTIVATED_HOLDOUT_START_UNDETERMINABLE. Kalıcı kayıt silinmez; aynı isteğin
    tekrarı sıfır yazmayla aynı sonucu verir; attempt execution aynı kuralla
    claim'den önce durur. Takvim ileride kapsadığında başlangıç AYNI create_time'dan
    türetilir -- kaymaz."""
    if persisted_event is None:
        return TechnicalV2ActivationReport(
            status=ACTIVATED_HOLDOUT_START_UNDETERMINABLE, reason_codes=("INITIAL_EVENT_UNREADABLE_AFTER_CREATE",),
            notes=("INITIAL event write reported success but its create_time could not be read; not eligible "
                   "for evidence collection until the same request is re-run and derives the start.",), **fields)
    try:
        start = _holdout_start_or_stop(persisted_event.create_time)
    except _Stop as stop:
        return TechnicalV2ActivationReport(
            status=ACTIVATED_HOLDOUT_START_UNDETERMINABLE, reason_codes=stop.codes,
            initial_event_create_time_observed=_iso(persisted_event.create_time),
            notes=("INITIAL event is persisted and NOT deleted; effective_holdout_start cannot be derived from its "
                   "create_time with the authoritative calendar. Evidence collection stays blocked (attempts fail "
                   "closed before claim); the start is never shifted.",), **fields)
    return TechnicalV2ActivationReport(
        status=status, initial_event_create_time_observed=_iso(persisted_event.create_time),
        effective_holdout_start=start, notes=notes, **fields)


def _activate(
    *,
    expected_project_id: str,
    expected_runtime_service: str,
    expected_runtime_revision: str,
    methodology_git_commit: str,
    methodology_approval_reference: str,
    lock_repo,
    event_repo,
    state_reader,
    live_scoring_config_hash_reader,
    runtime_identity_reader,
    runtime_fingerprint_observer,
    clock=_utcnow,
) -> TechnicalV2ActivationReport:
    from app.research.activation_event import build_initial_activation_event, compute_initial_activation_event_id
    from app.research.evidence_models import ProvenanceConflictError
    from app.research.technical_v2_readiness import MODE_PRODUCTION, validate_technical_v2_release_readiness

    writes = 0
    lock_id = event_id = None
    try:
        identity, candidate = _prepare_candidate(
            expected_project_id=expected_project_id,
            expected_runtime_service=expected_runtime_service,
            expected_runtime_revision=expected_runtime_revision,
            methodology_git_commit=methodology_git_commit,
            methodology_approval_reference=methodology_approval_reference,
            runtime_fingerprint_observer=runtime_fingerprint_observer,
        )
        lock_id = candidate.activation_lock_id
        candidate_hash = _lock_hash(candidate)
        event_id = compute_initial_activation_event_id(protocol_version=identity.protocol_version)

        # ---- 4) mevcut durum (salt okuma)
        try:
            existing_event = event_repo.get_verified(event_id)
            existing_lock = lock_repo.get_verified(lock_id)
            v2_lock_ids = set(state_reader.activation_lock_ids(identity.protocol_version))
        except ProvenanceConflictError as exc:
            raise _Stop("EXISTING_STATE_PROVENANCE_CONFLICT") from exc
        except Exception as exc:  # noqa: BLE001
            raise _Stop("EXISTING_STATE_UNREADABLE", type(exc).__name__) from exc

        def _lock_matches(persisted) -> bool:
            return persisted is not None and _lock_hash(persisted.lock) == candidate_hash

        if existing_event is not None:
            if existing_event.event.activation_lock_id != lock_id:
                raise _Stop("INITIAL_EVENT_BINDS_ANOTHER_LOCK")
            if not _lock_matches(existing_lock):
                raise _Stop("INITIAL_EVENT_WITHOUT_MATCHING_LOCK")
            return _initial_record_report(
                ALREADY_ACTIVATED, existing_event, activation_lock_id=lock_id, activation_event_id=event_id,
                notes=(_EXISTING_RECORD_NOTE,))

        if existing_lock is not None and not _lock_matches(existing_lock):
            raise _Stop("CANDIDATE_LOCK_ID_HAS_DIFFERENT_CONTENT")
        recovering = existing_lock is not None
        if v2_lock_ids != ({lock_id} if recovering else set()):
            raise _Stop("OTHER_V2_ACTIVATION_LOCK_PRESENT")

        # ---- 5) TAZE PRODUCTION readiness (gerçek okuyucu + canlı config + runtime);
        #         kurtarmada da atlanmaz, yalnızca kendi aday kilidinin varlığı tolere edilir
        readiness = validate_technical_v2_release_readiness(
            mode=MODE_PRODUCTION,
            activation_state=state_reader,
            live_scoring_config_hash_reader=live_scoring_config_hash_reader,
            runtime_identity_reader=runtime_identity_reader,
        )
        tolerated = {"NO_ACTIVATION_LOCK"} if recovering else set()
        if readiness.verification_scope != MODE_PRODUCTION or set(readiness.failed_gates) - tolerated \
                or (not recovering and readiness.status != "READY") \
                or (recovering and readiness.activation_lock_state != "PRESENT"):
            return TechnicalV2ActivationReport(
                status=BLOCKED, reason_codes=("PRODUCTION_READINESS_FAILED",), activation_lock_id=lock_id,
                activation_event_id=event_id, readiness_failed_gates=tuple(readiness.failed_gates),
                readiness_evaluated=True)
        # YALNIZCA ön kontrol (yerel saat): başlangıç şimdi bile belirlenemiyorsa
        # yazma yok. Kesin başlangıç yazmadan SONRA INITIAL'ın create_time'ından türetilir.
        _holdout_start_or_stop(clock())

        # ---- 6) atomik yazmalar (mevcut repository sözleşmesi)
        if recovering:
            lock_outcome = "PREEXISTING_VERIFIED"
        else:
            writes += 1
            try:
                lock_outcome = lock_repo.create(candidate).value
            except ProvenanceConflictError as exc:
                raise _Stop("LOCK_CREATE_PROVENANCE_CONFLICT") from exc

        event = build_initial_activation_event(protocol_version=identity.protocol_version, activation_lock_id=lock_id)
        writes += 1
        try:
            event_outcome = event_repo.create(event).value
        except ProvenanceConflictError:
            return TechnicalV2ActivationReport(
                status=BLOCKED, reason_codes=("INITIAL_EVENT_CONFLICT", PARTIAL_LOCK_WITHOUT_EVENT),
                activation_lock_id=lock_id, activation_event_id=event_id, lock_outcome=lock_outcome,
                recovered_partial_state=recovering, writes_attempted=writes, readiness_evaluated=True,
                notes=("Another lock is authorized by the INITIAL event; this lock stays unauthorized and is NOT deleted.",))
        except Exception as exc:  # noqa: BLE001 -- geçici yazma hatası: aynı isteğin tekrarı kurtarır
            return TechnicalV2ActivationReport(
                status=BLOCKED, reason_codes=("INITIAL_EVENT_WRITE_FAILED", PARTIAL_LOCK_WITHOUT_EVENT, type(exc).__name__),
                activation_lock_id=lock_id, activation_event_id=event_id, lock_outcome=lock_outcome,
                recovered_partial_state=recovering, writes_attempted=writes, readiness_evaluated=True,
                notes=("Retry the SAME authorization request to complete the INITIAL event.",))

        try:
            persisted_event = event_repo.get_verified(event_id)
        except Exception:  # noqa: BLE001 -- olay yazıldı ama kesin zaman okunamadı
            persisted_event = None
        return _initial_record_report(
            ACTIVATED, persisted_event, activation_lock_id=lock_id, activation_event_id=event_id,
            lock_outcome=lock_outcome, event_outcome=event_outcome, recovered_partial_state=recovering,
            writes_attempted=writes, readiness_evaluated=True,
            notes=("effective_holdout_start is derived from the INITIAL event create_time (technical_holdout).",))
    except _Stop as stop:
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=stop.codes, activation_lock_id=lock_id,
                                           activation_event_id=event_id, writes_attempted=writes)


def _authorize_revision(
    *,
    expected_project_id: str,
    expected_runtime_service: str,
    expected_runtime_revision: str,
    methodology_git_commit: str,
    methodology_approval_reference: str,
    lock_repo,
    event_repo,
    state_reader,
    live_scoring_config_hash_reader,
    runtime_identity_reader,
    runtime_fingerprint_observer,
) -> TechnicalV2ActivationReport:
    """Revision geçişi: INITIAL kilitle YALNIZCA runtime revision'ı farklı yeni
    kilit + `LOCK_AUTHORIZED` olayı. Önceki READY raporu kullanılmaz (taze
    PRODUCTION readiness); INITIAL olay ve holdout başlangıcı değişmez."""
    from app.research.activation_event import (
        build_lock_authorized_event,
        compute_initial_activation_event_id,
        compute_lock_authorized_activation_event_id,
    )
    from app.research.evidence_models import ProvenanceConflictError
    from app.research.technical_v2_readiness import MODE_PRODUCTION, validate_technical_v2_release_readiness

    writes = 0
    lock_id = event_id = None
    try:
        identity, candidate = _prepare_candidate(
            expected_project_id=expected_project_id,
            expected_runtime_service=expected_runtime_service,
            expected_runtime_revision=expected_runtime_revision,
            methodology_git_commit=methodology_git_commit,
            methodology_approval_reference=methodology_approval_reference,
            runtime_fingerprint_observer=runtime_fingerprint_observer,
        )
        lock_id = candidate.activation_lock_id
        candidate_hash = _lock_hash(candidate)
        pv = identity.protocol_version
        event_id = compute_lock_authorized_activation_event_id(protocol_version=pv, activation_lock_id=lock_id)

        # ---- mevcut durum (salt okuma)
        try:
            initial = event_repo.get_verified(compute_initial_activation_event_id(protocol_version=pv))
            initial_lock = lock_repo.get_verified(initial.event.activation_lock_id) if initial is not None else None
            existing_authorization = event_repo.get_verified(event_id)
            existing_lock = lock_repo.get_verified(lock_id)
        except ProvenanceConflictError as exc:
            raise _Stop("EXISTING_STATE_PROVENANCE_CONFLICT") from exc
        except Exception as exc:  # noqa: BLE001
            raise _Stop("EXISTING_STATE_UNREADABLE", type(exc).__name__) from exc

        if initial is None:
            raise _Stop("NOT_ACTIVATED")
        if initial_lock is None:
            raise _Stop("INITIAL_EVENT_WITHOUT_LOCK")
        if initial.event.activation_lock_id == lock_id:
            raise _Stop("CANDIDATE_IS_INITIAL_LOCK")
        base = initial_lock.lock
        if (base.authorized_project_id, base.authorized_runtime_service, base.authorized_methodology_source_fingerprint,
                base.protocol_sha256, base.freeze_manifest_sha256) != (
                candidate.authorized_project_id, candidate.authorized_runtime_service,
                candidate.authorized_methodology_source_fingerprint, candidate.protocol_sha256,
                candidate.freeze_manifest_sha256):
            raise _Stop("NOT_A_REVISION_TRANSITION_OF_INITIAL_LOCK")
        holdout_start = _holdout_start_or_stop(initial.create_time)

        if existing_lock is not None and _lock_hash(existing_lock.lock) != candidate_hash:
            raise _Stop("CANDIDATE_LOCK_ID_HAS_DIFFERENT_CONTENT")
        if existing_authorization is not None:
            if existing_lock is None:
                raise _Stop("LOCK_AUTHORIZED_EVENT_WITHOUT_MATCHING_LOCK")
            return TechnicalV2ActivationReport(
                status=ALREADY_AUTHORIZED, activation_lock_id=lock_id, activation_event_id=event_id,
                initial_event_create_time_observed=_iso(initial.create_time), effective_holdout_start=holdout_start,
                notes=(_EXISTING_RECORD_NOTE,))
        recovering = existing_lock is not None

        # ---- TAZE PRODUCTION readiness; aktivasyon zaten var -> yalnızca kilit/olay/
        #      kanıt varlığı kapıları (durum okunabilir olmak şartıyla) tolere edilir
        readiness = validate_technical_v2_release_readiness(
            mode=MODE_PRODUCTION,
            activation_state=state_reader,
            live_scoring_config_hash_reader=live_scoring_config_hash_reader,
            runtime_identity_reader=runtime_identity_reader,
        )
        tolerated = {"NO_ACTIVATION_LOCK", "NO_ACTIVATION_EVENT", "NO_EVIDENCE_COLLECTION_RUNNING"}
        if readiness.verification_scope != MODE_PRODUCTION or set(readiness.failed_gates) - tolerated \
                or readiness.activation_lock_state != "PRESENT" or readiness.activation_event_state != "PRESENT" \
                or readiness.evidence_collection_state not in ("PRESENT", "ABSENT"):
            return TechnicalV2ActivationReport(
                status=BLOCKED, reason_codes=("PRODUCTION_READINESS_FAILED",), activation_lock_id=lock_id,
                activation_event_id=event_id, readiness_failed_gates=tuple(readiness.failed_gates),
                readiness_evaluated=True)

        # ---- atomik yazmalar
        if recovering:
            lock_outcome = "PREEXISTING_VERIFIED"
        else:
            writes += 1
            try:
                lock_outcome = lock_repo.create(candidate).value
            except ProvenanceConflictError as exc:
                raise _Stop("LOCK_CREATE_PROVENANCE_CONFLICT") from exc
        writes += 1
        try:
            event_outcome = event_repo.create(build_lock_authorized_event(protocol_version=pv, activation_lock_id=lock_id)).value
        except ProvenanceConflictError:
            return TechnicalV2ActivationReport(
                status=BLOCKED, reason_codes=("LOCK_AUTHORIZED_EVENT_CONFLICT", PARTIAL_LOCK_WITHOUT_EVENT),
                activation_lock_id=lock_id, activation_event_id=event_id, lock_outcome=lock_outcome,
                recovered_partial_state=recovering, writes_attempted=writes, readiness_evaluated=True)
        except Exception as exc:  # noqa: BLE001 -- geçici yazma hatası: aynı isteğin tekrarı kurtarır
            return TechnicalV2ActivationReport(
                status=BLOCKED,
                reason_codes=("LOCK_AUTHORIZED_EVENT_WRITE_FAILED", PARTIAL_LOCK_WITHOUT_EVENT, type(exc).__name__),
                activation_lock_id=lock_id, activation_event_id=event_id, lock_outcome=lock_outcome,
                recovered_partial_state=recovering, writes_attempted=writes, readiness_evaluated=True,
                notes=("Retry the SAME authorization request to complete the LOCK_AUTHORIZED event.",))
        return TechnicalV2ActivationReport(
            status=AUTHORIZED, activation_lock_id=lock_id, activation_event_id=event_id, lock_outcome=lock_outcome,
            event_outcome=event_outcome, recovered_partial_state=recovering, writes_attempted=writes,
            readiness_evaluated=True, initial_event_create_time_observed=_iso(initial.create_time),
            effective_holdout_start=holdout_start,
            notes=("INITIAL event and effective_holdout_start unchanged; no new experiment started.",
                   "Previously authorized locks stay authorized (revocation is not defined by the contract)."))
    except _Stop as stop:
        return TechnicalV2ActivationReport(status=BLOCKED, reason_codes=stop.codes, activation_lock_id=lock_id,
                                           activation_event_id=event_id, writes_attempted=writes)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None
