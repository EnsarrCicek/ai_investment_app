"""Technical V1 kimlik-kapıları (identity gates) -- SAF karşılaştırma
katmanı. HATA 12N3C2-B2-D.

Bu modül HİÇBİR I/O yapmaz (Firestore/dosya sistemi/ortam değişkeni/ağ
erişimi YOK) -- yalnızca ZATEN GÖZLEMLENMİŞ (observed) ve ZATEN
YETKİLENDİRİLMİŞ (expected, `TechnicalV1ActivationLock`'tan ya da dondurulmuş
freeze manifest'ten gelen) iki değeri karşılaştırıp `IdentityGateEvaluation`
üretir.

Üç kilitli sorumluluk (section 3, ASLA çakışmaz/tekrarlanmaz):
  - CONFIG kapısı: YALNIZCA canlı çözümlenen teknik skor config'i vs
    dondurulmuş Technical V1 `scoring_config_hash`.
  - METHODOLOGY kapısı: YALNIZCA şu an deploy edilmiş 27-dosya metodoloji
    parmak-izi vs aktivasyon kilidinin yetkilendirdiği metodoloji parmak-izi.
  - RUNTIME kapısı: YALNIZCA şu an gözlemlenen audit/runtime kimliği vs
    aktivasyon kilidinin yetkilendirdiği runtime kimliği.

Bu modül HENÜZ:
  - `AttemptResultClassification`e (BLOCKED_CONFIG_DRIFT vb.) eşleme
    YAPMAZ -- bu, gelecekteki attempt-execution servisinin işidir (section
    9/23).
  - Universe/asset-config kapısını İÇERMEZ (section 22, kapsam dışı).
  - `TechnicalV1ActivationLockRepository`'yi hiç import/çağırmaz (section
    20) -- yalnızca ZATEN doğrulanmış bir `TechnicalV1ActivationLock`
    nesnesinin ilgili alanlarını PARAMETRE olarak alır.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.attempt_reason_codes import (
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
)
from app.research.attempt_models import GateCheckResult
from app.research.evidence_models import validate_sha256_hex


@dataclass(frozen=True)
class IdentityGateEvaluation:
    """Tek bir kimlik-kapısının SAF sonucu.

    Kesin değişmez: `result == PASS` <=> `reason_code is None`;
    `result == FAIL` <=> `reason_code`, o kapı için TEK, kararlı sabit
    reason-code string'idir. Ham exception mesajı/traceback/URL/credential/
    kullanıcı verisi ASLA taşımaz -- yalnızca kapalı, kararlı bir kategori.
    """

    result: GateCheckResult
    reason_code: str | None

    def __post_init__(self) -> None:
        if self.result == GateCheckResult.PASS:
            if self.reason_code is not None:
                raise ValueError(f"PASS sonucu reason_code taşıyamaz: {self.reason_code!r}")
        else:
            if not isinstance(self.reason_code, str) or not self.reason_code:
                raise ValueError(f"FAIL sonucu boş olmayan bir reason_code string'i taşımalı: {self.reason_code!r}")


def evaluate_config_gate(expected_scoring_config_hash: str, observed_scoring_config_hash: str) -> IdentityGateEvaluation:
    """CONFIG kapısı -- YALNIZCA canlı çözümlenen skor config'i vs
    dondurulmuş Technical V1 `scoring_config_hash`. Her iki değer de
    kanonik (64 küçük-harf hex) OLMALI -- format hatası burada, yerel
    olarak, hiçbir I/O yapılmadan fırlatılır (çağıranın kendi hatası)."""
    validate_sha256_hex(expected_scoring_config_hash)
    validate_sha256_hex(observed_scoring_config_hash)
    if observed_scoring_config_hash == expected_scoring_config_hash:
        return IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code=None)
    return IdentityGateEvaluation(result=GateCheckResult.FAIL, reason_code=SCORING_CONFIG_HASH_MISMATCH)


def evaluate_methodology_gate(
    expected_methodology_source_fingerprint: str, observed_methodology_source_fingerprint: str
) -> IdentityGateEvaluation:
    """METHODOLOGY kapısı -- YALNIZCA şu an deploy edilmiş 27-dosya
    metodoloji parmak-izi vs aktivasyon kilidinin yetkilendirdiği parmak-izi.

    KASITLI OLARAK karşılaştırmaz (section 13, ayrı provenance/runtime
    rolleri): `methodology_git_commit`, `protocol_sha256`,
    `freeze_manifest_sha256`, Cloud Run revision."""
    validate_sha256_hex(expected_methodology_source_fingerprint)
    validate_sha256_hex(observed_methodology_source_fingerprint)
    if observed_methodology_source_fingerprint == expected_methodology_source_fingerprint:
        return IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code=None)
    return IdentityGateEvaluation(result=GateCheckResult.FAIL, reason_code=METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH)


def evaluate_runtime_gate(expected_runtime_fingerprint: str, observed_runtime_fingerprint: str) -> IdentityGateEvaluation:
    """RUNTIME kapısı -- YALNIZCA şu an gözlemlenen audit/runtime kimliği
    (`project_id/service/revision`) vs aktivasyon kilidinin yetkilendirdiği
    runtime kimliği. Her iki değer de ZATEN `compute_runtime_fingerprint()`
    ile üretilmiş kanonik string'ler OLMALI -- bu fonksiyon ikinci bir
    string-birleştirme uygulaması İÇERMEZ."""
    if observed_runtime_fingerprint == expected_runtime_fingerprint:
        return IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code=None)
    return IdentityGateEvaluation(result=GateCheckResult.FAIL, reason_code=RUNTIME_IDENTITY_UNAUTHORIZED)
