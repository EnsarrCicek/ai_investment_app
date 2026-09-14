"""HATA 12N2A — Technical V1 immutable attempt-claim / attempt-result
repository'si (CLAIM-ONCE modeli: lease/heartbeat/takeover/generation
fencing YOK, bkz. HATA 12N2-A audit raporu).

İki koleksiyon, İKİSİ DE create-only:
  - `technical_v1_attempt_claims/{attempt_id}` -- "bir worker'a bu mantıksal
    denemeyi yürütmesi için izin verildi" (SONSUZA KADAR değişmez, ASLA
    `set()`/`update()` edilmez).
  - `technical_v1_attempt_results/{attempt_id}` -- worker'ın ürettiği
    terminal, değişmez kanıt (yalnızca karşılık gelen claim VARSA
    yayınlanabilir).

`claim var + result yok` KALICI, GEÇERLİ bir depolama durumudur (N2A'da
hiçbir temizlik/timeout süreci YOKTUR -- bkz. HATA 12N2-A section 15/22).
"""

from __future__ import annotations

from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from app.core.firebase import get_firestore_client
from app.research.attempt_models import (
    AttemptClaim,
    AttemptClaimMissingError,
    AttemptResult,
    ClaimOutcome,
    PublishOutcome,
)
from app.research.evidence_models import ProvenanceConflictError

ATTEMPT_CLAIMS_COLLECTION = "technical_v1_attempt_claims"
ATTEMPT_RESULTS_COLLECTION = "technical_v1_attempt_results"


class TechnicalV1AttemptRepository:
    def __init__(self, db=None):
        # HATA 12N1'in `GCSEvidenceObjectStore` deseniyle AYNI: `db`
        # enjekte EDİLMEZSE gerçek Firestore client'ı yalnızca BU ANDA
        # (modül import anında DEĞİL) kurulur -- testler `db` için minimal,
        # sözleşme-uyumlu bir sahte vererek gerçek ağ/ADC/proje erişimi
        # OLMADAN bu sınıfı egzersiz eder.
        self._db = db if db is not None else get_firestore_client()

    def claim_attempt(self, claim: AttemptClaim) -> ClaimOutcome:
        """Atomik "kontrol et VE claim et" -- `DocumentReference.create()`'ın
        precondition'ı (doküman zaten varsa `AlreadyExists`) ile. Duplicate
        delivery normal, BEKLENEN bir durumdur (istisna DEĞİL, `ClaimOutcome.
        ALREADY_CLAIMED` döner) -- çağıran bunu görünce provider fetch/
        benchmark fetch/engine compute/GCS upload'ın HİÇBİRİNİ YAPMAMALIDIR.
        """
        doc_ref = self._db.collection(ATTEMPT_CLAIMS_COLLECTION).document(claim.attempt_id)
        try:
            doc_ref.create(claim.to_document_fields())
            return ClaimOutcome.CLAIMED
        except AlreadyExists:
            existing_snapshot = doc_ref.get()
            existing_data = existing_snapshot.to_dict() if existing_snapshot.exists else None
            expected_identity = claim.identity_fields()
            existing_identity = (
                {key: existing_data.get(key) for key in expected_identity} if existing_data is not None else None
            )
            if existing_identity == expected_identity:
                # HATA 12N2A section 9: `claimed_by_runtime` KASITLI OLARAK
                # bu karşılaştırmanın DIŞINDA -- ilk claimant sonsuza kadar
                # sahiptir, farklı bir runtime'ın aynı attempt_id'yi
                # denemesi normal bir redelivery'dir.
                return ClaimOutcome.ALREADY_CLAIMED
            raise ProvenanceConflictError(
                f"Aynı attempt_id ({claim.attempt_id}) altında var olan claim'in kimlik alanları "
                f"beklenenle uyuşmuyor -- bozuk/yanlış-wiring bir kayıt (normal redelivery DEĞİL)."
            )

    def publish_result(self, result: AttemptResult) -> PublishOutcome:
        """CLAIM-ONCE modelinde generation/token fencing GEREKMEZ (sahiplik
        ASLA el değiştirmez) -- yayınlama transaction'ı yalnızca şunu
        doğrular: (1) karşılık gelen claim VAR, (2) claim'in kimliği bu
        result'ınkiyle EŞLEŞİYOR, (3) aynı attempt_id için ÇAKIŞAN bir
        result YOK. Claim dokümanı bu işlemde ASLA MUTATE EDİLMEZ."""
        claim_ref = self._db.collection(ATTEMPT_CLAIMS_COLLECTION).document(result.attempt_id)
        result_ref = self._db.collection(ATTEMPT_RESULTS_COLLECTION).document(result.attempt_id)
        transaction = self._db.transaction()

        @firestore.transactional
        def _publish(transaction) -> PublishOutcome:
            claim_snapshot = claim_ref.get(transaction=transaction)
            if not claim_snapshot.exists:
                raise AttemptClaimMissingError(
                    f"attempt_id={result.attempt_id} için karşılık gelen claim yok -- "
                    f"yürütme sözleşmesi ihlal edildi (önce claim, sonra iş, sonra publish)."
                )
            claim_data = claim_snapshot.to_dict()
            result_identity = result.identity_fields()
            claim_identity = {key: claim_data.get(key) for key in result_identity}
            if claim_identity != result_identity:
                raise ProvenanceConflictError(
                    f"attempt_id={result.attempt_id} için claim kimliği, publish edilmek istenen "
                    f"result'ın kimliğiyle uyuşmuyor -- bozuk/yanlış-wiring bir durum."
                )

            result_snapshot = result_ref.get(transaction=transaction)
            candidate_fields = result.to_document_fields()

            if result_snapshot.exists:
                existing_data = result_snapshot.to_dict()
                existing_result = AttemptResult.from_document_fields(existing_data)
                existing_stored_hash = existing_data.get("attempt_result_content_sha256")
                if existing_result.content_sha256 != existing_stored_hash:
                    raise ProvenanceConflictError(
                        f"attempt_id={result.attempt_id} için VAR OLAN result dokümanının içeriği, "
                        f"kendi saklanan attempt_result_content_sha256'sıyla eşleşmiyor -- "
                        f"depolama-katmanı bozulması/tamper şüphesi."
                    )
                if existing_result.content_sha256 == candidate_fields["attempt_result_content_sha256"]:
                    return PublishOutcome.IDEMPOTENT_REUSE
                raise ProvenanceConflictError(
                    f"attempt_id={result.attempt_id} için VAR OLAN result, FARKLI içerikle tekrar "
                    f"publish edilmeye çalışıldı -- en-son-kazanır UYGULANMAZ, sert hata."
                )

            transaction.create(result_ref, candidate_fields)
            return PublishOutcome.CREATED

        return _publish(transaction)

    def get_claim(self, attempt_id: str) -> AttemptClaim | None:
        doc = self._db.collection(ATTEMPT_CLAIMS_COLLECTION).document(attempt_id).get()
        if not doc.exists:
            return None
        return AttemptClaim.from_document_fields(doc.to_dict())

    def get_result(self, attempt_id: str) -> AttemptResult | None:
        doc = self._db.collection(ATTEMPT_RESULTS_COLLECTION).document(attempt_id).get()
        if not doc.exists:
            return None
        return AttemptResult.from_document_fields(doc.to_dict())
