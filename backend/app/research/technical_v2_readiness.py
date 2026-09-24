"""TECHNICAL V2-R1 — aktivasyon öncesi release gate (YALNIZCA okuma).

Soru: "Bu TAM çalışan build, dondurulmuş protokol altında Technical V2
prospektif kanıt toplamaya başlamak için güvenli mi?"

Bu modül kanıt toplamayı BAŞLATMAZ, hiçbir şey YAZMAZ, performans metriği
(hit rate / getiri / isabet / benchmark / P&L / sınıf performansı) HESAPLAMAZ.

Kilitli politikalar:
  * DONDURULMUŞ EVREN: TECHNICAL_V2_PROTOCOL_V1 evreni, BIST100 üyeliği sonradan
    değişse (ör. 2026-09-30 sonrası) bile TAM o 100 sembol olarak kalır; kapı
    canlı üyeliği HİÇ okumaz/yenilemez. Evreni değiştirmek YENİ bir protokol
    revizyonu (yeni protocol_version + yeni protokol sha'sı) gerektirir; aynı
    protocol_version altında içerik değişirse sha çıpası kapıyı kapatır.
  * DEPLOY BAYTLARI PARMAK İZİ: gelecekteki her aktivasyon/kanıt başlangıcından
    HEMEN ÖNCE çalışan konteyner `compute_methodology_source_fingerprint(
    normalize_newlines=True)` hesaplamalı ve dondurulmuş V2 parmak iziyle
    BİREBİR eşleşmelidir. Uyuşmazlık = HARD BLOCK (NOT_READY). Override
    bayrağı veya yalnızca-uyarı modu YOKTUR.
  * FAIL CLOSED: her kimlik/durum hatası NOT_READY üretir; fallback yok.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.research.canonical_hash import content_sha256

READY = "READY"
NOT_READY = "NOT_READY"


class ActivationStateReader(Protocol):
    """Salt-okunur aktivasyon/kanıt durumu. Hiçbir metodu yazma yapmamalı."""

    def activation_lock_exists(self, protocol_version: str) -> bool: ...

    def activation_event_exists(self, protocol_version: str) -> bool: ...

    def evidence_collection_running(self, protocol_version: str) -> bool: ...


class FirestoreReadOnlyActivationStateReader:
    """Mevcut technical_v1_* koleksiyonlarında `protocol_version` eşitliğiyle
    YALNIZCA okuma sorgusu (limit 1). create/set/update/delete ÇAĞRILMAZ.
    V1/V2 kayıtları aynı koleksiyonları paylaşır; `protocol_version` alanı ayırır."""

    def __init__(self, db) -> None:
        self._db = db

    def _any(self, collection: str, protocol_version: str) -> bool:
        query = self._db.collection(collection).where("protocol_version", "==", protocol_version).limit(1)
        return len(list(query.get())) > 0

    def activation_lock_exists(self, protocol_version: str) -> bool:
        from app.repositories.technical_v1_activation_lock_repository import COLLECTION

        return self._any(COLLECTION, protocol_version)

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


@dataclass(frozen=True)
class TechnicalV2ReadinessResult:
    status: str
    technical_version: str | None
    protocol_version: str | None
    engine_version: str | None
    protocol_sha256: str | None
    freeze_manifest_sha256: str | None
    scoring_config_sha256: str | None
    methodology_source_fingerprint: str | None
    observed_methodology_source_fingerprint: str | None
    fingerprint_normalized: bool
    universe_count: int | None
    holdout_active: bool | None
    effective_holdout_start: str | None
    activation_lock_present: bool | None
    activation_event_present: bool | None
    evidence_collection_running: bool | None
    failed_gates: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def validate_technical_v2_release_readiness(
    *,
    activation_state: ActivationStateReader,
    today: date | None = None,
    observed_methodology_fingerprint: str | None = None,
    observed_scoring_config_hash: str | None = None,
    running_engine_version: str | None = None,
    spec=None,
) -> TechnicalV2ReadinessResult:
    """Tüm kapılar bağımsız değerlendirilir; herhangi biri başarısızsa NOT_READY.

    `observed_methodology_fingerprint` verilmezse ÇALIŞAN build'in kaynak
    baytlarından (normalize) hesaplanır. `observed_scoring_config_hash`
    verilirse (ör. salt-okunur canlı config okuması) dondurulmuş hash'le
    eşleşmek zorundadır."""
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

    spec = spec or TECHNICAL_V2_SPEC
    running_engine = running_engine_version or ENGINE_VERSION
    failed: list[str] = []
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

    # ---- kimlik
    gate("TECHNICAL_VERSION", spec.technical_version == "TECHNICAL_V2"
         and protocol.get("technical_version") == "TECHNICAL_V2" and refs.get("technical_version") == "TECHNICAL_V2")
    gate("PROTOCOL_VERSION", spec.expected_protocol_version is not None
         and protocol.get("protocol_version") == spec.expected_protocol_version)
    gate("PROTOCOL_SHA256", spec.expected_protocol_sha256 is not None and protocol_sha == spec.expected_protocol_sha256)
    gate("FREEZE_MANIFEST_BINDING", manifest_sha is not None and refs.get("freeze_manifest_sha256") == manifest_sha
         and manifest.get("technical_version_name") == "TECHNICAL_V2")
    gate("IDENTITY_LOADS", lambda: load_evaluation_identity(spec).protocol_sha256 == protocol_sha)
    gate("ENGINE_VERSION", ident.get("engine_version") == refs.get("engine_version") == running_engine)
    gate("SCORING_CONFIG", lambda: (
        ident.get("scoring_config_hash") == refs.get("scoring_config_hash")
        == compute_scoring_config_hash(manifest["technical_indicator_weights"], manifest["technical_family_weights"])
        and (observed_scoring_config_hash is None or observed_scoring_config_hash == ident.get("scoring_config_hash"))))
    gate("FINGERPRINT_ALGORITHM_NORMALIZED", spec.normalized_fingerprint is True
         and "normalize_newlines=True" in str(ident.get("methodology_source_fingerprint_algorithm", "")))

    observed_fp = observed_methodology_fingerprint
    if observed_fp is None:
        try:
            observed_fp = compute_methodology_source_fingerprint(normalize_newlines=True)
        except Exception:  # noqa: BLE001
            observed_fp = None
    # HARD BLOCK: çalışan baytlar dondurulmuş V2 parmak izine birebir eşit olmalı.
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

    # ---- aktivasyon/kanıt durumu (salt-okunur)
    pv = protocol.get("protocol_version") or ""
    states: dict[str, bool | None] = {}
    for key, method in (("lock", "activation_lock_exists"), ("event", "activation_event_exists"),
                        ("running", "evidence_collection_running")):
        try:
            states[key] = bool(getattr(activation_state, method)(pv))
        except Exception:  # noqa: BLE001 -- okunamayan durum = hazır değil
            states[key] = None
    gate("NO_ACTIVATION_LOCK", states["lock"] is False)
    gate("NO_ACTIVATION_EVENT", states["event"] is False)
    gate("NO_EVIDENCE_COLLECTION_RUNNING", states["running"] is False)

    # ---- bilgi amaçlı uyarı (kapıyı AÇMAZ/KAPATMAZ)
    period_end = (protocol.get("universe") or {}).get("membership_period_end")
    if today is not None and period_end and today.isoformat() > period_end:
        warnings.append("UNIVERSE_MEMBERSHIP_PERIOD_ENDED_UNIVERSE_REMAINS_FROZEN_BY_PROTOCOL")

    return TechnicalV2ReadinessResult(
        status=READY if not failed else NOT_READY,
        technical_version=protocol.get("technical_version"),
        protocol_version=protocol.get("protocol_version"),
        engine_version=ident.get("engine_version"),
        protocol_sha256=protocol_sha,
        freeze_manifest_sha256=manifest_sha,
        scoring_config_sha256=ident.get("scoring_config_hash"),
        methodology_source_fingerprint=frozen_fp,
        observed_methodology_source_fingerprint=observed_fp,
        fingerprint_normalized=bool(spec.normalized_fingerprint),
        universe_count=len(universe),
        holdout_active=holdout_active,
        effective_holdout_start=holdout_start,
        activation_lock_present=states["lock"],
        activation_event_present=states["event"],
        evidence_collection_running=states["running"],
        failed_gates=tuple(failed),
        warnings=tuple(warnings),
    )
