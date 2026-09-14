"""HATA 12N2B2 — Technical V1 immutable final-evaluation repository'si.

Koleksiyon: `technical_v1_evaluations/{evaluation_id}` -- create-only,
KALICI bilimsel kanıt olarak. Bu repository:

  - SEÇİM MANTIĞI ÇALIŞTIRMAZ (`select_final_evaluation()`'ı hiç
    import/çağırmaz) -- yalnızca ZATEN ÜRETİLMİŞ bir `FinalEvaluation`
    nesnesini KALICI HALE GETİRİR.
  - `EvidenceObjectStore`/`TechnicalV1AttemptRepository`'yi hiç
    import/çağırmaz -- GCS'e/attempt claim-result koleksiyonlarına
    HİÇ DOKUNMAZ.
  - `FinalEvaluation.to_document_fields()`'i TEK, kanonik doküman
    temsili olarak kullanır -- final şemayı BURADA BAĞIMSIZ OLARAK
    YENİDEN İNŞA ETMEZ.

Kilitli create-only sözleşme (HATA 12N2A'daki `TechnicalV1AttemptRepository`
ile AYNI desen, `AlreadyExists` precondition'ı):
  - `.create()` yalnız BİR KEZ, ilk yaratımda kullanılır.
  - `set()`/`update()`/`add()`/`delete()` normal akışta HİÇ KULLANILMAZ.
  - Var olan bir doküman bulunursa: KÖRÜKÖRÜNE idempotent başarı
    İLAN EDİLMEZ -- ÖNCE var olan dokümanın HAM içerik-hash'i yeniden
    hesaplanıp doğrulanır (nesne ADI/saklanan hash string'i TEK BAŞINA
    ASLA güvenilmez), SONRA adayla karşılaştırılır. Aynıysa
    `IDEMPOTENT_REUSE`, farklıysa `ProvenanceConflictError` (sert hata,
    ASLA en-son-kazanır).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client
from app.research.evidence_identity import compute_evaluation_id
from app.research.evidence_models import ProvenanceConflictError, validate_sha256_hex
from app.research.final_evaluation_models import FinalEvaluation

COLLECTION = "technical_v1_evaluations"


class FinalEvaluationOutcome(str, Enum):
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class PersistedFinalEvaluation:
    """HATA 12N2B2 section 11: Firestore sunucu metadata'sını (`create_
    time`), final kaydın İÇERİĞİNE hiç kopyalamadan taşıyan salt-okunur
    zarf. `create_time` ASLA `FinalEvaluation.to_document_fields()`'e
    veya `record_content_sha256`'ya girmez -- bu SADECE bir okuma-zamanı
    gözlem değeridir."""

    evaluation: FinalEvaluation
    create_time: datetime


def _verify_and_reconstruct(expected_evaluation_id: str, raw_fields: dict) -> FinalEvaluation:
    """HATA 12N2B2 section 7/12/22/23: TEK, paylaşılan doğrulama+yeniden-
    kuruluş boru hattı -- hem `create()`'in var-olan-doküman karşılaştırma
    yolu HEM DE `get_verified()` BUNU çağırır, aynı mantık İKİ AYRI yerde
    YAZILMAZ.

    Sıra (hiçbiri atlanmaz):
      1. saklanan `record_content_sha256` kanonik (64 küçük-harf hex) mi?
      2. TÜM diğer alanlardan (kendisi HARİÇ) yeniden hesaplanan hash,
         saklanan değerle EŞLEŞİYOR mu? (nesne ADI/saklanan string TEK
         BAŞINA ASLA güvenilmez; beklenmeyen bir FAZLA alan bile bu
         karşılaştırmayı BAŞARISIZ KILAR -- section 9.)
      3. semantik yeniden kuruluş (`FinalEvaluation.from_document_
         fields()`) başarılı mı? (hash-tutarlı ama enum/şema açısından
         imkânsız bir doküman burada YAKALANIR.)
      4. yeniden kurulan kaydın KENDİ kimlik alanları (evaluation_id/
         protocol_version/T_session_date/symbol), hem bağımsız olarak
         yeniden hesaplanan `compute_evaluation_id(...)` İLE hem de
         BEKLENEN (istenen) doküman ID'si İLE eşleşiyor mu?

    Herhangi bir adım başarısız olursa `ProvenanceConflictError` -- ham
    bir `ValueError`/`KeyError` normal uygulama akışına SIZMAZ.
    """
    stored_hash = raw_fields.get("record_content_sha256")
    try:
        validate_sha256_hex(stored_hash)
    except Exception as exc:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: saklanan record_content_sha256 "
            f"kanonik (64 küçük-harf hex) formatında değil: {stored_hash!r}"
        ) from exc

    content_fields = {key: value for key, value in raw_fields.items() if key != "record_content_sha256"}

    from app.research.canonical_hash import content_sha256

    try:
        recomputed_hash = content_sha256(content_fields)
    except (TypeError, ValueError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: içerik alanları kanonik olarak "
            f"hash'lenemedi (JSON-güvenli olmayan bir değer içeriyor olabilir): {exc}"
        ) from exc
    if recomputed_hash != stored_hash:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: yeniden hesaplanan içerik hash'i "
            f"({recomputed_hash}) saklanan değerle ({stored_hash}) eşleşmiyor -- doküman içeriği "
            f"kendi saklanan hash'iyle TUTARSIZ (tamper/bozulma şüphesi)."
        )

    try:
        evaluation = FinalEvaluation.from_document_fields(content_fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: içerik hash'i geçerli ama doküman "
            f"semantik olarak FinalEvaluation şemasıyla tutarsız: {exc}"
        ) from exc

    recomputed_evaluation_id = compute_evaluation_id(
        evaluation.protocol_version, evaluation.T_session_date, evaluation.symbol
    )
    if evaluation.evaluation_id != recomputed_evaluation_id:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: saklanan evaluation_id "
            f"({evaluation.evaluation_id}) kendi protocol_version/T_session_date/symbol alanlarından "
            f"bağımsız olarak yeniden hesaplanan ({recomputed_evaluation_id}) ile eşleşmiyor."
        )
    if evaluation.evaluation_id != expected_evaluation_id:
        raise ProvenanceConflictError(
            f"technical_v1_evaluations/{expected_evaluation_id}: dokümanın KENDİ içeriğindeki "
            f"evaluation_id ({evaluation.evaluation_id}) doküman ID'sinden ({expected_evaluation_id}) "
            f"FARKLI -- yanlış/wrong-wiring bir kayıt."
        )

    return evaluation


class TechnicalV1EvaluationRepository:
    def __init__(self, db=None):
        # HATA 12N1/12N2A ile AYNI desen: `db` enjekte EDİLMEZSE gerçek
        # Firestore client'ı yalnızca BU ANDA (modül import anında DEĞİL)
        # kurulur -- testler `db` için minimal, sözleşme-uyumlu bir sahte
        # vererek gerçek ağ/ADC/proje erişimi OLMADAN bu sınıfı egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def create(self, evaluation: FinalEvaluation) -> FinalEvaluationOutcome:
        """HATA 12N2B2 section 3/4/5/6/8: adayın KENDİ kimliği önce
        bağımsız olarak doğrulanır, sonra `DocumentReference.create()`
        ile create-only yazma denenir. `AlreadyExists` durumunda var olan
        doküman KÖRÜKÖRÜNE idempotent SAYILMAZ -- `_verify_and_
        reconstruct()` ile TAM doğrulanıp candidate'in KENDİ (her zaman
        doğru, çünkü türetilmiş bir property olan) hash'iyle karşılaştırılır.
        """
        expected_evaluation_id = compute_evaluation_id(
            evaluation.protocol_version, evaluation.T_session_date, evaluation.symbol
        )
        if evaluation.evaluation_id != expected_evaluation_id:
            raise ProvenanceConflictError(
                f"Sağlanan FinalEvaluation.evaluation_id ({evaluation.evaluation_id}) kendi "
                f"protocol_version/T_session_date/symbol alanlarından bağımsız olarak yeniden "
                f"hesaplanan ({expected_evaluation_id}) ile eşleşmiyor -- persist edilmedi."
            )

        doc_ref = self._db.collection(COLLECTION).document(evaluation.evaluation_id)
        candidate_fields = evaluation.to_document_fields()
        # `record_content_sha256` her zaman türetilmiş bir property'dir --
        # adayın KENDİ hash'i ayrıca "doğrulanmaya" gerek duymaz, tanım
        # gereği doğrudur (section 8).
        candidate_hash = candidate_fields["record_content_sha256"]

        try:
            doc_ref.create(candidate_fields)
            return FinalEvaluationOutcome.CREATED
        except AlreadyExists:
            existing_snapshot = doc_ref.get()
            if not existing_snapshot.exists:
                raise ProvenanceConflictError(
                    f"technical_v1_evaluations/{evaluation.evaluation_id}: create() AlreadyExists "
                    f"fırlattı ama hemen ardından yapılan okuma dokümanı bulamadı -- beklenmeyen "
                    f"depolama-katmanı tutarsızlığı."
                )
            existing_evaluation = _verify_and_reconstruct(evaluation.evaluation_id, existing_snapshot.to_dict())
            existing_hash = existing_evaluation.record_content_sha256
            if existing_hash == candidate_hash:
                return FinalEvaluationOutcome.IDEMPOTENT_REUSE
            raise ProvenanceConflictError(
                f"technical_v1_evaluations/{evaluation.evaluation_id}: VAR OLAN kayıt FARKLI "
                f"içerikle tekrar persist edilmeye çalışıldı (existing={existing_hash}, "
                f"candidate={candidate_hash}) -- en-son-kazanır UYGULANMAZ, sert hata."
            )

    def get_verified(self, evaluation_id: str) -> PersistedFinalEvaluation | None:
        """HATA 12N2B2 section 12/14: ham doküman ÖNCE tam olarak
        doğrulanır (bkz. `_verify_and_reconstruct`), yalnızca ONDAN SONRA
        güvenilen bir `FinalEvaluation` + Firestore `create_time`
        metadata'sı içeren bir zarf döner. Doğrulanmamış/güvenilmeyen bir
        `FinalEvaluation` ASLA doğrudan DÖNDÜRÜLMEZ."""
        doc = self._db.collection(COLLECTION).document(evaluation_id).get()
        if not doc.exists:
            return None
        evaluation = _verify_and_reconstruct(evaluation_id, doc.to_dict())
        return PersistedFinalEvaluation(evaluation=evaluation, create_time=doc.create_time)
