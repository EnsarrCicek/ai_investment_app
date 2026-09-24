"""TECHNICAL V2 — sürümlü Technical değerlendirme kimliği (HATA 12/13 çerçevesinin
en küçük güvenli genellemesi).

Her Technical metodoloji sürümü, KENDİ dondurulmuş protokolüne ve freeze
manifest'ine bağlıdır. Bu modül:
  - `protocol_version` önekinden sürümü çözer (V1: TECHNICAL_V1_PROTOCOL_*,
    V2: TECHNICAL_V2_PROTOCOL_*),
  - paketlenmiş artefaktlardan TEK bir güvenilen `TechnicalEvaluationIdentity`
    türetir (protokol ↔ manifest çapraz bağı doğrulanır),
  - aktivasyon kilidini ve çağıranın bilimsel olgularını bu kimliğe karşı
    doğrular (V1/V2 karışımı fail-fast),
  - çalışan motorun sürümle eşleşmesini zorunlu kılar (engine 1.15.0 altında
    YENİ V1 attempt/aktivasyonu reddedilir; V1 kayıtlarının OKUNMASI serbest).

Firestore koleksiyonları ve doküman şemaları DEĞİŞMEZ: V1/V2 kayıtları, ID'leri
türeten `protocol_version` ve kayıtların taşıdığı protocol/manifest/engine/
scoring kimliğiyle ayrışır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.research.canonical_hash import content_sha256
from app.research.evidence_models import ProvenanceConflictError
from app.research.technical_v1_scoring_config_values import TechnicalV1MethodologySupersededError

_RESOURCES = Path(__file__).resolve().parent / "resources"


class TechnicalVersionMismatchError(ProvenanceConflictError):
    """İstenen/kilitli kimlik, güvenilen sürüm kimliğiyle eşleşmiyor (V1/V2
    karışımı veya kurcalanmış kimlik)."""


class TechnicalMethodologySupersededError(ProvenanceConflictError):
    """Sürümün dondurduğu engine_version çalışan motorla eşleşmiyor."""


@dataclass(frozen=True)
class TechnicalVersionSpec:
    technical_version: str
    protocol_path: Path
    freeze_manifest_path: Path
    protocol_version_prefix: str
    normalized_fingerprint: bool


TECHNICAL_V1_SPEC = TechnicalVersionSpec(
    technical_version="TECHNICAL_V1",
    protocol_path=_RESOURCES / "technical_v1_protocol_v1.json",
    freeze_manifest_path=_RESOURCES / "technical_v1_freeze_manifest.json",
    protocol_version_prefix="TECHNICAL_V1_PROTOCOL_",
    normalized_fingerprint=False,
)
TECHNICAL_V2_SPEC = TechnicalVersionSpec(
    technical_version="TECHNICAL_V2",
    protocol_path=_RESOURCES / "technical_v2_protocol_v1.json",
    freeze_manifest_path=_RESOURCES / "technical_v2_freeze_manifest.json",
    protocol_version_prefix="TECHNICAL_V2_PROTOCOL_",
    normalized_fingerprint=True,
)
TECHNICAL_VERSION_SPECS: dict[str, TechnicalVersionSpec] = {
    TECHNICAL_V1_SPEC.technical_version: TECHNICAL_V1_SPEC,
    TECHNICAL_V2_SPEC.technical_version: TECHNICAL_V2_SPEC,
}


def spec_for_protocol_version(protocol_version: str) -> TechnicalVersionSpec:
    matches = [s for s in TECHNICAL_VERSION_SPECS.values()
               if isinstance(protocol_version, str) and protocol_version.startswith(s.protocol_version_prefix)]
    if len(matches) != 1:
        raise TechnicalVersionMismatchError(f"protocol_version bilinen bir Technical sürümüne ait değil: {protocol_version!r}")
    return matches[0]


@dataclass(frozen=True)
class TechnicalEvaluationIdentity:
    technical_version: str
    protocol_version: str
    protocol_sha256: str
    freeze_manifest_sha256: str
    methodology_git_commit: str
    engine_version: str
    scoring_config_hash: str
    methodology_source_fingerprint: str | None
    normalized_fingerprint: bool
    spec: TechnicalVersionSpec


def _read(path: Path) -> dict:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ProvenanceConflictError(f"{path.name} bir JSON nesnesi değil")
    return parsed


def load_evaluation_identity(spec: TechnicalVersionSpec) -> TechnicalEvaluationIdentity:
    """Paketlenmiş protokol + manifest'ten güvenilen kimlik. Protokolün
    başvurduğu manifest hash'i gerçek manifest içeriğiyle eşleşmeli."""
    protocol = _read(spec.protocol_path)
    manifest = _read(spec.freeze_manifest_path)
    protocol_version = protocol.get("protocol_version")
    if not isinstance(protocol_version, str) or not protocol_version.startswith(spec.protocol_version_prefix):
        raise TechnicalVersionMismatchError(f"{spec.protocol_path.name}: protocol_version {protocol_version!r} {spec.technical_version} değil")
    if manifest.get("technical_version_name") != spec.technical_version:
        raise TechnicalVersionMismatchError(f"{spec.freeze_manifest_path.name}: technical_version_name {spec.technical_version} değil")
    manifest_sha = content_sha256(manifest)
    refs = protocol.get("methodology_references") or {}
    if refs.get("freeze_manifest_sha256") != manifest_sha:
        raise TechnicalVersionMismatchError(
            f"{spec.protocol_path.name} başka bir freeze manifest'e bağlı ({refs.get('freeze_manifest_sha256')!r} != {manifest_sha!r})")
    ident = manifest["methodology_identity"]
    for field in ("engine_version", "scoring_config_hash", "methodology_git_commit"):
        if field in refs and refs[field] != ident[field]:
            raise TechnicalVersionMismatchError(f"protokol/manifest {field} uyuşmazlığı")
    fingerprint = ident.get("methodology_source_fingerprint")
    if spec.normalized_fingerprint and not fingerprint:
        raise TechnicalVersionMismatchError(f"{spec.technical_version} manifest'i metodoloji parmak izi taşımalı")
    if fingerprint and refs.get("methodology_source_fingerprint", fingerprint) != fingerprint:
        raise TechnicalVersionMismatchError("protokol/manifest methodology_source_fingerprint uyuşmazlığı")
    return TechnicalEvaluationIdentity(
        technical_version=spec.technical_version,
        protocol_version=protocol_version,
        protocol_sha256=content_sha256(protocol),
        freeze_manifest_sha256=manifest_sha,
        methodology_git_commit=ident["methodology_git_commit"],
        engine_version=ident["engine_version"],
        scoring_config_hash=ident["scoring_config_hash"],
        methodology_source_fingerprint=fingerprint,
        normalized_fingerprint=spec.normalized_fingerprint,
        spec=spec,
    )


