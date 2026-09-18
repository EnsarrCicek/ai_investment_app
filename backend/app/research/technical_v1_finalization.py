"""HATA 13D — Technical V1 tek-evaluation ({protocol_version,
T_session_date, symbol}) finalizasyon orkestrasyonu.

Bu modül HİÇBİR seçim/doğrulama MANTIĞI İÇERMEZ -- TAMAMEN mevcut,
KİLİTLİ `select_final_evaluation()` seçicisine ve `TechnicalV1Evaluation
Repository`'nin KENDİ create-only/idempotent-reuse/provenance-conflict
yarış-koşulu ele alma mantığına DELEGE eder (section 14/25/32/33 --
"No selector rewrite", "Selector remains single source of truth").

KRİTİK, KASITLI TASARIM (section 21): `select_final_evaluation()`
KENDİSİ, geçici/bilinmeyen bir `EvidenceObjectStore` hatasıyla
karşılaşırsa `FinalizationRetryableError` fırlatır VE bu fonksiyon
TAMAMEN durur (attempt1'in kanıt doğrulaması geçici olarak başarısız
olursa, attempt2'ye ASLA "sessizce" geçilmez -- bkz. o modülün KENDİ
`_qualifying_for_final_selection()` docstring'i, section 30). Bu modül bu
istisnayı KASITLI OLARAK YAKALAMAZ -- doğrudan çağırana YAYILIR, "kardeş
adaya sessiz geçiş YOK" kuralını BİR KEZ DAHA (bu sarmalama katmanında)
YENİDEN UYGULAMAZ/BOZMAZ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.repositories.technical_v1_evaluation_repository import FinalEvaluationOutcome, TechnicalV1EvaluationRepository
from app.research.evidence_identity import compute_attempt_id
from app.research.evidence_object_store import EvidenceObjectStore
from app.research.final_evaluation_models import FinalEvaluation, FinalizationContext
from app.research.final_evaluation_selector import select_final_evaluation
from app.research.technical_v1_attempt_reads import read_persisted_attempt_claim, read_persisted_attempt_result


class FinalizationOutcome(str, Enum):
    """HATA 13D section 37: yalnızca OPERASYONEL sonuç -- bilimsel durum
    (`CaptureStatus`/`EvaluationIntegrityStatus`/`result_classification`)
    BURADA ASLA KODLANMAZ, her zaman `FinalEvaluation`'ın KENDİ içindedir."""

    NOT_YET_FINALIZABLE = "NOT_YET_FINALIZABLE"
    CREATED = "CREATED"
    IDEMPOTENT_REUSE = "IDEMPOTENT_REUSE"


@dataclass(frozen=True)
class FinalizationReport:
    outcome: FinalizationOutcome
    evaluation: FinalEvaluation | None = None


class TechnicalV1Finalizer:
    """HATA 13D section 14. `db`, attempt claim/result koleksiyonlarını
    OKUMAK için (13C'nin/attempt2 sarmalayıcısının YAZDIĞI AYNI Firestore
    projesi) kullanılır -- bu sınıf o koleksiyonlara ASLA YAZMAZ."""

    def __init__(
        self,
        *,
        db,
        evidence_store: EvidenceObjectStore,
        evaluation_repo: TechnicalV1EvaluationRepository,
    ) -> None:
        self._db = db
        self._evidence_store = evidence_store
        self._evaluation_repo = evaluation_repo

    def finalize(self, context: FinalizationContext, *, now: datetime) -> FinalizationReport:
        """HATA 13D section 16/17: `now`, yalnızca formal cutoff'a karşı
        bir OPERASYONEL "ne zaman çağrıldı" kontrolüdür -- bilimsel sonuç,
        HER ZAMAN `context.formal_cutoff_utc`'ye göre değerlendirilen
        claim/result `create_time`'larından türetilir (bkz. `select_final_
        evaluation()`'ın kendisi); finalizer fiziksel olarak çok daha SONRA
        (operasyonel varsayılan 10:15 ya da daha geç) çalışabilir, sonuç
        DEĞİŞMEZ."""
        if now < context.formal_cutoff_utc:
            return FinalizationReport(outcome=FinalizationOutcome.NOT_YET_FINALIZABLE)

        attempt1_id = compute_attempt_id(context.evaluation_id, 1)
        attempt2_id = compute_attempt_id(context.evaluation_id, 2)

        attempt1_claim = read_persisted_attempt_claim(self._db, 1, attempt1_id)
        attempt1_result = read_persisted_attempt_result(self._db, 1, attempt1_id)
        attempt2_claim = read_persisted_attempt_claim(self._db, 2, attempt2_id)
        attempt2_result = read_persisted_attempt_result(self._db, 2, attempt2_id)

        # `FinalizationRetryableError` KASITLI OLARAK burada YAKALANMAZ --
        # bkz. modül docstring'i.
        evaluation = select_final_evaluation(
            context, attempt1_claim, attempt1_result, attempt2_claim, attempt2_result, self._evidence_store
        )

        create_outcome = self._evaluation_repo.create(evaluation)
        if create_outcome == FinalEvaluationOutcome.CREATED:
            return FinalizationReport(outcome=FinalizationOutcome.CREATED, evaluation=evaluation)
        return FinalizationReport(outcome=FinalizationOutcome.IDEMPOTENT_REUSE, evaluation=evaluation)
