"""Technical V1 PRE-CLAIM yetkilendirme -- SAF, I/O'suz birincil kontrol
katmanı. HATA 13B section 20.

Bu modül HİÇBİR I/O yapmaz (Firestore/dosya sistemi/ortam değişkeni/ağ/
provider erişimi YOK) -- yalnızca ZATEN DOĞRULANMIŞ üç nesneyi
(`TechnicalV1ActivationLock`, `TechnicalV1ActivationEvent | None`,
`TrustedTechnicalV1Protocol`) ve bir sembolü alıp saf bir
`PreClaimAuthorization` üretir.

KAVRAMSAL KONUM (HATA 13A section 5/6, section 21 burada AÇIKÇA
tekrarlanır): bu, bir `AttemptClaim` YARATILMADAN ÖNCE yanıtlanması
gereken sorudur -- "bu (activation_lock × symbol) çifti için GERÇEKTEN bir
claim oluşturulmaya YETKİLİ MİYİZ?" `app.research.identity_gates`'teki dört
kimlik-kapısından TAMAMEN AYRI bir katmandır (section 29): CONFIG/
METHODOLOGY/RUNTIME/post-claim UNIVERSE kapıları burada TEKRARLANMAZ,
onlar HATA 13C'nin (henüz yazılmamış attempt-execution servisi)
sorumluluğudur. Bu modül SADECE üç şeyi kurar:
  1. aktivasyon yetkilendirmesi (bir olay var mı, o olay TAM OLARAK bu
     kilidi mi yetkilendiriyor),
  2. kilit × doğrulanmış protokol kimlik ilişkisi,
  3. pre-claim dondurulmuş-evren üyeliği.

KİLİTLİ SINIR (HATA 13B section 3, section 21): bu modülün var olması
"aktivasyon olayı olmadan claim yok" kuralını SİSTEM GENELİNDE
UYGULAMAZ -- `claim_attempt()`'e HİÇBİR guard TAKILMADI (bkz.
`technical_v1_attempt_repository.py`, DEĞİŞTİRİLMEDİ). Bu kuralı
GERÇEKTEN uygulayacak olan, `claim_attempt()`'ten HEMEN ÖNCE
`authorize_pre_claim()`'i çağıracak olan HATA 13C'dir.

`PreClaimStatus`, `AttemptResultClassification`/`native_reason_code` İLE
ASLA KARIŞTIRILMAZ (section 21) -- bu PRE-CLAIM kontrol akışıdır, henüz
hiçbir `AttemptResult` (hatta hiçbir `AttemptClaim`) YOKTUR."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.research.activation_event import TechnicalV1ActivationEvent
from app.research.activation_lock import TechnicalV1ActivationLock
from app.research.evidence_models import EvidenceIntegrityError, ProvenanceConflictError
from app.research.technical_v1_protocol import TrustedTechnicalV1Protocol


class PreClaimStatus(str, Enum):
    """Kapalı (closed) küme -- HATA 13B section 21. Üçünün DIŞINDA hiçbir
    durum YOKTUR; malformed/programlama hatası girdisi bir durum DEĞİL,
    bir exception'dır (section 26/44)."""

    AUTHORIZED = "AUTHORIZED"
    PRE_ACTIVATION = "PRE_ACTIVATION"
    OUTSIDE_FROZEN_UNIVERSE = "OUTSIDE_FROZEN_UNIVERSE"


@dataclass(frozen=True)
class PreClaimAuthorization:
    """Tek bir pre-claim yetkilendirme kararının SAF sonucu."""

    status: PreClaimStatus