def identity_for_protocol_version(protocol_version: str) -> TechnicalEvaluationIdentity:
    return load_evaluation_identity(spec_for_protocol_version(protocol_version))


def assert_identity_matches_running_engine(identity: TechnicalEvaluationIdentity) -> None:
    from app.engines.technical.engine import ENGINE_VERSION

    if identity.engine_version != ENGINE_VERSION:
        cls = TechnicalV1MethodologySupersededError if identity.technical_version == "TECHNICAL_V1" else TechnicalMethodologySupersededError
        raise cls(
            f"{identity.technical_version} engine_version={identity.engine_version!r} ama çalışan engine={ENGINE_VERSION!r}: "
            "bu sürüm için YENİ attempt/aktivasyon reddedildi (geçmiş kayıtlar okunabilir kalır)."
        )


def validate_lock_identity(lock, identity: TechnicalEvaluationIdentity) -> None:
    """Aktivasyon kilidi TAM olarak bu sürümün güvenilen kimliğini mi taşıyor?

    `methodology_git_commit` KASITLI OLARAK eşitlenmez: HATA 12L/12M düzeninde
    kilit, deploy için onaylanan commit'i taşır (davranış değiştirmeyen altyapı
    commit'leri serbesttir); kaynak kimliğini metodoloji parmak izi korur. V2
    manifest'i parmak izi taşıdığından V2 kilidinin yetkili parmak izi ona
    BİREBİR eşit olmalıdır."""
    checks = [
        ("protocol_version", lock.protocol_version, identity.protocol_version),
        ("protocol_sha256", lock.protocol_sha256, identity.protocol_sha256),
        ("freeze_manifest_sha256", lock.freeze_manifest_sha256, identity.freeze_manifest_sha256),
    ]
    if identity.methodology_source_fingerprint is not None:
        checks.append(("authorized_methodology_source_fingerprint", lock.authorized_methodology_source_fingerprint,
                       identity.methodology_source_fingerprint))
    for name, observed, expected in checks:
        if observed != expected:
            raise TechnicalVersionMismatchError(
                f"activation lock {name} {identity.technical_version} kimliğiyle eşleşmiyor: {observed!r} != {expected!r}")


def validate_scientific_facts(facts, identity: TechnicalEvaluationIdentity) -> None:
    """Çağıranın (internal endpoint isteği) bildirdiği oturum olguları,
    sürümün güvenilen kimliğiyle birebir aynı olmalı."""
    for name, expected in (
        ("freeze_manifest_sha256", identity.freeze_manifest_sha256),
        ("engine_version", identity.engine_version),
        ("scoring_config_hash", identity.scoring_config_hash),
    ):
        observed = getattr(facts, name)
        if observed != expected:
            raise TechnicalVersionMismatchError(
                f"oturum olgusu {name} {identity.technical_version} kimliğiyle eşleşmiyor: {observed!r} != {expected!r}")
