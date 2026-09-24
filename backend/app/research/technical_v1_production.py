"""PROD-2 — Technical V1 production bağımlılık factory'si.

Bu modül SAF DEĞİLDİR (I/O yapar) -- HATA 12/13'te KİLİTLENEN, DEĞİŞTİRİLMEMİŞ
production bileşenlerini (repository'ler, `GCSEvidenceObjectStore`, gerçek
`BistProvider`, config repository) TEK bir yerde COMPOSE eder. Hiçbir
bilimsel/orkestrasyon mantığı BURAYA TAŞINMAZ -- bu modül SADECE constructor
çağrılarını birleştirir (section 4).

KASITLI GEÇ (LAZY) İNŞA: `build_session_controller()` yalnızca GERÇEKTEN
çağrıldığında çalışır -- modül IMPORT edilirken hiçbir Firestore/GCS
client'ı OLUŞTURULMAZ (her bağımlılığın KENDİ, ZATEN kilitlenmiş lazy-init
deseniyle AYNI). Bu, `TECHNICAL_V1_EVIDENCE_BUCKET` ayarlı OLMASA BİLE
`import app.main`'in HER ZAMAN güvenli kalmasını sağlar (section 25) --
yalnızca bu factory GERÇEKTEN çağrıldığında (bir internal endpoint
tetiklendiğinde) eksik config açık bir hataya dönüşür, hiçbir claim/
evidence yazımı denenmeden.

HİÇBİR GİZLİ BİLİMSEL VARSAYILAN YOK (section 5): `protocol_sha256`
çağırandan (HTTP isteği) AÇIKÇA gelir -- burada hiçbir sabit/varsayılan
hash/activation_lock_id/session_date/sembol İCAT EDİLMEZ."""

from __future__ import annotations

from app.core.config import TECHNICAL_V1_EVIDENCE_BUCKET
from app.research.technical_versions import (
    TECHNICAL_VERSION_SPECS,
    TechnicalVersionMismatchError,
    assert_identity_matches_running_engine,
    load_evaluation_identity,
)
from app.core.firebase import get_firestore_client
from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
from app.repositories.technical_v1_attempt_repository import TechnicalV1AttemptRepository
from app.repositories.technical_v1_evaluation_repository import TechnicalV1EvaluationRepository
from app.repositories.technical_v1_session_manifest_repository import TechnicalV1SessionManifestRepository
from app.repositories.technical_v1_session_run_repository import TechnicalV1SessionRunRepository
from app.research.evidence_object_store import GCSEvidenceObjectStore
from app.research.technical_v1_attempt2_orchestration import TechnicalV1Attempt2Orchestrator
from app.research.technical_v1_attempt_execution import TechnicalV1AttemptExecutionService
from app.research.technical_v1_finalization import TechnicalV1Finalizer
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
from app.research.technical_v1_session_controller import TechnicalV1SessionController
from app.services.market_data.bist_provider import BistProvider


class TechnicalV1ConfigurationError(RuntimeError):
    """Gerçek bir Technical V1 production servisi inşa edilmeye çalışıldı
    ama gerekli konfigürasyon (ör. `TECHNICAL_V1_EVIDENCE_BUCKET`) eksik.
    Ordinary app startup'ı (`import app.main`) ASLA bundan dolayı
    BAŞARISIZ OLMAZ -- bu hata YALNIZCA bu factory GERÇEKTEN çağrıldığında
    (section 25), herhangi bir claim/evidence yazımından ÖNCE fırlatılır."""


def _require_evidence_bucket() -> str:
    if not TECHNICAL_V1_EVIDENCE_BUCKET:
        raise TechnicalV1ConfigurationError(
            "TECHNICAL_V1_EVIDENCE_BUCKET ayarlı değil -- Technical V1 production servisi "
            "inşa edilemedi (hiçbir claim/evidence yazımı denenmedi)."
        )
    return TECHNICAL_V1_EVIDENCE_BUCKET