def authorize_pre_claim(
    *,
    activation_lock: TechnicalV1ActivationLock,
    activation_event: TechnicalV1ActivationEvent | None,
    trusted_protocol: TrustedTechnicalV1Protocol,
    symbol: str,
) -> PreClaimAuthorization:
    """HATA 13B section 20-28: pre-claim yetkilendirme kontrol sırası.

    Sıra (hiçbiri atlanmaz, section 44'ün gerektirdiği gibi malformed
    programlama girdisi HER ZAMAN önce, sessizce bir domain durumuna
    dönüştürülmeden reddedilir):
      1. `symbol` biçimsel olarak geçerli mi (non-empty str) -- DEĞİLSE
         `EvidenceIntegrityError` (section 26/44, ASLA
         `OUTSIDE_FROZEN_UNIVERSE`'e dönüştürülmez).
      2. `activation_lock`, `trusted_protocol` İLE aynı protokolü mü
         tanımlıyor (`protocol_version` VE `protocol_sha256` ikisi de) --
         DEĞİLSE `ProvenanceConflictError` (section 24, olay var/yok
         FARK ETMEZ -- bu, olay-öncesi bile kontrol edilmesi gereken bir
         iç tutarlılık kontrolüdür).
      3. `activation_event is None` -- EVETSE `PRE_ACTIVATION` (section
         22, sıradan/beklenen bir durum, exception DEĞİL).
      4. olay TAM OLARAK bu kilidi mi yetkilendiriyor (`protocol_version`
         VE `activation_lock_id` ikisi de eşleşmeli) -- DEĞİLSE
         `ProvenanceConflictError` (section 23 -- zaten doğrulanmış iki
         nesne arasındaki bir uyuşmazlık ASLA sıradan `PRE_ACTIVATION`
         sayılmaz).
      5. `symbol`, `trusted_protocol.frozen_symbols`'ın TAM (normalizasyonsuz)
         bir üyesi mi -- DEĞİLSE `OUTSIDE_FROZEN_UNIVERSE` (section 27).
      6. hepsi geçerse `AUTHORIZED` (section 28).

    Bu fonksiyon HİÇBİR repository/Firestore/provider/AssetRepository/
    `claim_attempt()` çağrısı YAPMAZ (section 20/45) ve CONFIG/METHODOLOGY/
    RUNTIME/post-claim-UNIVERSE kimlik-kapılarını TEKRARLAMAZ (section 29)."""
    if not isinstance(symbol, str) or not symbol:
        raise EvidenceIntegrityError(f"symbol boş olmayan bir string olmalı: {symbol!r}")

    if activation_lock.protocol_version != trusted_protocol.protocol_version:
        raise ProvenanceConflictError(
            "activation_lock.protocol_version "
            f"({activation_lock.protocol_version!r}) trusted_protocol.protocol_version "
            f"({trusted_protocol.protocol_version!r}) ile eşleşmiyor -- zaten doğrulanmış iki nesne "
            "arasında bir tutarsızlık."
        )
    if activation_lock.protocol_sha256 != trusted_protocol.protocol_sha256:
        raise ProvenanceConflictError(
            "activation_lock.protocol_sha256 "
            f"({activation_lock.protocol_sha256!r}) trusted_protocol.protocol_sha256 "
            f"({trusted_protocol.protocol_sha256!r}) ile eşleşmiyor -- zaten doğrulanmış iki nesne "
            "arasında bir tutarsızlık."
        )

    if activation_event is None:
        return PreClaimAuthorization(status=PreClaimStatus.PRE_ACTIVATION)

    if activation_event.protocol_version != activation_lock.protocol_version:
        raise ProvenanceConflictError(
            "activation_event.protocol_version "
            f"({activation_event.protocol_version!r}) activation_lock.protocol_version "
            f"({activation_lock.protocol_version!r}) ile eşleşmiyor -- zaten doğrulanmış iki nesne "
            "arasında bir tutarsızlık."
        )
    if activation_event.activation_lock_id != activation_lock.activation_lock_id:
        raise ProvenanceConflictError(
            "activation_event.activation_lock_id "
            f"({activation_event.activation_lock_id!r}) tam olarak yetkilendirilmesi istenen "
            f"activation_lock.activation_lock_id ({activation_lock.activation_lock_id!r}) ile "
            "eşleşmiyor -- bu olay BAŞKA bir kilidi yetkilendiriyor."
        )

    if symbol not in trusted_protocol.frozen_symbols:
        return PreClaimAuthorization(status=PreClaimStatus.OUTSIDE_FROZEN_UNIVERSE)

    return PreClaimAuthorization(status=PreClaimStatus.AUTHORIZED)
