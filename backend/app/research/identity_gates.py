"""Technical V1 kimlik-kapıları (identity gates) -- SAF karşılaştırma
katmanı. HATA 12N3C2-B2-D / E1-R3.

Bu modül HİÇBİR I/O yapmaz (Firestore/dosya sistemi/ortam değişkeni/ağ
erişimi YOK) -- yalnızca ZATEN GÖZLEMLENMİŞ (observed) ve ZATEN
YETKİLENDİRİLMİŞ (expected, `TechnicalV1ActivationLock`'tan, dondurulmuş
freeze manifest'ten, ya da doğrulanmış `TrustedTechnicalV1Protocol`'den
gelen) iki değeri karşılaştırıp `IdentityGateEvaluation` üretir.

Dört kilitli sorumluluk (section 3, ASLA çakışmaz/tekrarlanmaz):
  - CONFIG kapısı: YALNIZCA canlı çözümlenen teknik skor config'i vs
    dondurulmuş Technical V1 `scoring_config_hash`.
  - METHODOLOGY kapısı: YALNIZCA şu an deploy edilmiş 27-dosya metodoloji
    parmak-izi vs aktivasyon kilidinin yetkilendirdiği metodoloji parmak-izi.
  - RUNTIME kapısı: YALNIZCA şu an gözlemlenen audit/runtime kimliği vs
    aktivasyon kilidinin yetkilendirdiği runtime kimliği.
  - UNIVERSE kapısı (HATA 12N3C2-E1-R3): YALNIZCA gözlemlenen (attempt'in
    taşıdığı) sembol vs dondurulmuş Technical V1 100-sembol evren üyeliği.
    Technical V1'de bunun ÖTESİNDE hiçbir dondurulmuş per-sembol asset
    config alanı YOKTUR (bkz. HATA 12N3C2-E1 audit'i, Decision B) -- bu
    yüzden bu kapı SADECE küme-üyeliğidir, başka hiçbir asset-config
    karşılaştırması İÇERMEZ.

Bu modül HENÜZ:
  - `AttemptResultClassification`e (BLOCKED_CONFIG_DRIFT vb.) eşleme
    YAPMAZ -- bu, gelecekteki attempt-execution servisinin işidir (section
    9/23).
  - `TechnicalV1ActivationLockRepository`'yi/protokol-yükleyicisini/
    `TechnicalV1ActivationLock`'u hiç import/çağırmaz (section 20) --
    yalnızca ZATEN doğrulanmış nesnelerin ilgili alanlarını (`frozen_
    symbols`, hash'ler, fingerprint'ler) PARAMETRE olarak alır. UNIVERSE
    kapısı, protokol artefaktını KENDİSİ YENİDEN AÇMAZ/doğrulamaz --
    çağıran `TrustedTechnicalV1Protocol.frozen_symbols`'ı sağlar.
  - PRE-CLAIM controller reddetme mantığını İÇERMEZ -- bu SADECE, gelecekte
    zaten claim edilmiş bir attempt için post-claim, defense-in-depth bir
    yeniden-doğrulamadır (bkz. HATA 12N3C2-E1 section 14/16).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.attempt_reason_codes import (
    METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH,
    RUNTIME_IDENTITY_UNAUTHORIZED,
    SCORING_CONFIG_HASH_MISMATCH,
    SYMBOL_NOT_IN_FROZEN_UNIVERSE,
)
from app.research.attempt_models import GateCheckResult
from app.research.evidence_models import EvidenceIntegrityError, validate_sha256_hex


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


def evaluate_universe_gate(expected_frozen_symbols: frozenset[str], observed_symbol: str) -> IdentityGateEvaluation:
    """UNIVERSE kapısı -- YALNIZCA gözlemlenen sembolün dondurulmuş
    Technical V1 100-sembol evreninin TAM (exact) bir üyesi olup olmadığı.
    HİÇBİR normalizasyon YAPILMAZ (section 8): büyük/küçük harf
    dönüşümü, boşluk temizleme, `.IS` son-ek kaldırma -- HİÇBİRİ. Girdi
    zaten kanonik bare-ticker formunda OLMALI, aksi halde (kanonik olsa
    bile evren dışıysa) FAIL olur.

    `expected_frozen_symbols`, ZATEN doğrulanmış bir `TrustedTechnicalV1
    Protocol.frozen_symbols`'tur -- bu fonksiyon protokol artefaktını
    KENDİSİ yeniden AÇMAZ/doğrulamaz, 100-eleman/benzersizlik/hash
    kontrolünü TEKRARLAMAZ (bunlar zaten `load_verified_technical_v1_
    protocol()` tarafından garanti edilir, section 11). Yalnızca kaba bir
    kullanım-hatası/programlama-hatası koruması yapar (section 10) --
    tip/boşluk kontrolü, ONARIM/normalizasyon DEĞİL.

    `observed_symbol` boş/None/string-olmayan ise bu bir GEÇERLİ bilimsel
    "evren dışı" gözlemi DEĞİLDİR -- kaba bir programlama/domain girdi
    hatasıdır (section 9) ve `EvidenceIntegrityError` olarak yerel,
    hiçbir I/O yapılmadan fırlatılır -- ASLA `SYMBOL_NOT_IN_FROZEN_
    UNIVERSE`'e dönüştürülmez."""
    if not isinstance(expected_frozen_symbols, frozenset):
        raise TypeError(
            f"expected_frozen_symbols bir frozenset olmalı, {type(expected_frozen_symbols).__name__} bulundu"
        )
    for member in expected_frozen_symbols:
        if not isinstance(member, str) or not member:
            raise EvidenceIntegrityError(
                f"expected_frozen_symbols boş olmayan string olmayan bir üye içeriyor: {member!r}"
            )

    if not isinstance(observed_symbol, str) or not observed_symbol:
        raise EvidenceIntegrityError(f"observed_symbol boş olmayan bir string olmalı: {observed_symbol!r}")

    if observed_symbol in expected_frozen_symbols:
        return IdentityGateEvaluation(result=GateCheckResult.PASS, reason_code=None)
    return IdentityGateEvaluation(result=GateCheckResult.FAIL, reason_code=SYMBOL_NOT_IN_FROZEN_UNIVERSE)