def build_session_controller(
    *, protocol_sha256: str, technical_version: str = "TECHNICAL_V1"
) -> TechnicalV1SessionController:
    """HATA 12/13'te kilitlenen TÜM production bileşenlerini COMPOSE eder.

    `protocol_sha256` çağıran tarafın (internal endpoint) isteğinden AÇIKÇA
    gelir -- `TrustedTechnicalV1Protocol.frozen_symbol_list`'in (kontrolcünün
    her fazda kullandığı dondurulmuş 100-sembol kaynağı) hangi doğrulanmış
    protokolden yükleneceğini belirler. Attempt1/attempt2'nin KENDİ,
    değiştirilmemiş iç mantığı (13C/13B), her attempt için AYRICA, verilen
    `activation_lock_id`'den kendi `protocol_sha256`'sını BAĞIMSIZ OLARAK
    yeniden türetip doğrular -- burada seçilen değer, o iç doğrulamayı
    ATLAMAZ/YERİNE GEÇMEZ, sadece kontrolcü seviyesindeki (frozen evren/
    manifest) kullanım için ayrıca yüklenir.
    """
    # TECHNICAL V2: kontrolcü TEK bir sürüm kimliğine bağlanır. İstenen
    # protocol_sha256 o sürümün paketlenmiş protokolüyle TAM eşleşmeli ve
    # çalışan motor sürümün engine_version'ıyla eşleşmeli (engine 1.15.0
    # altında V1 kontrolcüsü kurulamaz). Hiçbir Firestore/GCS client'ı bu
    # kontroller geçmeden OLUŞTURULMAZ.
    spec = TECHNICAL_VERSION_SPECS.get(technical_version)
    if spec is None:
        raise TechnicalVersionMismatchError(f"bilinmeyen technical_version: {technical_version!r}")
    evaluation_identity = load_evaluation_identity(spec)
    if protocol_sha256 != evaluation_identity.protocol_sha256:
        raise TechnicalVersionMismatchError(
            f"protocol_sha256 {technical_version} protokolüyle eşleşmiyor ({protocol_sha256!r})"
        )
    assert_identity_matches_running_engine(evaluation_identity)

    evidence_bucket = _require_evidence_bucket()

    db = get_firestore_client()
    trusted_protocol = load_verified_technical_v1_protocol(protocol_sha256, spec.protocol_path)

    provider = BistProvider()
    config_repo = SystemConfigRepository()
    benchmark_cache_repo = BenchmarkCacheRepository()
    evidence_store = GCSEvidenceObjectStore(bucket_name=evidence_bucket)

    attempt_execution_service = TechnicalV1AttemptExecutionService(
        activation_lock_repo=TechnicalV1ActivationLockRepository(db=db),
        activation_event_repo=TechnicalV1ActivationEventRepository(db=db),
        attempt_repo=TechnicalV1AttemptRepository(db=db),
        evidence_store=evidence_store,
        provider=provider,
        config_repo=config_repo,
        benchmark_cache_repo=benchmark_cache_repo,
    )
    attempt2_orchestrator = TechnicalV1Attempt2Orchestrator(
        db=db, attempt_execution_service=attempt_execution_service
    )
    evaluation_repo = TechnicalV1EvaluationRepository(db=db)
    finalizer = TechnicalV1Finalizer(db=db, evidence_store=evidence_store, evaluation_repo=evaluation_repo)

    return TechnicalV1SessionController(
        trusted_protocol=trusted_protocol,
        attempt_execution_service=attempt_execution_service,
        attempt2_orchestrator=attempt2_orchestrator,
        finalizer=finalizer,
        session_run_repo=TechnicalV1SessionRunRepository(db=db),
        session_manifest_repo=TechnicalV1SessionManifestRepository(db=db),
        evaluation_repo=evaluation_repo,
        evaluation_identity=evaluation_identity,
    )
