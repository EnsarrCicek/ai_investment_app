"""HATA 13C — Technical V1 tek-deneme (single-attempt) yürütme servisi.

Bu modül, HATA 12/13A/13B'de KAPANMIŞ provenance/taksonomi bileşenlerini
GERÇEK bir çalışan boru hattına bağlayan İLK üretim servisidir:

    pre-claim yetkilendirme -> claim -> post-claim kimlik kapıları ->
    veri edinimi/normalizasyon -> immutable evidence -> TechnicalAnalysisEngine
    -> post-analysis exclusion -> sınıflandırma -> AttemptResult yayınlama.

HİÇBİR kapalı bileşen (activation event/lock, protokol/freeze-manifest
yükleyicileri, AttemptClaim/AttemptResult şeması, attempt repository,
evidence serializer'lar/object store, identity gates, exclusion policy,
final selector, session manifest) YENİDEN TASARLANMAZ -- bu modül
YALNIZCA onları enjekte edilmiş bağımlılıklar olarak ÇAĞIRIR.

KASITLI OLARAK YAPILMAYANLAR (13D/13E'nin kapsamı):
  - attempt2'nin GEREKİP GEREKMEDİĞİNE karar vermek (bu servis KENDİSİNE
    verilen `attempt_number`'ı yürütür, kendi başına 2. denemeyi
    PLANLAMAZ).
  - `FinalEvaluation` üretmek/persist etmek (`select_final_evaluation()`
    burada HİÇ çağrılmaz).
  - 100 sembollük session dispatch'i / `SessionManifest` / scheduler.

Bu servis `session_id` PARAMETRESİ ALMAZ -- ne `AttemptClaim` ne
`AttemptResult` bir `session_id` alanı taşır (o, `session_manifest.py`
seviyesinde, `{protocol_version, T_session_date}`'ten `compute_session_id()`
ile HER ZAMAN yeniden türetilebilen bir kavramdır) -- gereksiz, tüketilmeyen
bir parametre EKLENMEZ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import numpy as np

from app.engines.technical.data_quality import (
    DataQualityError,
    InvalidOHLCVError,
    TradingDayContinuityError,
    check_data_quality,
    check_raw_ohlcv_integrity,
    check_trading_day_continuity,
)
from app.engines.technical.engine import MIN_HISTORY_DAYS, compute_technical_analysis
from app.engines.technical.history_window import compute_history_window, resolve_expected_start
from app.engines.technical.scoring import compute_scoring_config_hash, resolve_family_weights, resolve_indicator_weights
from app.repositories.benchmark_cache_repository import BenchmarkCacheRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_v1_activation_event_repository import TechnicalV1ActivationEventRepository
from app.repositories.technical_v1_activation_lock_repository import TechnicalV1ActivationLockRepository
from app.repositories.technical_v1_attempt_repository import TechnicalV1AttemptRepository
from app.research.activation_event import (
    TechnicalV1ActivationEvent,
    compute_initial_activation_event_id,
    compute_lock_authorized_activation_event_id,
)
from app.research.activation_lock import TechnicalV1ActivationLock, compute_runtime_fingerprint
from app.research.attempt_models import (
    AttemptClaim,
    AttemptResult,
    AttemptResultClassification,
    ClaimOutcome,
    GateCheckResult,
    PublishOutcome,
)
from app.research.attempt_reason_codes import PROVIDER_DATA_UNAVAILABLE
from app.research.evidence_identity import compute_attempt_id, compute_evaluation_id
from app.research.evidence_models import EvidenceObjectKind, ProvenanceConflictError
from app.research.evidence_object_store import EvidenceObjectStore
from app.research.evidence_serialization import (
    asset_input_sha256,
    asset_snapshot_bytes,
    benchmark_input_sha256,
    benchmark_snapshot_bytes,
    input_snapshot_sha256_from_hashes,
    technical_output_bytes,
    technical_output_sha256,
)
from app.research.exclusion_policy import (
    evaluate_history_validation_exclusion,
    evaluate_technical_score_exclusion,
    resolve_post_analysis_exclusion,
)
from app.research.identity_gates import (
    IdentityGateEvaluation,
    evaluate_config_gate,
    evaluate_methodology_gate,
    evaluate_runtime_gate,
    evaluate_universe_gate,
)
from app.research.preclaim_authorization import PreClaimStatus, authorize_pre_claim
from app.research.technical_v1_methodology_observation import observe_methodology_source_fingerprint
from app.research.technical_v1_protocol import load_verified_technical_v1_protocol
from app.research.technical_v1_runtime_identity import observe_runtime_fingerprint
from app.research.technical_v1_scoring_config_values import load_verified_scoring_config_hash
from app.research.technical_versions import (
    assert_identity_matches_running_engine,
    identity_for_protocol_version,
    validate_lock_identity,
)
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.benchmark_service import get_benchmark_close_series
from app.services.market_data.completed_bars import filter_completed_daily_bars
from app.services.market_data.trading_calendar import normalize_bist_daily_sessions, session_normalization_to_dict


class AttemptExecutionOutcome(str, Enum):
    """`execute_attempt()`'in dönebileceği KAPALI sonuç kümesi -- bir
    `AttemptResult` YAYINLANMAMIŞ olabilecek durumları (henüz aktivasyon
    yok / sembol dondurulmuş evren dışı / bu attempt zaten başka bir
    worker'a ait) bir yayınlanmış terminal sonuçtan AYIRT ETMEK içindir.
    Bunların HİÇBİRİ bir `AttemptResultClassification`/`native_reason_code`
    DEĞİLDİR -- bu, PRE-CLAIM/orkestrasyon seviyesinde bir kontrol akışı
    sonucudur (bkz. HATA 13B section 21, AYNI ayrım burada da korunur)."""

    ACTIVATION_LOCK_NOT_FOUND = "ACTIVATION_LOCK_NOT_FOUND"
    PRE_ACTIVATION = "PRE_ACTIVATION"
    OUTSIDE_FROZEN_UNIVERSE = "OUTSIDE_FROZEN_UNIVERSE"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    RESULT_PUBLISHED = "RESULT_PUBLISHED"


@dataclass(frozen=True)
class AttemptExecutionReport:
    """`execute_attempt()`'in TEK dönüş zarfı -- testlerin/gelecekteki
    çağıranın hem "ne oldu" (`outcome`) hem (varsa) GERÇEKTEN yayınlanan
    `AttemptResult`'ı hem de yayınlama sonucunun (`CREATED`/
    `IDEMPOTENT_REUSE`) KENDİSİNİ tek bir yerden okuyabilmesi içindir."""

    outcome: AttemptExecutionOutcome
    result: AttemptResult | None = None
    publish_outcome: PublishOutcome | None = None


# ---------------------------------------------------------------------------
# HATA 13C section 19 -- pure classification builder (private, dar kapsamlı).
# Hiçbir I/O yapmaz, yalnızca ZATEN üretilmiş IdentityGateEvaluation/
# ExclusionEvaluation nesnelerini AttemptResultClassification/native_reason_
# code çiftine indirger. Dev bir genel "policy engine" DEĞİLDİR -- kapalı,
# sabit taksonomiyi AÇIKÇA kodlar.
# ---------------------------------------------------------------------------


def _first_failing_identity_gate(
    config: IdentityGateEvaluation,
    methodology: IdentityGateEvaluation,
    runtime: IdentityGateEvaluation,
    universe: IdentityGateEvaluation,
) -> tuple[AttemptResultClassification, str] | None:
    """Dört kapıdan (CONFIG/METHODOLOGY/RUNTIME/UNIVERSE, HER ZAMAN bu
    sabit sırayla -- bu dört kapının HER YERDE, `identity_gates.py`'den
    `attempt_reason_codes.py`'ye, AttemptResult alan sırasına kadar
    tutarlı tutulan KENDİ sırası) FAIL olan İLKİNİ döner. Final selector'ın
    `_classification_gate_consistency_holds()`'u YALNIZCA "BLOCKED_X <=>
    gate X FAIL" ilişkisini zorunlu kılar -- diğer üç gate'in değeri
    hakkında hiçbir kısıt YOKTUR (bkz. final_evaluation_selector.py); bu
    yüzden BİRDEN FAZLA gate aynı anda FAIL olsa bile TEK bir öncelik
    sırası seçmek YETERLİ ve GÜVENLİDİR -- şema ihlali OLUŞTURMAZ.
    Hepsi PASS ise `None` döner."""
    if config.result == GateCheckResult.FAIL:
        return AttemptResultClassification.BLOCKED_CONFIG_DRIFT, config.reason_code
    if methodology.result == GateCheckResult.FAIL:
        return AttemptResultClassification.BLOCKED_METHODOLOGY_DRIFT, methodology.reason_code
    if runtime.result == GateCheckResult.FAIL:
        return AttemptResultClassification.BLOCKED_RUNTIME_IDENTITY, runtime.reason_code
    if universe.result == GateCheckResult.FAIL:
        return AttemptResultClassification.BLOCKED_UNIVERSE_OR_ASSET_CONFIG, universe.reason_code
    return None


def _classify_post_analysis(
    technical_score: float | None, history_validation_status: str
) -> tuple[AttemptResultClassification, str | None]:
    """HATA 12 final closure'ın KİLİTLİ tek-neden önceliğini (TECHNICAL_
    SCORE_NONE > LEADING_EDGE_UNVERIFIED) `resolve_post_analysis_
    exclusion()`'a DELEGE eder -- burada İKİNCİ bir öncelik kopyası
    YAZILMAZ."""
    score_exclusion = evaluate_technical_score_exclusion(technical_score)
    history_exclusion = evaluate_history_validation_exclusion(history_validation_status)
    resolved = resolve_post_analysis_exclusion(score_exclusion, history_exclusion)
    if resolved.excluded:
        return AttemptResultClassification.EXCLUSION, resolved.reason_code
    return AttemptResultClassification.VALID_CANDIDATE, None


def _cast_for_asset_evidence(df):
    """`serialize_asset_snapshot()` (HATA 12N1) kanonik OHLCV şemasını
    (Open/High/Low/Close=float64, Volume=int64) KATI olarak zorunlu kılar,
    HİÇBİR sessiz coerce YAPMAZ -- provider'ın KENDİSİ Volume'u float64
    döndürebileceğinden (yfinance garantisi DEĞİL), bu dönüştürme burada,
    AÇIKÇA, TEK bir yerde yapılır. BİLİMSEL boru hattında kullanılan
    `df`'İN KENDİSİNİ DEĞİŞTİRMEZ -- yalnızca evidence-capture için AYRI
    bir kopya üretir (bkz. çağrı noktası)."""
    evidence_df = df.copy()
    evidence_df[["Open", "High", "Low", "Close"]] = evidence_df[["Open", "High", "Low", "Close"]].astype(np.float64)
    evidence_df["Volume"] = evidence_df["Volume"].astype(np.int64)
    return evidence_df


class TechnicalV1AttemptExecutionService:
    """HATA 13C section 4/5: TEK bir (session, symbol, attempt_number)
    denemesini yürüten servis. TÜM bağımlılıklar constructor'da AÇIKÇA
    enjekte edilir -- hiçbir global Firestore/GCS client'ı burada
    OLUŞTURULMAZ (her repository/store KENDİ lazy-init desenini korur,
    bkz. HATA 12N1/12N3C2-B2-B)."""

    def __init__(
        self,
        *,
        activation_lock_repo: TechnicalV1ActivationLockRepository,
        activation_event_repo: TechnicalV1ActivationEventRepository,
        attempt_repo: TechnicalV1AttemptRepository,
        evidence_store: EvidenceObjectStore,
        provider: MarketDataProvider,
        config_repo: SystemConfigRepository,
        benchmark_cache_repo: BenchmarkCacheRepository,
    ) -> None:
        self._activation_lock_repo = activation_lock_repo
        self._activation_event_repo = activation_event_repo
        self._attempt_repo = attempt_repo
        self._evidence_store = evidence_store
        self._provider = provider
        self._config_repo = config_repo
        self._benchmark_cache_repo = benchmark_cache_repo

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def execute_attempt(
        self,
        *,
        activation_lock_id: str,
        protocol_version: str,
        T_session_date: str,
        symbol: str,
        attempt_number: int,
        now: datetime | None = None,
    ) -> AttemptExecutionReport:
        """HATA 13C section 2/6: TEK bir mantıksal deneme. `now` verilirse
        (testlerde deterministik olmak için) hem veri-penceresi hem
        `started_at`/`finished_at`/`scheduled_for` hesaplarında kullanılır;
        verilmezse gerçek `datetime.now(timezone.utc)`."""
        effective_now = now if now is not None else datetime.now(timezone.utc)

        # ---- 1) verified activation lock (section 7) --------------------
        persisted_lock = self._activation_lock_repo.get_verified(activation_lock_id)
        if persisted_lock is None:
            return AttemptExecutionReport(outcome=AttemptExecutionOutcome.ACTIVATION_LOCK_NOT_FOUND)
        activation_lock = persisted_lock.lock

        # ---- 1b) TECHNICAL V2: sürümlü kimlik -- claim'den ÖNCE, fail-fast.
        # Sürüm kilidin protocol_version'ından çözülür; çağıranın
        # protocol_version'ı kilitle AYNI olmalı (evaluation/attempt ID'leri
        # ondan türetilir), kilit sürümün güvenilen kimliğini TAM taşımalı ve
        # çalışan motor sürümün engine_version'ıyla eşleşmeli (engine 1.15.0
        # altında YENİ V1 attempt'i burada, hiçbir claim/yazma olmadan reddedilir).
        if protocol_version != activation_lock.protocol_version:
            raise ProvenanceConflictError(
                f"istek protocol_version ({protocol_version!r}) activation_lock.protocol_version "
                f"({activation_lock.protocol_version!r}) ile eşleşmiyor"
            )
        evaluation_identity = identity_for_protocol_version(activation_lock.protocol_version)
        assert_identity_matches_running_engine(evaluation_identity)
        validate_lock_identity(activation_lock, evaluation_identity)

        # ---- 2) verified authorizing event (section 8/9/10) -------------
        activation_event = self._find_authorizing_event(activation_lock)

        # ---- 3) verified protocol (section 11) ---------------------------
        trusted_protocol = load_verified_technical_v1_protocol(
            activation_lock.protocol_sha256, evaluation_identity.spec.protocol_path
        )

        # ---- 4) pre-claim authorization -- HEMEN claim_attempt()'ten ÖNCE
        #         (section 12/13, HATA 13B -> 13C kritik kablolaması) ------
        authorization = authorize_pre_claim(
            activation_lock=activation_lock,
            activation_event=activation_event,
            trusted_protocol=trusted_protocol,
            symbol=symbol,
        )
        if authorization.status == PreClaimStatus.PRE_ACTIVATION:
            return AttemptExecutionReport(outcome=AttemptExecutionOutcome.PRE_ACTIVATION)
        if authorization.status == PreClaimStatus.OUTSIDE_FROZEN_UNIVERSE:
            return AttemptExecutionReport(outcome=AttemptExecutionOutcome.OUTSIDE_FROZEN_UNIVERSE)
        # Buraya ulaşıldıysa authorization.status == AUTHORIZED (kapalı,
        # üç-üyeli enum -- section 21/28).

        # ---- 5) claim (section 14/15/16) ---------------------------------
        observed_runtime_fingerprint = observe_runtime_fingerprint()
        evaluation_id = compute_evaluation_id(protocol_version, T_session_date, symbol)
        attempt_id = compute_attempt_id(evaluation_id, attempt_number)
        claim = AttemptClaim(
            attempt_id=attempt_id,
            evaluation_id=evaluation_id,
            attempt_number=attempt_number,
            protocol_version=protocol_version,
            T_session_date=T_session_date,
            symbol=symbol,
            claimed_by_runtime=observed_runtime_fingerprint,
            activation_lock_id=activation_lock.activation_lock_id,
        )
        claim_outcome = self._attempt_repo.claim_attempt(claim)
        if claim_outcome == ClaimOutcome.ALREADY_CLAIMED:
            # HATA 13C section 15/16/54: bu attempt_id BAŞKA bir claim
            # tarafından ZATEN sahiplenilmiş (ilk-claimant-kazanır, lease
            # çalma/timeout takeover YOK) -- İKİNCİ bir provider fetch/
            # evidence-capture/scientific work YAPILMAZ, koşulsuz DURULUR.
            return AttemptExecutionReport(outcome=AttemptExecutionOutcome.ALREADY_CLAIMED)

        # ---- 6) post-claim kimlik kapıları -- provider işinden ÖNCE
        #         (section 17/18) ------------------------------------------
        weights = resolve_indicator_weights(self._config_repo.get_raw("technical_indicator_weights"))
        family_weights = resolve_family_weights(self._config_repo.get_raw("technical_family_weights"))
        observed_scoring_config_hash = compute_scoring_config_hash(weights, family_weights)
        expected_scoring_config_hash = load_verified_scoring_config_hash(
            activation_lock.freeze_manifest_sha256, evaluation_identity.spec.freeze_manifest_path
        )
        config_result = evaluate_config_gate(expected_scoring_config_hash, observed_scoring_config_hash)

        observed_methodology_fingerprint = observe_methodology_source_fingerprint(
            normalize_newlines=evaluation_identity.normalized_fingerprint
        )
        methodology_result = evaluate_methodology_gate(
            activation_lock.authorized_methodology_source_fingerprint, observed_methodology_fingerprint
        )

        expected_runtime_fingerprint = compute_runtime_fingerprint(
            activation_lock.authorized_project_id,
            activation_lock.authorized_runtime_service,
            activation_lock.authorized_runtime_revision,
        )
        runtime_result = evaluate_runtime_gate(expected_runtime_fingerprint, observed_runtime_fingerprint)

        universe_result = evaluate_universe_gate(trusted_protocol.frozen_symbols, symbol)

        blocked = _first_failing_identity_gate(config_result, methodology_result, runtime_result, universe_result)
        if blocked is not None:
            classification, native_reason_code = blocked
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=classification,
                native_reason_code=native_reason_code,
            )
            return self._publish(result)

        # ---- 7) veri edinimi -- YALNIZCA dört kapı de PASS olduktan SONRA
        #         (section 20) ------------------------------------------
        history_window = compute_history_window(effective_now)
        try:
            provider_history = self._provider.get_history(
                symbol,
                start=history_window.provider_request_start.isoformat(),
                end=history_window.provider_request_end.isoformat(),
            )
        except Exception:
            # HATA 13C section 20/39: sağlayıcı sınırında BEKLENEN dış
            # arıza -- ham exception TÜRÜ kapalı bir taksonomi
            # OLUŞTURMADIĞINDAN (bkz. bist_provider.py'nin kendi retry-
            # tükenme deseni) burada, YALNIZCA bu çağrı etrafında, geniş
            # yakalanır. Traceback/mesaj native_reason_code'a ASLA taşınmaz.
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=AttemptResultClassification.FAILED,
                native_reason_code=PROVIDER_DATA_UNAVAILABLE,
            )
            return self._publish(result)

        provider_history = filter_completed_daily_bars(provider_history, now=effective_now)
        provider_history, session_normalization_result = normalize_bist_daily_sessions(
            provider_history, symbol=symbol, provider="yahoo_finance"
        )

        # ---- 8) asset evidence -- GENİŞ, pre-roll-dahil provider_history,
        #         trim'DEN ÖNCE (section 24/25 -- HATA 12/13A'nın kilitlediği
        #         leading-edge yeniden-kuruluş gereksinimi) -----------------
        evidence_asset_df = _cast_for_asset_evidence(provider_history)
        asset_hash = asset_input_sha256(evidence_asset_df, symbol)
        asset_ref = self._evidence_store.put_immutable(
            EvidenceObjectKind.ASSET_SNAPSHOT, asset_hash, asset_snapshot_bytes(evidence_asset_df, symbol)
        )

        expected_start, validation_status = resolve_expected_start(provider_history, history_window.analysis_start)

        try:
            check_trading_day_continuity(provider_history, symbol, now=effective_now, expected_start=expected_start)
        except TradingDayContinuityError as exc:
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=AttemptResultClassification.EXCLUSION,
                native_reason_code=exc.reason_code,
                asset_hash=asset_hash,
                asset_ref=asset_ref,
            )
            return self._publish(result)

        df = provider_history[provider_history.index.date >= expected_start]

        try:
            check_raw_ohlcv_integrity(df, symbol)
        except InvalidOHLCVError as exc:
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=AttemptResultClassification.EXCLUSION,
                native_reason_code=exc.reason_code,
                asset_hash=asset_hash,
                asset_ref=asset_ref,
            )
            return self._publish(result)

        try:
            check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=effective_now)
        except DataQualityError as exc:
            # HATA 13C section 28/29: YALNIZCA HATA-12-onaylı INSUFFICIENT_
            # HISTORY burada EXCLUSION'a eşlenir. MISSING_COLUMNS/MISSING_
            # OHLCV/STALE_DATA/TRADING_CALENDAR_UNSUPPORTED_YEAR için
            # protokol taksonomisinde AÇIK bir karar YOK -- section 28'in
            # "guess yapma" talimatı gereği bunlar BURADA yakalanmaz,
            # olduğu gibi yukarı fırlatılır (internal-defect sınırı,
            # section 21: claim var, result YOK -- NO_RESULT).
            if exc.reason_code != "INSUFFICIENT_HISTORY":
                raise
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=AttemptResultClassification.EXCLUSION,
                native_reason_code=exc.reason_code,
                asset_hash=asset_hash,
                asset_ref=asset_ref,
            )
            return self._publish(result)

        # ---- 9) benchmark -- BİR KEZ çekilir, SONRA compute_technical_
        #         analysis()'e ENJEKTE edilir (section 26 -- motorun
        #         GERÇEKTEN tükettiği ile evidence'ın AYNI olduğu garanti
        #         edilir, ikinci bir bağımsız fetch YAPILMAZ) --------------
        try:
            benchmark_close_series = get_benchmark_close_series(
                provider=self._provider, cache_repo=self._benchmark_cache_repo
            )
        except Exception:
            result = self._build_result(
                claim=claim,
                effective_now=effective_now,
                runtime_fingerprint=observed_runtime_fingerprint,
                config_result=config_result.result,
                methodology_result=methodology_result.result,
                runtime_result=runtime_result.result,
                universe_result=universe_result.result,
                classification=AttemptResultClassification.FAILED,
                native_reason_code=PROVIDER_DATA_UNAVAILABLE,
                asset_hash=asset_hash,
                asset_ref=asset_ref,
            )
            return self._publish(result)

        # ---- 10) bilimsel hesaplama -- formül KOPYASI YOK, paylaşılan
        #          `compute_technical_analysis()` doğrudan çağrılır --------
        analysis = compute_technical_analysis(
            df,
            symbol,
            weights,
            family_weights,
            observed_scoring_config_hash,
            validation_status.value,
            session_normalization_to_dict(session_normalization_result),
            provider=self._provider,
            benchmark_cache_repo=self._benchmark_cache_repo,
            benchmark_close_series=benchmark_close_series,
            now=effective_now,
        )

        # ---- 11) benchmark + output evidence -- YALNIZCA başarılı analiz
        #          SONRASI (section 26/27) -----------------------------
        benchmark_hash = benchmark_input_sha256(benchmark_close_series)
        benchmark_ref = self._evidence_store.put_immutable(
            EvidenceObjectKind.BENCHMARK_SNAPSHOT, benchmark_hash, benchmark_snapshot_bytes(benchmark_close_series)
        )
        output_hash = technical_output_sha256(analysis)
        output_ref = self._evidence_store.put_immutable(
            EvidenceObjectKind.TECHNICAL_OUTPUT, output_hash, technical_output_bytes(analysis)
        )

        # ---- 12) post-analysis exclusion + sınıflandırma (section 29/30) -
        classification, native_reason_code = _classify_post_analysis(
            analysis.technical_score, analysis.history_validation_status
        )
        result = self._build_result(
            claim=claim,
            effective_now=effective_now,
            runtime_fingerprint=observed_runtime_fingerprint,
            config_result=config_result.result,
            methodology_result=methodology_result.result,
            runtime_result=runtime_result.result,
            universe_result=universe_result.result,
            classification=classification,
            native_reason_code=native_reason_code,
            asset_hash=asset_hash,
            asset_ref=asset_ref,
            benchmark_hash=benchmark_hash,
            benchmark_ref=benchmark_ref,
            output_hash=output_hash,
            output_ref=output_ref,
        )
        return self._publish(result)

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _find_authorizing_event(
        self, activation_lock: TechnicalV1ActivationLock
    ) -> TechnicalV1ActivationEvent | None:
        """HATA 13B section 9/10: deterministik, tarama-yapmayan (scan-free)
        arama -- ÖNCE `protocol_version`'ın `INITIAL` olayı (bu kilidi
        bağlıyorsa kullan), YOKSA bu TAM kilidin KENDİ `LOCK_AUTHORIZED`
        olayı. Doğrulanmış bir olay kendi deterministik kimliğiyle
        ÇELİŞİRSE `get_verified()`'ın KENDİSİ `ProvenanceConflictError`
        fırlatır -- burada YUTULMAZ/sessizce PRE_ACTIVATION'a
        DÖNÜŞTÜRÜLMEZ (section 10, 21)."""
        initial_event_id = compute_initial_activation_event_id(protocol_version=activation_lock.protocol_version)
        initial_envelope = self._activation_event_repo.get_verified(initial_event_id)
        if initial_envelope is not None and (
            initial_envelope.event.activation_lock_id == activation_lock.activation_lock_id
        ):
            return initial_envelope.event

        lock_authorized_event_id = compute_lock_authorized_activation_event_id(
            protocol_version=activation_lock.protocol_version,
            activation_lock_id=activation_lock.activation_lock_id,
        )
        lock_authorized_envelope = self._activation_event_repo.get_verified(lock_authorized_event_id)
        if lock_authorized_envelope is not None:
            return lock_authorized_envelope.event

        return None

    @staticmethod
    def _build_result(
        *,
        claim: AttemptClaim,
        effective_now: datetime,
        runtime_fingerprint: str,
        config_result: GateCheckResult,
        methodology_result: GateCheckResult,
        runtime_result: GateCheckResult,
        universe_result: GateCheckResult,
        classification: AttemptResultClassification,
        native_reason_code: str | None,
        asset_hash: str | None = None,
        asset_ref=None,
        benchmark_hash: str | None = None,
        benchmark_ref=None,
        output_hash: str | None = None,
        output_ref=None,
    ) -> AttemptResult:
        """HATA 13C section 36: mevcut `AttemptResult` şemasını KULLANIR,
        GENİŞLETMEZ. `input_snapshot_sha256`, `evidence_serialization.
        input_snapshot_sha256_from_hashes()` (TEK paylaşılan birleştirici)
        ile, asset+benchmark İKİSİ DE mevcutsa türetilir -- ikinci bir
        birleştirme formülü YAZILMAZ."""
        timestamp = effective_now.isoformat()
        input_snapshot_sha256 = (
            input_snapshot_sha256_from_hashes(asset_hash, benchmark_hash)
            if asset_hash is not None and benchmark_hash is not None
            else None
        )
        return AttemptResult(
            attempt_id=claim.attempt_id,
            evaluation_id=claim.evaluation_id,
            attempt_number=claim.attempt_number,
            protocol_version=claim.protocol_version,
            T_session_date=claim.T_session_date,
            symbol=claim.symbol,
            scheduled_for=claim.T_session_date,
            runtime_fingerprint=runtime_fingerprint,
            activation_lock_id=claim.activation_lock_id,
            config_gate_result=config_result,
            methodology_gate_result=methodology_result,
            runtime_gate_result=runtime_result,
            universe_gate_result=universe_result,
            result_classification=classification,
            native_reason_code=native_reason_code,
            started_at=timestamp,
            finished_at=timestamp,
            asset_input_sha256=asset_hash,
            benchmark_input_sha256=benchmark_hash,
            input_snapshot_sha256=input_snapshot_sha256,
            technical_output_sha256=output_hash,
            asset_object_ref=asset_ref,
            benchmark_object_ref=benchmark_ref,
            technical_output_object_ref=output_ref,
        )

    def _publish(self, result: AttemptResult) -> AttemptExecutionReport:
        publish_outcome = self._attempt_repo.publish_result(result)
        return AttemptExecutionReport(
            outcome=AttemptExecutionOutcome.RESULT_PUBLISHED, result=result, publish_outcome=publish_outcome
        )
