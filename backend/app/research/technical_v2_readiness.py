"""TECHNICAL V2-R1 — aktivasyon öncesi release gate (YALNIZCA okuma).

Soru: "Bu TAM çalışan build, dondurulmuş protokol altında Technical V2
prospektif kanıt toplamaya başlamak için güvenli mi?"

Bu modül kanıt toplamayı BAŞLATMAZ, hiçbir şey YAZMAZ, performans metriği
(hit rate / getiri / isabet / benchmark / P&L / sınıf performansı) HESAPLAMAZ.

KAPSAM (verification_scope):
  * LOCAL — yalnızca paketlenmiş artefaktlar + bu makinedeki kaynak baytları.
    Canlı Firestore durumu, canlı scoring config ve deploy runtime kimliği
    OKUNMAZ (NOT_RUN). Başarılı sonuç `LOCAL_CHECKS_PASSED`'dir, `READY` DEĞİL;
    sentetik bir okuyucu verilse bile production aktivasyonuna YETMEZ.
  * PRODUCTION — deploy edilmiş konteyner içinde: gerçek salt-okunur Firestore
    okuyucusu, canlı scoring config okuması ve K_SERVICE/K_REVISION runtime
    kimliği ZORUNLUDUR; parmak izi ÇALIŞAN kaynak baytlarından ölçülür (dışarıdan
    verilen değer kabul edilmez). Yalnızca burada `READY` mümkündür.

Kilitli politikalar:
  * DONDURULMUŞ EVREN: TECHNICAL_V2_PROTOCOL_V1 evreni BIST100 üyeliği sonradan
    değişse bile TAM o 100 semboldür; canlı üyelik okunmaz. Evren değişikliği
    YENİ protokol revizyonu gerektirir (sha çıpası kapıyı kapatır).
  * DEPLOY BAYTLARI PARMAK İZİ: çalışan baytların normalize parmak izi
    dondurulmuş V2 parmak izine eşit olmalı; uyuşmazlık HARD BLOCK, override yok.
  * FAIL CLOSED: okunamayan/eksik zorunlu kontrol = başarısız kapı.

CLI: `python -m app.research.technical_v2_readiness [--mode local|production]`
Çıkış kodu: 0 = PRODUCTION READY, 3 = LOCAL_CHECKS_PASSED (aktivasyona yetmez),
1 = NOT_READY. Çıktı secret/kimlik bilgisi içermez.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Protocol

from app.research.canonical_hash import content_sha256

READY = "READY"
LOCAL_CHECKS_PASSED = "LOCAL_CHECKS_PASSED"
NOT_READY = "NOT_READY"
MODE_LOCAL = "LOCAL"
MODE_PRODUCTION = "PRODUCTION"

PRESENT, ABSENT, UNKNOWN, NOT_RUN = "PRESENT", "ABSENT", "UNKNOWN", "NOT_RUN"
FIRESTORE_READ_ONLY = "FIRESTORE_READ_ONLY"


class ActivationStateReader(Protocol):
    """Salt-okunur aktivasyon/kanıt durumu. `source` veri kaynağını bildirir."""

    source: str

    def activation_lock_exists(self, protocol_version: str) -> bool: ...

    def activation_event_exists(self, protocol_version: str) -> bool: ...

    def evidence_collection_running(self, protocol_version: str) -> bool: ...


class FirestoreReadOnlyActivationStateReader:
    """Mevcut technical_v1_* koleksiyonlarında `protocol_version` eşitliğiyle
    YALNIZCA okuma sorgusu (limit 1). create/set/update/delete ÇAĞRILMAZ.
    V1/V2 kayıtları aynı koleksiyonları paylaşır; `protocol_version` alanı ayırır."""

    source = FIRESTORE_READ_ONLY

    def __init__(self, db) -> None:
        self._db = db

    def _any(self, collection: str, protocol_version: str) -> bool:
        query = self._db.collection(collection).where("protocol_version", "==", protocol_version).limit(1)
        return len(list(query.get())) > 0

    def activation_lock_exists(self, protocol_version: str) -> bool:
        from app.repositories.technical_v1_activation_lock_repository import COLLECTION

        return self._any(COLLECTION, protocol_version)

    def activation_lock_ids(self, protocol_version: str, limit: int = 3) -> tuple[str, ...]:
        """Bu protocol_version'a ait kilit doküman ID'leri (salt okuma, limitli)
        -- kısmi-yazım kurtarmasında TAM olarak hangi kilidin var olduğunu
        bilmek için."""
        from app.repositories.technical_v1_activation_lock_repository import COLLECTION

        query = self._db.collection(COLLECTION).where("protocol_version", "==", protocol_version).limit(limit)
        return tuple(sorted(doc.id for doc in query.get()))

    def activation_event_exists(self, protocol_version: str) -> bool:
        from app.repositories.technical_v1_activation_event_repository import COLLECTION

        return self._any(COLLECTION, protocol_version)

    def evidence_collection_running(self, protocol_version: str) -> bool:
        from app.repositories.technical_v1_attempt_repository import ATTEMPT_CLAIMS_COLLECTION, ATTEMPT_RESULTS_COLLECTION
        from app.repositories.technical_v1_evaluation_repository import COLLECTION as EVALUATIONS
        from app.repositories.technical_v1_session_manifest_repository import COLLECTION as SESSIONS
        from app.repositories.technical_v1_session_run_repository import COLLECTION as SESSION_RUNS

        return any(self._any(c, protocol_version)
                   for c in (ATTEMPT_CLAIMS_COLLECTION, ATTEMPT_RESULTS_COLLECTION, SESSION_RUNS, EVALUATIONS, SESSIONS))


class ReadOnlySystemConfigReader:
    """`system_config` için YALNIZCA `get_raw` (document.get). `SystemConfig
    Repository.get()` eksik dokümanı varsayılanlarla YAZABİLDİĞİNDEN bu kapıda
    kullanılmaz."""

    def __init__(self, db) -> None:
        self._db = db

    def get_raw(self, config_id: str) -> dict | None:
        doc = self._db.collection("system_config").document(config_id).get()
        return doc.to_dict() if doc.exists else None


def live_scoring_config_hash_from(db) -> Callable[[], str]:
    """Attempt execution'ın CONFIG kapısının kullandığı AYNI çözümleme
    (`compute_observed_scoring_config_hash`, fail-fast resolve) -- salt okuma."""
    from app.research.technical_v1_scoring_config_values import compute_observed_scoring_config_hash

    return lambda: compute_observed_scoring_config_hash(ReadOnlySystemConfigReader(db))


def observe_runtime_identity() -> dict:
    """Deploy runtime kimliği (K_SERVICE/K_REVISION). Eksikse istisna
    (sahte 'local' değeri üretilmez). Proje kimliği çıktıya yazılmaz."""
    from app.research.technical_v1_runtime_identity import observe_runtime_fingerprint
    import os

    observe_runtime_fingerprint()  # eksik env -> RuntimeIdentityUnobservableError
    return {"service": os.environ["K_SERVICE"], "revision": os.environ["K_REVISION"]}


@dataclass(frozen=True)
class TechnicalV2ReadinessResult:
    status: str
    verification_scope: str
    production_activation_eligible: bool
    technical_version: str | None
    protocol_version: str | None
    engine_version: str | None
    protocol_sha256: str | None
    freeze_manifest_sha256: str | None
    scoring_config_sha256: str | None
    live_scoring_config_status: str
    methodology_source_fingerprint: str | None
    observed_methodology_source_fingerprint: str | None
    fingerprint_source: str
    fingerprint_normalized: bool
    universe_count: int | None
    holdout_active: bool | None
    effective_holdout_start: str | None
    activation_state_source: str
    activation_lock_state: str
    activation_event_state: str
    evidence_collection_state: str
    runtime_identity_status: str
    runtime_service: str | None
    runtime_revision: str | None
    failed_gates: tuple[str, ...] = field(default_factory=tuple)
    not_run_checks: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def validate_technical_v2_release_readiness(
    *,
    mode: str = MODE_LOCAL,
    activation_state: ActivationStateReader | None = None,
    live_scoring_config_hash_reader: Callable[[], str] | None = None,
    runtime_identity_reader: Callable[[], dict] | None = None,
    today: date | None = None,
    observed_methodology_fingerprint: str | None = None,
    running_engine_version: str | None = None,
    spec=None,
) -> TechnicalV2ReadinessResult:
    """Tüm kapılar bağımsız değerlendirilir. PRODUCTION'da canlı kontrollerin
    her biri zorunludur; LOCAL'de yapılmayanlar `not_run_checks`'e yazılır ve
    sonuç en fazla `LOCAL_CHECKS_PASSED` olur."""
    from app.engines.technical.engine import ENGINE_VERSION
    from app.engines.technical.scoring import compute_scoring_config_hash
    from app.research.methodology_fingerprint import compute_methodology_source_fingerprint
    from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
    from app.research.technical_v1_scoring_config_values import TechnicalV1MethodologySupersededError
    from app.research.technical_versions import (
        TECHNICAL_V1_SPEC,
        TECHNICAL_V2_SPEC,
        assert_identity_matches_running_engine,
        load_evaluation_identity,
    )

    if mode not in (MODE_LOCAL, MODE_PRODUCTION):
        raise ValueError(f"bilinmeyen mode: {mode!r}")
    production = mode == MODE_PRODUCTION
    spec = spec or TECHNICAL_V2_SPEC
    running_engine = running_engine_version or ENGINE_VERSION
    failed: list[str] = []
    not_run: list[str] = []
    warnings: list[str] = []

    def gate(code: str, ok) -> None:
        try:
            passed = ok() if callable(ok) else bool(ok)
        except Exception:  # noqa: BLE001 -- fail closed
            passed = False
        if not passed:
            failed.append(code)

    try:
        protocol = json.loads(spec.protocol_path.read_text(encoding="utf-8"))
        manifest = json.loads(spec.freeze_manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        protocol, manifest = {}, {}
        failed.append("ARTIFACTS_UNREADABLE")
    refs = protocol.get("methodology_references") or {}
    ident = manifest.get("methodology_identity") or {}
    universe = (protocol.get("universe") or {}).get("frozen_symbol_list") or []
    holdout = protocol.get("holdout_status") or {}
    protocol_sha = content_sha256(protocol) if protocol else None
    manifest_sha = content_sha256(manifest) if manifest else None
    frozen_fp = ident.get("methodology_source_fingerprint")
    frozen_scoring = ident.get("scoring_config_hash")

    # ---- kimlik (paketlenmiş artefaktlar)
    gate("TECHNICAL_VERSION", spec.technical_version == "TECHNICAL_V2"
         and protocol.get("technical_version") == "TECHNICAL_V2" and refs.get("technical_version") == "TECHNICAL_V2")
    gate("PROTOCOL_VERSION", spec.expected_protocol_version is not None
         and protocol.get("protocol_version") == spec.expected_protocol_version)
    gate("PROTOCOL_SHA256", spec.expected_protocol_sha256 is not None and protocol_sha == spec.expected_protocol_sha256)
    gate("FREEZE_MANIFEST_BINDING", manifest_sha is not None and refs.get("freeze_manifest_sha256") == manifest_sha
         and manifest.get("technical_version_name") == "TECHNICAL_V2")
    gate("IDENTITY_LOADS", lambda: load_evaluation_identity(spec).protocol_sha256 == protocol_sha)
    gate("ENGINE_VERSION", ident.get("engine_version") == refs.get("engine_version") == running_engine)
    gate("SCORING_CONFIG_FROZEN", lambda: frozen_scoring == refs.get("scoring_config_hash") == compute_scoring_config_hash(
        manifest["technical_indicator_weights"], manifest["technical_family_weights"]))
    gate("FINGERPRINT_ALGORITHM_NORMALIZED", spec.normalized_fingerprint is True
         and "normalize_newlines=True" in str(ident.get("methodology_source_fingerprint_algorithm", "")))

    # ---- çalışan kaynak baytları parmak izi (HARD BLOCK)
    if observed_methodology_fingerprint is None:
        fingerprint_source = "RUNNING_SOURCE_BYTES"
        try:
            observed_fp = compute_methodology_source_fingerprint(normalize_newlines=True)
        except Exception:  # noqa: BLE001
            observed_fp = None
    else:
        fingerprint_source = "SUPPLIED"
        observed_fp = observed_methodology_fingerprint
    gate("METHODOLOGY_FINGERPRINT", frozen_fp is not None and frozen_fp == refs.get("methodology_source_fingerprint")
         and observed_fp == frozen_fp)

    # ---- dondurulmuş evren (canlı üyelik OKUNMAZ)
    gate("UNIVERSE_COUNT", len(universe) == 100)
    gate("UNIVERSE_UNIQUE", len(set(universe)) == len(universe))
    gate("UNIVERSE_MATCHES_PROTOCOL", lambda: list(
        load_verified_technical_v1_protocol(protocol_sha, spec.protocol_path).frozen_symbol_list) == list(universe))

    # ---- V1/V2 ayrımı
    gate("NO_VERSION_MIXING", lambda: (
        (protocol.get("supersedes") or {}).get("protocol_sha256") == load_evaluation_identity(TECHNICAL_V1_SPEC).protocol_sha256
        != protocol_sha and refs.get("freeze_manifest_sha256") != load_evaluation_identity(TECHNICAL_V1_SPEC).freeze_manifest_sha256))

    def _v1_superseded() -> bool:
        try:
            assert_identity_matches_running_engine(load_evaluation_identity(TECHNICAL_V1_SPEC))
        except TechnicalV1MethodologySupersededError:
            return running_engine == ENGINE_VERSION
        return False

    gate("V1_SUPERSEDED", _v1_superseded)

    # ---- holdout (protokol)
    holdout_active = holdout.get("prospective_holdout_started")
    holdout_start = holdout.get("effective_holdout_start")
    gate("HOLDOUT_INACTIVE", holdout_active is False)
    gate("HOLDOUT_START_NULL", holdout_start is None)

    # ---- canlı durum: aktivasyon kilidi / olayı / kanıt kayıtları
    pv = protocol.get("protocol_version") or ""
    live_state_checks = (("lock", "activation_lock_exists", "NO_ACTIVATION_LOCK"),
                         ("event", "activation_event_exists", "NO_ACTIVATION_EVENT"),
                         ("running", "evidence_collection_running", "NO_EVIDENCE_COLLECTION_RUNNING"))
    states: dict[str, str] = {}
    if activation_state is None:
        state_source = NOT_RUN
        for key, _, code in live_state_checks:
            states[key] = NOT_RUN
            (failed if production else not_run).append(code)
    else:
        state_source = getattr(activation_state, "source", "SYNTHETIC")
        if production and state_source != FIRESTORE_READ_ONLY:
            failed.append("ACTIVATION_STATE_NOT_PRODUCTION_SOURCE")
        for key, method, code in live_state_checks:
            try:
                states[key] = PRESENT if getattr(activation_state, method)(pv) else ABSENT
            except Exception:  # noqa: BLE001 -- okunamayan durum = UNKNOWN, fail closed
                states[key] = UNKNOWN
            if states[key] != ABSENT:
                failed.append(code)
        if not production and state_source != FIRESTORE_READ_ONLY:
            not_run.append("PRODUCTION_ACTIVATION_STATE_READ")

    # ---- canlı scoring config
    if live_scoring_config_hash_reader is None:
        live_status = NOT_RUN
        (failed if production else not_run).append("LIVE_SCORING_CONFIG")
    else:
        try:
            live_hash = live_scoring_config_hash_reader()
            live_status = "MATCH" if live_hash == frozen_scoring else "MISMATCH"
        except Exception:  # noqa: BLE001
            live_status = "UNREADABLE"
        if live_status != "MATCH":
            failed.append(f"LIVE_SCORING_CONFIG_{live_status}")

    # ---- deploy runtime kimliği
    runtime_service = runtime_revision = None
    if runtime_identity_reader is None:
        runtime_status = NOT_RUN
        (failed if production else not_run).append("DEPLOYED_RUNTIME_IDENTITY")
    else:
        try:
            rt = runtime_identity_reader()
            runtime_service, runtime_revision = rt["service"], rt["revision"]
            runtime_status = "OBSERVED"
        except Exception:  # noqa: BLE001
            runtime_status = "UNOBSERVABLE"
            failed.append("DEPLOYED_RUNTIME_IDENTITY_UNOBSERVABLE")

    # ---- production'da dışarıdan verilen kimlik değerleri kabul edilmez
    if production and fingerprint_source != "RUNNING_SOURCE_BYTES":
        failed.append("FINGERPRINT_NOT_MEASURED_FROM_RUNNING_BYTES")
    if production and running_engine_version is not None:
        failed.append("ENGINE_VERSION_NOT_FROM_RUNNING_BUILD")
    if not production:
        not_run.append("DEPLOYED_CONTAINER_FINGERPRINT")

    # ---- bilgi amaçlı uyarı (kapıyı AÇMAZ/KAPATMAZ)
    period_end = (protocol.get("universe") or {}).get("membership_period_end")
    if today is not None and period_end and today.isoformat() > period_end:
        warnings.append("UNIVERSE_MEMBERSHIP_PERIOD_ENDED_UNIVERSE_REMAINS_FROZEN_BY_PROTOCOL")

    if failed:
        status = NOT_READY
    elif production:
        status = READY
    else:
        status = LOCAL_CHECKS_PASSED

    return TechnicalV2ReadinessResult(
        status=status,
        verification_scope=mode,
        production_activation_eligible=status == READY and production,
        technical_version=protocol.get("technical_version"),
        protocol_version=protocol.get("protocol_version"),
        engine_version=ident.get("engine_version"),
        protocol_sha256=protocol_sha,
        freeze_manifest_sha256=manifest_sha,
        scoring_config_sha256=frozen_scoring,
        live_scoring_config_status=live_status,
        methodology_source_fingerprint=frozen_fp,
        observed_methodology_source_fingerprint=observed_fp,
        fingerprint_source=fingerprint_source,
        fingerprint_normalized=bool(spec.normalized_fingerprint),
        universe_count=len(universe),
        holdout_active=holdout_active,
        effective_holdout_start=holdout_start,
        activation_state_source=state_source,
        activation_lock_state=states["lock"],
        activation_event_state=states["event"],
        evidence_collection_state=states["running"],
        runtime_identity_status=runtime_status,
        runtime_service=runtime_service,
        runtime_revision=runtime_revision,
        failed_gates=tuple(failed),
        not_run_checks=tuple(not_run),
        warnings=tuple(warnings),
    )


EXIT_CODES = {READY: 0, NOT_READY: 1, LOCAL_CHECKS_PASSED: 3}


def run_cli(argv: list[str] | None = None) -> int:
    """Production giriş noktası. Okuyucuları/runtime bağımlılıklarını KENDİSİ
    kurar; dışarıdan okuyucu/rapor/override ALMAZ."""
    return _run_cli(argv)


def _run_cli(argv: list[str] | None = None, *, firestore_client_factory=None, runtime_identity_reader=None,
             out=None) -> int:
    """YALNIZCA testler için bağımlılık enjeksiyonu (modül-içi). `--mode local`
    (varsayılan): canlı okuma YOK. `--mode production`: gerçek Firestore'a
    YALNIZCA okuma + canlı config + runtime kimliği. Firestore istemcisi
    kurulamazsa fail-closed NOT_READY (istisna mesajı yazdırılmaz)."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.research.technical_v2_readiness")
    parser.add_argument("--mode", choices=("local", "production"), default="local")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    today = date.today()

    if args.mode == "local":
        result = validate_technical_v2_release_readiness(mode=MODE_LOCAL, today=today)
        extra = {}
    else:
        extra = {}
        try:
            if firestore_client_factory is None:
                from app.core.firebase import get_firestore_client as firestore_client_factory
            db = firestore_client_factory()
            reader = FirestoreReadOnlyActivationStateReader(db)
            config_reader = live_scoring_config_hash_from(db)
        except Exception as exc:  # noqa: BLE001 -- fail closed, mesaj/kimlik bilgisi yazdırılmaz
            reader, config_reader = None, None
            extra["firestore_client_error_type"] = type(exc).__name__
        result = validate_technical_v2_release_readiness(
            mode=MODE_PRODUCTION, activation_state=reader, live_scoring_config_hash_reader=config_reader,
            runtime_identity_reader=runtime_identity_reader or observe_runtime_identity, today=today)
    payload = {**asdict(result), **extra}
    out.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    raise SystemExit(run_cli())
