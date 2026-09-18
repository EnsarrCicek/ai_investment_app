"""HATA 13D — Technical V1 attempt-2 karar/yürütme sarmalayıcısı.

Bu modül, attempt #2'nin GEREKİP GEREKMEDİĞİNE dair KENDİ kararını
ÜRETMEZ -- `app.research.final_evaluation_selector`'ın ZATEN kilitlenmiş,
saf, GCS'siz tarihsel önyargı (`_qualifying_at_attempt2_decision`) ve
sınıflandırma (`_attempt2_requirement_state`) yardımcılarını, ve attempt1
durumunu değerlendiren `_evaluate_attempt`'i DOĞRUDAN import eder (section
6/25: "Reuse the exact already-built historical predicate... Selector
remains single source of truth" -- İKİNCİ bir politika/predicate KOPYASI
YAZILMAZ). Bu üç fonksiyonun "private" (alt çizgili) olması BİLİNÇLİ bir
tasarım kararının SONUCUDUR, bir gözden kaçırma DEĞİLDİR -- alternatif
(tam `select_final_evaluation()`'ı 09:00 kararı için çağırmak) YANLIŞ
olurdu, çünkü o fonksiyon AYRICA `_qualifying_for_final_selection()`
üzerinden CANLI GCS doğrulaması da yapar; bu, HATA 13D section 7'nin
KİLİTLİ kuralını ("09:00 attempt2 requirement predicate is based on
attempt claim/result metadata, NOT GCS evidence verification") İHLAL
ederdi -- geçici bir object-store arızası, attempt2'nin dispatch
edilip edilmeyeceğini YANLIŞLIKLA etkileyebilirdi.

Attempt-2'nin execution KENDİSİ (provider fetch/normalizasyon/evidence-
capture/kimlik-kapıları/exclusion/publish) TAMAMEN HATA 13C'nin
`TechnicalV1AttemptExecutionService`'ine DELEGE edilir -- burada İKİNCİ
bir bilimsel implementasyon KOPYASI YOKTUR. Claim-once/no-takeover
semantiği de TAMAMEN 13C'den (ve onun ALTINDAKİ, değiştirilmemiş
`TechnicalV1AttemptRepository.claim_attempt()`'ten) miras alınır -- bu
sarmalayıcı KENDİ başına "attempt2 zaten claim edildi mi" kontrolü
YAPMAZ, tekrarlı bir çağrının GÜVENLİ olmasını 13C'nin kendi ALREADY_
CLAIMED kısa-devresine BIRAKIR (section 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.research.evidence_identity import compute_attempt_id
from app.research.final_evaluation_models import AttemptRequirementState, FinalizationContext
from app.research.final_evaluation_selector import (
    _attempt2_requirement_state,
    _evaluate_attempt,
    _qualifying_at_attempt2_decision,
)
from app.research.technical_v1_attempt_execution import AttemptExecutionReport, TechnicalV1AttemptExecutionService
from app.research.technical_v1_attempt_reads import read_persisted_attempt_claim, read_persisted_attempt_result


class Attempt2Outcome(str, Enum):
    """`AttemptRequirementState`'in (`REQUIRED` HARİÇ -- o, ya `WINDOW_
    CLOSED` ya `DISPATCHED`'e dönüşür) BİREBİR karşılığı, artı iki saf
    zamanlama durumu. Kapalı küme -- section 10/11/12'nin gerektirdiği
    TÜM operasyonel çıktılar burada temsil edilir."""

    NOT_YET_DUE = "NOT_YET_DUE"
    NOT_REQUIRED_FIRST_VALID = "NOT_REQUIRED_FIRST_VALID"
    INDETERMINATE_PROVENANCE = "INDETERMINATE_PROVENANCE"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    DISPATCHED = "DISPATCHED"


@dataclass(frozen=True)
class Attempt2Report:
    outcome: Attempt2Outcome
    execution_report: AttemptExecutionReport | None = None


class TechnicalV1Attempt2Orchestrator:
    """HATA 13D section 8. TÜM bağımlılıklar constructor'da AÇIKÇA enjekte
    edilir -- `db`, `technical_v1_attempt_claims`/`technical_v1_attempt_
    results` koleksiyonlarını (13C'nin `TechnicalV1AttemptRepository`'siyle
    AYNI Firestore projesi/koleksiyonları) okumak için kullanılır; bu
    sarmalayıcı KENDİSİ hiçbir zaman bu koleksiyonlara YAZMAZ (yalnızca
    OKUR) -- yazma, TAMAMEN 13C'nin `TechnicalV1AttemptExecutionService`'i
    üzerinden, `TechnicalV1AttemptRepository.claim_attempt()`/`publish_
    result()` aracılığıyla gerçekleşir."""

    def __init__(self, *, db, attempt_execution_service: TechnicalV1AttemptExecutionService) -> None:
        self._db = db
        self._attempt_execution_service = attempt_execution_service

    def run_attempt2_if_required(
        self,
        context: FinalizationContext,
        *,
        activation_lock_id: str,
        now: datetime,
    ) -> Attempt2Report:
        """HATA 13D section 8-13. `context`, çağıran tarafından ZATEN
        inşa edilmiş (dolayısıyla `attempt2_decision_time_utc`/`formal_
        cutoff_utc`'yi ZATEN taşıyan) bir `FinalizationContext`'tir --
        bu sarmalayıcı kendi zaman-hesaplama kopyasını YAPMAZ, TEK bir
        yerde (context inşası) hesaplanan bu iki zaman damgasını doğrudan
        okur (section 12: "Use existing schedule/time helpers")."""
        if now < context.attempt2_decision_time_utc:
            # section 10: 09:00'dan ÖNCE -- claim YOK, provider YOK.
            return Attempt2Report(outcome=Attempt2Outcome.NOT_YET_DUE)

        attempt1_id = compute_attempt_id(context.evaluation_id, 1)
        attempt1_claim = read_persisted_attempt_claim(self._db, 1, attempt1_id)
        attempt1_result = read_persisted_attempt_result(self._db, 1, attempt1_id)
        attempt1_evaluation = _evaluate_attempt(1, context, attempt1_claim, attempt1_result)

        attempt1_create_time = attempt1_result.create_time if attempt1_result is not None else None
        qualifying_at_decision = _qualifying_at_attempt2_decision(attempt1_evaluation, context, attempt1_create_time)
        requirement = _attempt2_requirement_state(attempt1_evaluation, qualifying_at_decision)

        if requirement == AttemptRequirementState.NOT_REQUIRED_FIRST_VALID:
            return Attempt2Report(outcome=Attempt2Outcome.NOT_REQUIRED_FIRST_VALID)
        if requirement == AttemptRequirementState.INDETERMINATE_PROVENANCE:
            # attempt1 provenance/integrity açısından güvenilmez -- bu bir
            # zamanlama/retry sorunu DEĞİLDİR, otomatik bir attempt2
            # dispatch'i İLE "çözülmez" (section 5: "not an unconditional
            # retry"). Nihai muhasebe finalizasyon seviyesindedir.
            return Attempt2Report(outcome=Attempt2Outcome.INDETERMINATE_PROVENANCE)

        # requirement == REQUIRED
        if now >= context.formal_cutoff_utc:
            # section 11/12: 09:45'TE VEYA SONRASINDA YENİ bir eligible
            # attempt2 dispatch edilmez -- claim YARATILMAZ.
            return Attempt2Report(outcome=Attempt2Outcome.WINDOW_CLOSED)

        execution_report = self._attempt_execution_service.execute_attempt(
            activation_lock_id=activation_lock_id,
            protocol_version=context.protocol_version,
            T_session_date=context.T_session_date,
            symbol=context.symbol,
            attempt_number=2,
            now=now,
        )
        return Attempt2Report(outcome=Attempt2Outcome.DISPATCHED, execution_report=execution_report)
