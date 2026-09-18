"""HATA 13E — Technical V1 oturum (session) kontrolcüsü.

Bu modül, HATA 12/13A-D'de KAPANMIŞ, tek-sembol seviyesindeki bileşenleri
(pre-claim yetkilendirme + tek-deneme yürütme + attempt2 + finalizasyon)
dondurulmuş 100-sembollük evren üzerinde TEK bir tam Technical V1
oturumuna bağlayan orkestrasyon katmanıdır.

Bu modül KESİNLİKLE:
  - Bilimsel formül/karar mantığı İÇERMEZ -- her sembol için TEK, GERÇEK
    çağrı `TechnicalV1AttemptExecutionService.execute_attempt()`/
    `TechnicalV1Attempt2Orchestrator.run_attempt2_if_required()`/
    `TechnicalV1Finalizer.finalize()`'e delege edilir.
  - `select_final_evaluation()`/exclusion policy/identity gates'i
    YENİDEN UYGULAMAZ.
  - Canlı BIST100/`AssetRepository`/provider-keşfi OKUMAZ -- dondurulmuş
    evren SADECE `TrustedTechnicalV1Protocol.frozen_symbol_list`'ten gelir
    (section 3/10/34).
  - Saat bekleyen bir zamanlayıcı DEĞİLDİR -- her faz metodu, çağıranın
    (gelecekte HATA 13E'nin KAPSAMI DIŞINDAKİ bir Cloud Scheduler'ın)
    verdiği `now` ile HEMEN çalışır (section 7/51).

PER-SEMBOL YALITIM SINIRI (section 11/12, KASITLI, DAR tanım): attempt1/
attempt2 fazlarında `ProvenanceConflictError`'ı DAHİL her istisna
PER-SEMBOL yakalanır ve operasyonel bir hata olarak kaydedilir, diğer 99
sembolün işlenmesi HİÇ ENGELLENMEZ -- "sistem-geneli bozulma fazı
durdurmayı gerektirebilir" (section 11) İSTEĞE BAĞLI bir istisna olarak
DEĞERLENDİRİLDİ ama KASITLI OLARAK UYGULANMADI: `execute_attempt()`'in
KENDİSİ bir kara kutu olduğundan, dışarıdan "bu ProvenanceConflictError
aktivasyon kilidi/olayı gibi OTURUM-GENELİ bir kaynaktan mı, yoksa BU
sembolün KENDİ evidence-store içerik-adresi çakışmasından mı geldi"
sorusunu GÜVENİLİR biçimde ayırt etmenin (mesaj metni ayrıştırma DIŞINDA)
bir yolu yoktur -- mesaj-metni ayrıştırmaya dayanan kırılgan bir sezgisel
kural YAZMAK, section 11'in KENDİ "define this boundary narrowly"
talimatından DAHA RİSKLİ olurdu (yanlış sınıflandırılmış tek bir sembol
hatası, KALAN 99 sembolün TAMAMINI haksız yere durdurabilirdi). Bu yüzden
"dar sınır" burada BİLİNÇLİ OLARAK boş küme olarak seçildi -- section 11'in
BİRİNCİL, AÇIK kuralı ("One symbol failing must NOT abort dispatch of
the other 99 symbols") KOŞULSUZ uygulanır. Finalizasyon fazında
`ProvenanceConflictError` bu tartışmanın DIŞINDADIR -- o, `session_run.py`'nin
KENDİ, ZATEN var olan `provenance_blocked_evaluation_ids` kavramına
KARŞILIK GELEN, BEKLENEN bir per-evaluation durumdur (section 24).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.repositories.technical_v1_evaluation_repository import TechnicalV1EvaluationRepository
from app.repositories.technical_v1_session_manifest_repository import (
    SessionManifestOutcome,
    TechnicalV1SessionManifestRepository,
)
from app.repositories.technical_v1_session_run_repository import TechnicalV1SessionRunRepository
from app.research.evidence_identity import compute_evaluation_id, compute_session_id
from app.research.evidence_models import ProvenanceConflictError
from app.research.final_evaluation_models import FinalizationContext, FinalizationRetryableError
from app.research.session_manifest import (
    ExpectedEvaluationState,
    SessionAccountingResult,
    SessionAccountingStatus,
    TechnicalV1SessionManifest,
    build_session_manifest,
    derive_expected_evaluation_ids,
    derive_session_accounting,
)
from app.research.session_run import TechnicalV1SessionRunSnapshot
from app.research.technical_v1_attempt2_orchestration import TechnicalV1Attempt2Orchestrator
from app.research.technical_v1_attempt_execution import TechnicalV1AttemptExecutionService
from app.research.technical_v1_attempt_schedule import attempt2_decision_time_utc, formal_cutoff_utc
from app.research.technical_v1_finalization import TechnicalV1Finalizer
from app.research.technical_v1_protocol import TrustedTechnicalV1Protocol


@dataclass(frozen=True)
class SessionScientificFacts:
    """Bir oturumun TÜM sembollerinde PAYLAŞILAN (sembole bağlı OLMAYAN)
    `FinalizationContext` alanları -- `protocol_sha256` KASITLI OLARAK
    BURADA YOKTUR, çağıran `TrustedTechnicalV1Protocol.protocol_sha256`'yı
    (kontrolcüye ZATEN enjekte edilmiş) kullanır, İKİNCİ bir kopya
    TAŞINMAZ. `attempt2_decision_time_utc`/`formal_cutoff_utc` de BURADA
    YOKTUR -- her ikisi de HER ÇAĞRIDA `technical_v1_attempt_schedule`'dan
    (HATA 13D, DEĞİŞTİRİLMEMİŞ) doğrudan türetilir."""

    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str
    E1_date: str


@dataclass(frozen=True)
class SymbolPhaseOutcome:
    """TEK bir sembol için TEK bir faz çağrısının operasyonel sonucu --
    BİLİMSEL KANIT DEĞİLDİR (section 32), yalnızca çağıranın (ör. bir
    dashboard/log) okuyacağı bir özet kaydıdır."""

    symbol: str
    outcome: str
    detail: str | None = None


@dataclass(frozen=True)
class PhaseReport:
    """Section 32: sayaçlar `outcome` değerine göre türetilir -- ayrı,
    elle-senkronize edilen bir sayaç seti TUTULMAZ."""

    outcomes: tuple[SymbolPhaseOutcome, ...]

    @property
    def processed(self) -> int:
        return len(self.outcomes)

    def count(self, outcome: str) -> int:
        return sum(1 for item in self.outcomes if item.outcome == outcome)


@dataclass(frozen=True)
class ManifestPhaseResult:
    """`manifest`/`create_outcome`, `accounting.status == COMPLETE`
    DEĞİLSE HER ZAMAN `None`'dır -- section 28'in "controller loop
    finished ile scientific session complete AYNI şey DEĞİLDİR" kuralını
    yapısal olarak zorunlu kılar (COMPLETE olmayan bir accounting için
    `build_session_manifest()`'in KENDİSİ hiç ÇAĞRILMAZ)."""

    accounting: SessionAccountingResult
    manifest: TechnicalV1SessionManifest | None
    create_outcome: SessionManifestOutcome | None


class TechnicalV1SessionController:
    """HATA 13E section 5/6. TÜM bağımlılıklar (dahil olduğu üç per-attempt
    servis + üç repository + güvenilen protokol) constructor'da AÇIKÇA
    enjekte edilir -- hiçbir global Firestore/GCS client'ı burada
    OLUŞTURULMAZ (her bağımlılık KENDİ, ZATEN kilitlenmiş lazy-init
    desenini korur)."""

    def __init__(
        self,
        *,
        trusted_protocol: TrustedTechnicalV1Protocol,
        attempt_execution_service: TechnicalV1AttemptExecutionService,
        attempt2_orchestrator: TechnicalV1Attempt2Orchestrator,
        finalizer: TechnicalV1Finalizer,
        session_run_repo: TechnicalV1SessionRunRepository,
        session_manifest_repo: TechnicalV1SessionManifestRepository,
        evaluation_repo: TechnicalV1EvaluationRepository,
    ) -> None:
        self._trusted_protocol = trusted_protocol
        self._attempt_execution_service = attempt_execution_service
        self._attempt2_orchestrator = attempt2_orchestrator
        self._finalizer = finalizer
        self._session_run_repo = session_run_repo
        self._session_manifest_repo = session_manifest_repo
        self._evaluation_repo = evaluation_repo

    # -----------------------------------------------------------------
    # Ortak yardımcı -- HİÇBİR faz metodunun DIŞINA sızmaz.
    # -----------------------------------------------------------------

    def _build_context(
        self, *, protocol_version: str, T_session_date: str, symbol: str, facts: SessionScientificFacts
    ) -> FinalizationContext:
        return FinalizationContext(
            evaluation_id=compute_evaluation_id(protocol_version, T_session_date, symbol),
            protocol_version=protocol_version,
            protocol_sha256=self._trusted_protocol.protocol_sha256,
            methodology_git_commit=facts.methodology_git_commit,
            freeze_manifest_sha256=facts.freeze_manifest_sha256,
            engine_version=facts.engine_version,
            scoring_config_hash=facts.scoring_config_hash,
            T_session_date=T_session_date,
            symbol=symbol,
            E1_date=facts.E1_date,
            attempt2_decision_time_utc=attempt2_decision_time_utc(T_session_date),
            formal_cutoff_utc=formal_cutoff_utc(T_session_date),
        )

    # -----------------------------------------------------------------
    # Section 8 -- attempt1 fazı
    # -----------------------------------------------------------------

    def run_attempt1_phase(
        self, *, activation_lock_id: str, protocol_version: str, T_session_date: str, now: datetime
    ) -> PhaseReport:
        outcomes: list[SymbolPhaseOutcome] = []
        for symbol in self._trusted_protocol.frozen_symbol_list:
            try:
                report = self._attempt_execution_service.execute_attempt(
                    activation_lock_id=activation_lock_id,
                    protocol_version=protocol_version,
                    T_session_date=T_session_date,
                    symbol=symbol,
                    attempt_number=1,
                    now=now,
                )
                outcomes.append(SymbolPhaseOutcome(symbol=symbol, outcome=report.outcome.value))
            except Exception as exc:  # noqa: BLE001 -- section 11/12: per-symbol yalıtım KASITLI olarak geniş
                outcomes.append(
                    SymbolPhaseOutcome(symbol=symbol, outcome="OPERATIONAL_ERROR", detail=type(exc).__name__)
                )
        return PhaseReport(outcomes=tuple(outcomes))

    # -----------------------------------------------------------------
    # Section 16/17/18 -- attempt2 fazı
    # -----------------------------------------------------------------

    def run_attempt2_phase(
        self,
        *,
        activation_lock_id: str,
        protocol_version: str,
        T_session_date: str,
        facts: SessionScientificFacts,
        now: datetime,
    ) -> PhaseReport:
        outcomes: list[SymbolPhaseOutcome] = []
        for symbol in self._trusted_protocol.frozen_symbol_list:
            context = self._build_context(
                protocol_version=protocol_version, T_session_date=T_session_date, symbol=symbol, facts=facts
            )
            try:
                report = self._attempt2_orchestrator.run_attempt2_if_required(
                    context, activation_lock_id=activation_lock_id, now=now
                )
                outcomes.append(SymbolPhaseOutcome(symbol=symbol, outcome=report.outcome.value))
            except Exception as exc:  # noqa: BLE001 -- section 18: AYNI dar per-symbol yalıtım
                outcomes.append(
                    SymbolPhaseOutcome(symbol=symbol, outcome="OPERATIONAL_ERROR", detail=type(exc).__name__)
                )
        return PhaseReport(outcomes=tuple(outcomes))

    # -----------------------------------------------------------------
    # Section 19/20 -- finalizasyon fazı
    # -----------------------------------------------------------------

    def run_finalization_phase(
        self, *, protocol_version: str, T_session_date: str, facts: SessionScientificFacts, now: datetime
    ) -> PhaseReport:
        """HATA 13E section 13/14: bu faz, biten geçişte GÖZLEMLENEN
        `RETRYABLE`/`PROVENANCE_CONFLICT` evaluation_id kümesini
        `TechnicalV1SessionRunSnapshot`'a TAM DEĞİŞTİRME (full-replace)
        olarak yazar -- bu, `session_run.py`'nin KENDİ, dokümante ettiği
        "her geçişte SIFIRDAN yeniden inşa edilir" sözleşmesidir."""
        outcomes: list[SymbolPhaseOutcome] = []
        retry_pending: list[str] = []
        provenance_blocked: list[str] = []

        for symbol in self._trusted_protocol.frozen_symbol_list:
            context = self._build_context(
                protocol_version=protocol_version, T_session_date=T_session_date, symbol=symbol, facts=facts
            )
            try:
                report = self._finalizer.finalize(context, now=now)
                outcomes.append(SymbolPhaseOutcome(symbol=symbol, outcome=report.outcome.value))
            except FinalizationRetryableError as exc:
                outcomes.append(
                    SymbolPhaseOutcome(symbol=symbol, outcome="RETRYABLE", detail=type(exc).__name__)
                )
                retry_pending.append(context.evaluation_id)
            except ProvenanceConflictError as exc:
                # section 24: finalizasyonda BEKLENEN, per-evaluation bir
                # durum -- session_run.py'nin KENDİ provenance_blocked
                # kavramına eşlenir, fazı DURDURMAZ.
                outcomes.append(
                    SymbolPhaseOutcome(symbol=symbol, outcome="PROVENANCE_CONFLICT", detail=type(exc).__name__)
                )
                provenance_blocked.append(context.evaluation_id)

        session_id = compute_session_id(protocol_version, T_session_date)
        snapshot = TechnicalV1SessionRunSnapshot(
            session_id=session_id,
            protocol_version=protocol_version,
            T_session_date=T_session_date,
            retry_pending_evaluation_ids=tuple(sorted(retry_pending)),
            provenance_blocked_evaluation_ids=tuple(sorted(provenance_blocked)),
        )
        self._session_run_repo.upsert(snapshot)

        return PhaseReport(outcomes=tuple(outcomes))

    # -----------------------------------------------------------------
    # Section 21-27 -- manifest tamlık kontrolü + inşa
    # -----------------------------------------------------------------

    def build_session_manifest_if_complete(
        self, *, protocol_version: str, T_session_date: str, facts: SessionScientificFacts
    ) -> ManifestPhaseResult:
        """HATA 13E section 21-28: denominator HER ZAMAN dondurulmuş
        100'den türetilir (Firestore'dan keşfedilmez, section 22).
        `build_session_manifest()`, `accounting.status == COMPLETE`
        DEĞİLSE HİÇ ÇAĞRILMAZ (o fonksiyon ZATEN 100'den az/çok kayıt
        verilirse `ValueError` fırlatır -- bu KASITLI OLARAK ÖNCEDEN,
        AÇIK bir muhasebe adımıyla ÖNLENİR, section 41/43)."""
        frozen_symbols = self._trusted_protocol.frozen_symbol_list
        expected_ids = derive_expected_evaluation_ids(protocol_version, T_session_date, frozen_symbols)

        states: dict[str, ExpectedEvaluationState] = {}
        verified_by_id = {}
        for evaluation_id in expected_ids:
            try:
                persisted = self._evaluation_repo.get_verified(evaluation_id)
            except ProvenanceConflictError:
                states[evaluation_id] = ExpectedEvaluationState.CONFLICT
                continue
            if persisted is None:
                states[evaluation_id] = ExpectedEvaluationState.ABSENT
            else:
                states[evaluation_id] = ExpectedEvaluationState.VERIFIED
                verified_by_id[evaluation_id] = persisted.evaluation

        session_id = compute_session_id(protocol_version, T_session_date)
        accounting = derive_session_accounting(session_id, expected_ids, states)

        if accounting.status != SessionAccountingStatus.COMPLETE:
            return ManifestPhaseResult(accounting=accounting, manifest=None, create_outcome=None)

        final_evaluations = [verified_by_id[evaluation_id] for evaluation_id in expected_ids]
        manifest = build_session_manifest(
            protocol_version=protocol_version,
            T_session_date=T_session_date,
            protocol_sha256=self._trusted_protocol.protocol_sha256,
            freeze_manifest_sha256=facts.freeze_manifest_sha256,
            frozen_symbols=frozen_symbols,
            final_evaluations=final_evaluations,
        )
        create_outcome = self._session_manifest_repo.create(manifest)
        return ManifestPhaseResult(accounting=accounting, manifest=manifest, create_outcome=create_outcome)
