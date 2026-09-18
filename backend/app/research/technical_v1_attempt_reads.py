"""HATA 13D — Technical V1 attempt claim/result HAM okuma yardımcıları.

Bu modül `TechnicalV1AttemptRepository`'yi DEĞİŞTİRMEZ/genişletmez -- onun
KENDİ export ettiği koleksiyon adı sabitlerini (`ATTEMPT_CLAIMS_COLLECTION`/
`ATTEMPT_RESULTS_COLLECTION`) kullanarak, `final_evaluation_selector.py`'nin
BEKLEDİĞİ TAM ŞEKİLDE HAM (doğrulanmamış) `PersistedAttemptClaim`/
`PersistedAttemptResultDocument` zarflarını üretir.

`TechnicalV1AttemptRepository.get_claim()`/`get_result()` (ZATEN
doğrulanmış, `AttemptClaim`/`AttemptResult` NESNESİ döner) BİLEREK
KULLANILMAZ -- seçicinin KENDİSİ (`select_final_evaluation()`) doğrulamayı
BAĞIMSIZ OLARAK, ham dict üzerinden yapmak üzere tasarlanmıştır (bkz.
`final_evaluation_models.py`, `PersistedAttemptClaim`/`PersistedAttempt
ResultDocument` docstring'leri) -- ÖNCEDEN doğrulanmış bir nesne vermek bu
tasarımı BOZAR (tampered/semantic-invalid bir doküman seçiciye HİÇ
ULAŞAMAZDI, çünkü `AttemptResult.__post_init__` zaten kendi kendine
fırlatırdı -- seçicinin KENDİ, bağımsız hash/semantic/identity doğrulama
zincirini asla ÇALIŞTIRAMAZDI)."""

from __future__ import annotations

from app.repositories.technical_v1_attempt_repository import ATTEMPT_CLAIMS_COLLECTION, ATTEMPT_RESULTS_COLLECTION
from app.research.final_evaluation_models import PersistedAttemptClaim, PersistedAttemptResultDocument


def read_persisted_attempt_claim(db, attempt_number: int, attempt_id: str) -> PersistedAttemptClaim | None:
    """Doküman yoksa `None` -- bu, `select_final_evaluation()`'ın kendisinin
    `ClaimPresence.MISSING` olarak ele alacağı GEÇERLİ, sıradan bir
    durumdur (exception DEĞİLDİR)."""
    doc = db.collection(ATTEMPT_CLAIMS_COLLECTION).document(attempt_id).get()
    if not doc.exists:
        return None
    return PersistedAttemptClaim(attempt_number=attempt_number, attempt_id=attempt_id, document_fields=doc.to_dict())


def read_persisted_attempt_result(db, attempt_number: int, attempt_id: str) -> PersistedAttemptResultDocument | None:
    """Doküman yoksa `None` -- `ResultState.NO_RESULT`'a karşılık gelen
    GEÇERLİ, sıradan bir durumdur."""
    doc = db.collection(ATTEMPT_RESULTS_COLLECTION).document(attempt_id).get()
    if not doc.exists:
        return None
    return PersistedAttemptResultDocument(
        attempt_number=attempt_number,
        attempt_id=attempt_id,
        document_fields=doc.to_dict(),
        create_time=doc.create_time,
    )
