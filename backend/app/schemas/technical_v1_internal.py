"""PROD-2 — Technical V1 internal job endpoint istek/yanıt şemaları.

Hiçbir şema bir sembol/sembol-listesi alanı TAŞIMAZ (section 8/37) --
dondurulmuş 100-sembol evren HER ZAMAN `TrustedTechnicalV1Protocol.
frozen_symbol_list`'ten gelir, çağıran bunu ASLA değiştiremez. Ham
`FinalEvaluation`/evidence içeriği HİÇBİR yanıt şemasında YOKTUR (section
13) -- yalnızca güvenli sayım/durum alanları."""

from __future__ import annotations

from pydantic import BaseModel


class Attempt1Request(BaseModel):
    protocol_version: str
    protocol_sha256: str
    T_session_date: str
    activation_lock_id: str


class Attempt2Request(BaseModel):
    protocol_version: str
    protocol_sha256: str
    T_session_date: str
    activation_lock_id: str
    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str
    E1_date: str


class FinalizationRequest(BaseModel):
    protocol_version: str
    protocol_sha256: str
    T_session_date: str
    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str
    E1_date: str


class ManifestRequest(BaseModel):
    protocol_version: str
    protocol_sha256: str
    T_session_date: str
    methodology_git_commit: str
    freeze_manifest_sha256: str
    engine_version: str
    scoring_config_hash: str
    E1_date: str


class PhaseSummaryResponse(BaseModel):
    phase: str
    session_id: str
    T_session_date: str
    processed: int
    outcome_counts: dict[str, int]


class ManifestSummaryResponse(BaseModel):
    session_id: str
    accounting_status: str
    expected_symbol_count: int
    verified_count: int
    absent_count: int
    conflict_count: int
    manifest_persisted: bool
    create_outcome: str | None
