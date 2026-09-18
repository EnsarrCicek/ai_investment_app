"""PROD-2 — Technical V1 internal job endpoint'leri.

Bu router, HATA 12/13'te KİLİTLENEN `TechnicalV1SessionController`'ın dört
fazını (attempt1/attempt2/finalization/manifest) çağıran, BAŞKA hiçbir
bilimsel/orkestrasyon mantığı İÇERMEYEN İNCE bir HTTP katmanıdır.

KİLİTLİ SINIRLAR (section 6/11/12/18):
  - 09:00 attempt2 kararı / 09:45 formal cutoff mantığı BURADA TEKRAR
    UYGULANMAZ -- bunlar TAMAMEN `TechnicalV1Attempt2Orchestrator`/
    `TechnicalV1Finalizer`'a (değiştirilmemiş) delege edilir.
  - Bu router HİÇBİR activation lock/event OLUŞTURMAZ -- `/activate`/
    `/start-holdout` gibi bir uç nokta KASITLI OLARAK YOKTUR.
  - Hiçbir Cloud Scheduler kaynağı OLUŞTURULMAZ -- uç noktalar
    ÇAĞRILABİLİR hale gelir ama gelecekteki bir scheduler adımına kadar
    DORMANT kalır.

AUTH (section 7): `app/api/jobs.py`'deki `DAILY_JOB_SECRET` deseninin
BİREBİR AYNISI -- ayrı bir ikinci gizli-anahtar şeması İCAT EDİLMEDİ,
yalnızca AYRI bir sabit (`TECHNICAL_V1_JOB_SECRET`) kullanılır (aynı
mantıkla, günlük analiz job'ıyla AYNI paylaşılan sırrı YENİDEN KULLANMAK
-- iki bağımsız operasyonel yüzeyi AYNI sırra bağlamak -- yanlış olurdu).

LOGLAMA (section 14/15/34): tek satırlık JSON metni olarak, stdlib
`logging` üzerinden emit edilir (Cloud Run/Cloud Logging, geçerli JSON
olan stdout satırlarını OTOMATİK olarak `jsonPayload`'a ayrıştırır --
hiçbir üçüncü-parti structured-logging kütüphanesi İCAT EDİLMEDİ/EKLENMEDİ,
section 16). Ham exception mesajı/secret/header/evidence İÇERİĞİ ASLA
loglanmaz -- yalnızca `type(exc).__name__` (section 34)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import TECHNICAL_V1_JOB_SECRET
from app.research.evidence_identity import compute_evaluation_id, compute_session_id
from app.research.technical_v1_production import TechnicalV1ConfigurationError, build_session_controller
from app.research.technical_v1_session_controller import SessionScientificFacts, TechnicalV1SessionController
from app.schemas.technical_v1_internal import (
    Attempt1Request,
    Attempt2Request,
    FinalizationRequest,
    ManifestRequest,
    ManifestSummaryResponse,
    PhaseSummaryResponse,
)

router = APIRouter(prefix="/internal/technical-v1", tags=["technical-v1-internal"])

_logger = logging.getLogger("technical_v1")

_SERIOUS_OUTCOMES = ("OPERATIONAL_ERROR", "RETRYABLE", "PROVENANCE_CONFLICT")


def _check_auth(x_job_secret: str | None) -> None:
    """`app/api/jobs.py::daily_analysis()` İLE BİREBİR AYNI desen (section
    7) -- eksik/yanlış sır, HİÇBİR controller/Firestore/GCS erişiminden
    ÖNCE, 403 ile reddedilir."""
    if not TECHNICAL_V1_JOB_SECRET or x_job_secret != TECHNICAL_V1_JOB_SECRET:
        raise HTTPException(status_code=403, detail="Geçersiz veya eksik job secret")


def _require_session_id(protocol_version: str, T_session_date: str) -> str:
    """`compute_session_id()`'nin KENDİ, ZATEN kilitlenmiş kanonik-tarih
    doğrulamasını yeniden kullanır -- burada İKİNCİ bir regex/timezone
    aritmetiği YAZILMAZ (section 9)."""
    try:
        return compute_session_id(protocol_version, T_session_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Geçersiz T_session_date: {exc}") from exc


def _build_controller(protocol_sha256: str) -> TechnicalV1SessionController:
    try:
        return build_session_controller(protocol_sha256=protocol_sha256)
    except TechnicalV1ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_controller_factory():
    """FastAPI `Depends()` dolaylaması -- testler `app.dependency_
    overrides[get_controller_factory]`'yi GERÇEK GCS/Firestore/provider'a
    HİÇ dokunmadan, sahte bir controller döndüren bir factory ile
    değiştirebilir (section 28/38)."""
    return _build_controller


def _log_json(level: int, **fields: object) -> None:
    payload = {"technical_v1": True, **fields}
    _logger.log(level, json.dumps(payload, default=str, sort_keys=True))


def _outcome_counts(outcomes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in outcomes:
        counts[item.outcome] = counts.get(item.outcome, 0) + 1
    return counts


def _log_phase_report(
    *,
    phase: str,
    session_id: str,
    protocol_version: str,
    T_session_date: str,
    report,
    duration_ms: float,
    activation_lock_id: str | None = None,
) -> dict[str, int]:
    """Section 15/17: her fazdan SONRA TEK bir aggregate log satırı, artı
    (varsa) HER "serious" per-sembol sonucu için AYRI bir uyarı satırı --
    PROD-1'in "100 OPERATIONAL_ERROR sessizce kaybolabilir" riskine
    doğrudan cevap."""
    counts = _outcome_counts(report.outcomes)
    serious_total = sum(counts.get(name, 0) for name in _SERIOUS_OUTCOMES)

    base_fields: dict[str, object] = {
        "phase": phase,
        "session_id": session_id,
        "protocol_version": protocol_version,
        "T_session_date": T_session_date,
        "processed": report.processed,
        "outcome_counts": counts,
        "duration_ms": round(duration_ms, 1),
    }
    if activation_lock_id is not None:
        base_fields["activation_lock_id"] = activation_lock_id

    if report.processed > 0 and serious_total == report.processed:
        _log_json(logging.ERROR, event="phase_all_symbols_failed", **base_fields)
    elif serious_total > 0:
        _log_json(logging.WARNING, event="phase_partial_failure", **base_fields)
    else:
        _log_json(logging.INFO, event="phase_completed", **base_fields)

    for item in report.outcomes:
        if item.outcome in _SERIOUS_OUTCOMES:
            _log_json(
                logging.WARNING,
                event="phase_symbol_issue",
                phase=phase,
                session_id=session_id,
                symbol=item.symbol,
                evaluation_id=compute_evaluation_id(protocol_version, T_session_date, item.symbol),
                outcome=item.outcome,
                exception_type=item.detail,
            )

    return counts


@router.post("/attempt1", response_model=PhaseSummaryResponse)
def attempt1_phase(
    request: Attempt1Request,
    x_job_secret: str | None = Header(default=None),
    controller_factory=Depends(get_controller_factory),
):
    _check_auth(x_job_secret)
    session_id = _require_session_id(request.protocol_version, request.T_session_date)
    controller = controller_factory(request.protocol_sha256)

    started = time.monotonic()
    report = controller.run_attempt1_phase(
        activation_lock_id=request.activation_lock_id,
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        now=datetime.now(timezone.utc),
    )
    duration_ms = (time.monotonic() - started) * 1000.0

    counts = _log_phase_report(
        phase="attempt1",
        session_id=session_id,
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        report=report,
        duration_ms=duration_ms,
        activation_lock_id=request.activation_lock_id,
    )
    return PhaseSummaryResponse(
        phase="attempt1",
        session_id=session_id,
        T_session_date=request.T_session_date,
        processed=report.processed,
        outcome_counts=counts,
    )


@router.post("/attempt2", response_model=PhaseSummaryResponse)
def attempt2_phase(
    request: Attempt2Request,
    x_job_secret: str | None = Header(default=None),
    controller_factory=Depends(get_controller_factory),
):
    _check_auth(x_job_secret)
    session_id = _require_session_id(request.protocol_version, request.T_session_date)
    controller = controller_factory(request.protocol_sha256)

    facts = SessionScientificFacts(
        methodology_git_commit=request.methodology_git_commit,
        freeze_manifest_sha256=request.freeze_manifest_sha256,
        engine_version=request.engine_version,
        scoring_config_hash=request.scoring_config_hash,
        E1_date=request.E1_date,
    )

    started = time.monotonic()
    report = controller.run_attempt2_phase(
        activation_lock_id=request.activation_lock_id,
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        facts=facts,
        now=datetime.now(timezone.utc),
    )
    duration_ms = (time.monotonic() - started) * 1000.0

    counts = _log_phase_report(
        phase="attempt2",
        session_id=session_id,
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        report=report,
        duration_ms=duration_ms,
        activation_lock_id=request.activation_lock_id,
    )
    return PhaseSummaryResponse(
        phase="attempt2",
        session_id=session_id,
        T_session_date=request.T_session_date,
        processed=report.processed,
        outcome_counts=counts,
    )


@router.post("/finalize", response_model=PhaseSummaryResponse)
def finalization_phase(
    request: FinalizationRequest,
    x_job_secret: str | None = Header(default=None),
    controller_factory=Depends(get_controller_factory),
):
    _check_auth(x_job_secret)
    session_id = _require_session_id(request.protocol_version, request.T_session_date)
    controller = controller_factory(request.protocol_sha256)

    facts = SessionScientificFacts(
        methodology_git_commit=request.methodology_git_commit,
        freeze_manifest_sha256=request.freeze_manifest_sha256,
        engine_version=request.engine_version,
        scoring_config_hash=request.scoring_config_hash,
        E1_date=request.E1_date,
    )

    started = time.monotonic()
    report = controller.run_finalization_phase(
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        facts=facts,
        now=datetime.now(timezone.utc),
    )
    duration_ms = (time.monotonic() - started) * 1000.0

    counts = _log_phase_report(
        phase="finalize",
        session_id=session_id,
        protocol_version=request.protocol_version,
        T_session_date=request.T_session_date,
        report=report,
        duration_ms=duration_ms,
    )
    return PhaseSummaryResponse(
        phase="finalize",
        session_id=session_id,
        T_session_date=request.T_session_date,
        processed=report.processed,
        outcome_counts=counts,
    )


@router.post("/manifest", response_model=ManifestSummaryResponse)
def manifest_phase(
    request: ManifestRequest,
    x_job_secret: str | None = Header(default=None),
    controller_factory=Depends(get_controller_factory),
):
    _check_auth(x_job_secret)
    session_id = _require_session_id(request.protocol_version, request.T_session_date)
    controller = controller_factory(request.protocol_sha256)

    facts = SessionScientificFacts(
        methodology_git_commit=request.methodology_git_commit,
        freeze_manifest_sha256=request.freeze_manifest_sha256,
        engine_version=request.engine_version,
        scoring_config_hash=request.scoring_config_hash,
        E1_date=request.E1_date,
    )

    result = controller.build_session_manifest_if_complete(
        protocol_version=request.protocol_version, T_session_date=request.T_session_date, facts=facts
    )

    accounting = result.accounting
    log_fields = {
        "phase": "manifest",
        "session_id": session_id,
        "protocol_version": request.protocol_version,
        "T_session_date": request.T_session_date,
        "accounting_status": accounting.status.value,
        "expected_count": accounting.expected_symbol_count,
        "verified_count": accounting.verified_count,
        "absent_count": accounting.absent_count,
        "conflict_count": accounting.conflict_count,
    }
    if accounting.status.value == "COMPLETE":
        _log_json(logging.INFO, event="manifest_complete", **log_fields)
    else:
        # section 17: eksik/çakışan bir session ASLA sessizce geçilmez.
        _log_json(logging.WARNING, event="manifest_incomplete", **log_fields)

    return ManifestSummaryResponse(
        session_id=session_id,
        accounting_status=accounting.status.value,
        expected_symbol_count=accounting.expected_symbol_count,
        verified_count=accounting.verified_count,
        absent_count=accounting.absent_count,
        conflict_count=accounting.conflict_count,
        manifest_persisted=result.manifest is not None,
        create_outcome=result.create_outcome.value if result.create_outcome is not None else None,
    )
