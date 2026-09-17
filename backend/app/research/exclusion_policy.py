"""Technical V1 bağımsız bilimsel exclusion politikası -- SAF karşılaştırma
katmanı. HATA 12N3C2-E2-A / E2-A1 / E2-B-R1 / HATA 12 final closure.

Bu modül HİÇBİR I/O yapmaz (Firestore/dosya sistemi/ortam değişkeni/ağ
erişimi YOK) -- yalnızca ZATEN üretilmiş bir bilimsel değeri (örn. bir
`TechnicalAnalysisEngine` çağrısından dönen `technical_score`) alıp saf bir
`ExclusionEvaluation` üretir. `app.research.identity_gates`'teki dört
kimlik-kapısı ile AYNI mimari desen (saf fonksiyon + değişmez sonuç tipi +
kararlı reason-code sabiti) -- ama KAVRAMSAL OLARAK FARKLI bir katman:
kimlik-kapıları "bu attempt yetkili bir bağlamda mı çalıştı" sorusunu
cevaplar, exclusion politikası "bu BİLİMSEL GÖZLEM, protokolün missing-data
politikası altında geçerli bir karşılaştırma gözlemi mi" sorusunu cevaplar
(bkz. `research/technical_v1_protocol_v1.json`'daki
`missing_data_policy.excluded_categories`).

KİLİTLİ kontrat (HATA 12N3C2-E2-A audit'inde doğrulanan):
  - `technical_score is None` ⟺ `TechnicalAnalysisEngine`'in 7 ham
    component'inin (RSI/MACD/trend/EMA-slope/Bollinger/Momentum/ROC)
    TAMAMI unavailable (finite değil) -- son derece nadir ama TAMAMEN
    meşru, matematiksel olarak iyi-tanımlı bir çıktı (bkz. `scoring.py::
    aggregate_available_components`). Bu ASLA bir exception/crash/internal
    defect DEĞİLDİR -- motor BAŞARIYLA tamamlanmış, iyi-biçimlendirilmiş
    bir `TechnicalAnalysis` nesnesi üretmiştir.
  - `technical_score = 0.0` GERÇEK, hesaplanmış, GEÇERLİ bir skordur --
    exclusion DEĞİLDİR. `None` ile `0.0` ASLA karıştırılmaz (truthiness
    kontrolü -- `if not technical_score` -- BU YÜZDEN KULLANILMAZ, çünkü
    Python'da `not 0.0 is True`).
  - `technical_score is None`, bir data-quality veto'sunun (MISSING_OHLCV/
    INVALID_OHLCV/INSUFFICIENT_HISTORY/vb.) SEMPTOMU DEĞİLDİR -- yapısal
    olarak MUTUALLY EXCLUSIVE'dir: `analyze_with_id()`'de bu vetolar
    `compute_technical_analysis()`'TEN ÖNCE, hiçbir exception-yakalama
    OLMADAN çalışır -- biri fırlarsa `TechnicalAnalysis` nesnesi HİÇ
    OLUŞMAZ. Bu yüzden bu modül HİÇBİR data-quality/continuity/provider
    durumu KABUL ETMEZ (section 9) -- yalnızca ZATEN başarıyla üretilmiş
    skor DEĞERİNİ alır, hiçbir üst-bağlam/precedence motoru GEREKMEZ
    (section 10).

KİLİTLİ kontrat (HATA 12N3C2-E2-B-R1 audit'inde doğrulanan --
`evaluate_history_validation_exclusion` için):
  - `history_validation_status == "LEADING_EDGE_UNVERIFIED"` ⟺ pre-roll
    gözlem bölgesi (`resolve_expected_start()`, bkz.
    `app.engines.technical.history_window`) sembolün `analysis_start`'tan
    ÖNCE zaten işlem gördüğüne dair kanıt BULAMADI -- bu ASLA otomatik
    "yeni halka arz" (PRE_LISTING) sayılmaz, yalnızca "kanıtlanamadı"
    anlamına gelir (bkz. `history_window.py` modül docstring'i).
  - `TECHNICAL_SCORE_NONE`'ın AKSİNE bu, TEK BAŞINA bir hard veto
    DEĞİLDİR -- `analyze_with_id()`, bu durumla BİRLİKTE geçerli, non-None
    bir `technical_score` üretebilir (HATA 12N3C2-E2-B-R1, "Design B"
    kararı). Bu yüzden bu exclusion, YALNIZCA zaten başarıyla üretilmiş
    bir `TechnicalAnalysis.history_validation_status` alanı üzerinde
    değerlendirilir -- ayrı bir "downstream veto oldu mu" kontrolüne
    GEREK YOKTUR, çünkü downstream bir hard veto (continuity/raw-OHLCV/
    insufficient-history) zaten `TechnicalAnalysis` nesnesinin hiç
    OLUŞMASINI ENGELLER (bkz. E2-B-R1 raporu, "Exact producer condition").
  - İKİ post-analysis exclusion (`TECHNICAL_SCORE_NONE` ve
    `LEADING_EDGE_UNVERIFIED`) yapısal olarak BAĞIMSIZDIR (biri skorun
    KENDİSİNE, diğeri girdi penceresinin KANIT durumuna bakar) -- nadiren
    ama GERÇEKTEN birlikte oluşabilirler (bkz.
    `resolve_post_analysis_exclusion()` ve onun testleri). Protokolün
    `missing_data_policy`'si bu ikisi arasında açık bir sıralama
    BELİRTMEZ (yalnızca ikisinin de `excluded_categories` altında ayrı
    satırlar olduğunu söyler) -- bu modül, KİLİTLİ, DOKÜMANTE EDİLMİŞ tek
    bir V1 kuralı seçer: `TECHNICAL_SCORE_NONE` önceliklidir, çünkü analiz
    çıktısının (skorun) kendisinin YOKLUĞU, girdi penceresinin kanıt
    durumuna dair bir provenance bayrağından DAHA DOĞRUDAN sonuç-
    geçersiz-kılıcıdır. Bu, YENİ bir multi-reason şema GENİŞLEMESİ
    GEREKTİRMEZ -- `AttemptResult.native_reason_code` TEK bir skaler
    `str | None` olarak KALIR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.engines.technical.history_window import HistoryValidationStatus
from app.research.attempt_reason_codes import LEADING_EDGE_UNVERIFIED, TECHNICAL_SCORE_NONE
from app.research.evidence_models import EvidenceIntegrityError


@dataclass(frozen=True)
class ExclusionEvaluation:
    """Tek bir bağımsız bilimsel exclusion kararının SAF sonucu.

    Kesin değişmez: `excluded=False` <=> `reason_code is None`;
    `excluded=True` <=> `reason_code`, bu exclusion kategorisi için TEK,
    kararlı sabit reason-code string'idir."""

    excluded: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        if self.excluded:
            if not isinstance(self.reason_code, str) or not self.reason_code:
                raise ValueError(
                    f"excluded=True iken boş olmayan bir reason_code string'i taşımalı: {self.reason_code!r}"
                )
        else:
            if self.reason_code is not None:
                raise ValueError(f"excluded=False iken reason_code taşıyamaz: {self.reason_code!r}")


def evaluate_technical_score_exclusion(technical_score: float | None) -> ExclusionEvaluation:
    """YALNIZCA `technical_score is None` bağımsız bilimsel exclusion
    kategorisini değerlendirir (protokolün `missing_data_policy.
    excluded_categories`'indeki "technical_score is None" satırı).

    Kesin sözleşme:
      - `technical_score is None` -> `excluded=True`, `reason_code=
        TECHNICAL_SCORE_NONE`.
      - Geçerli, finite bir sayı (0.0 DAHİL, pozitif/negatif herhangi bir
        değer) -> `excluded=False`, `reason_code=None`. `0.0` GERÇEK,
        ölçülmüş bir skordur -- ASLA `not technical_score` gibi bir
        truthiness kontrolüyle `None` ile KARIŞTIRILMAZ.
      - `NaN`/`+inf`/`-inf`/`bool`/sayısal-olmayan bir nesne: bunlar
        GEÇERLİ bir bilimsel "None" gözlemi DEĞİLDİR -- kaba bir
        programlama/domain girdi hatasıdır (section 8), çünkü üretim
        motorunun KENDİ aggregation contract'ı (`aggregate_available_
        components`) yalnızca `None` ya da finite bir değer ÜRETİR, ASLA
        NaN/inf üretmez. Bu durumda `EvidenceIntegrityError` yerel olarak,
        hiçbir I/O yapılmadan fırlatılır -- ASLA `TECHNICAL_SCORE_NONE`'a
        dönüştürülmez.

    Bu fonksiyon HİÇBİR data-quality/continuity/provider durumu KABUL
    ETMEZ ve HİÇBİR öncelik (precedence) mantığı İÇERMEZ -- yalnızca ZATEN
    başarıyla üretilmiş skor değerini değerlendirir (bkz. modül
    docstring'i, section 9/10)."""
    if technical_score is None:
        return ExclusionEvaluation(excluded=True, reason_code=TECHNICAL_SCORE_NONE)

    if isinstance(technical_score, bool) or not isinstance(technical_score, (int, float)):
        raise EvidenceIntegrityError(
            f"technical_score sayısal (float) ya da None olmalı, {type(technical_score).__name__} bulundu: "
            f"{technical_score!r}"
        )
    if not math.isfinite(technical_score):
        raise EvidenceIntegrityError(
            f"technical_score finite olmayan bir değer taşıyor -- üretim motorunun KENDİ aggregation "
            f"contract'ı ASLA NaN/inf üretmez (yalnızca None ya da finite bir değer), bu bir programlama/"
            f"domain girdi hatasıdır: {technical_score!r}"
        )

    return ExclusionEvaluation(excluded=False, reason_code=None)


def evaluate_history_validation_exclusion(history_validation_status: str | None) -> ExclusionEvaluation:
    """YALNIZCA `history_validation_status == "LEADING_EDGE_UNVERIFIED"` bağımsız
    bilimsel exclusion kategorisini değerlendirir (protokolün `missing_data_
    policy.excluded_categories`'indeki "leading-edge unverified handling"
    satırı) -- HATA 12N3C2-E2-B/E2-B-R1/HATA 12 final closure.

    Kesin sözleşme:
      - `"LEADING_EDGE_UNVERIFIED"` (bkz. `HistoryValidationStatus`, AYNI
        string spelling yeniden kullanılır) -> `excluded=True`,
        `reason_code=LEADING_EDGE_UNVERIFIED`.
      - `"VERIFIED_PRE_WINDOW"` -> `excluded=False`, `reason_code=None`.
      - Başka HERHANGİ bir değer (`None` DAHİL, bilinmeyen/yanlış yazılmış
        bir string DAHİL): bu iki tanınan domain değerinden biri DEĞİLDİR --
        kaba bir programlama/domain girdi hatasıdır (`resolve_expected_
        start()`'ın KENDİ contract'ı yalnızca bu iki değeri üretir), `Evidence
        IntegrityError` yerel olarak fırlatılır. `PRE_LISTING` gibi ÜÇÜNCÜ bir
        durum ASLA ÇIKARIMLANMAZ/İCAT EDİLMEZ (bkz. `history_window.py` modül
        docstring'i, kabul edilmiş sınırlama).

    Bu fonksiyon, YALNIZCA zaten başarıyla üretilmiş bir `TechnicalAnalysis.
    history_validation_status` alanı üzerinde çağrılmak üzere TASARLANMIŞTIR
    -- ayrı bir "sonradan bir downstream hard veto oldu mu" kontrolüne GEREK
    YOKTUR, çünkü öyle bir veto zaten `TechnicalAnalysis` nesnesinin hiç
    OLUŞMASINI engeller (bkz. HATA 12N3C2-E2-B-R1 raporu, Design B / "Exact
    producer condition"). HİÇBİR provider/continuity/OHLCV/insufficient-
    history durumu burada KABUL EDİLMEZ/YORUMLANMAZ."""
    if history_validation_status == HistoryValidationStatus.LEADING_EDGE_UNVERIFIED.value:
        return ExclusionEvaluation(excluded=True, reason_code=LEADING_EDGE_UNVERIFIED)
    if history_validation_status == HistoryValidationStatus.VERIFIED_PRE_WINDOW.value:
        return ExclusionEvaluation(excluded=False, reason_code=None)
    raise EvidenceIntegrityError(
        "history_validation_status tanınan iki değerden biri olmalı "
        f"({HistoryValidationStatus.VERIFIED_PRE_WINDOW.value!r} / "
        f"{HistoryValidationStatus.LEADING_EDGE_UNVERIFIED.value!r}), "
        f"{history_validation_status!r} bulundu -- bu bir programlama/domain girdi hatasıdır, ASLA "
        "PRE_LISTING ya da başka bir domain durumu olarak YORUMLANMAZ."
    )


def resolve_post_analysis_exclusion(
    technical_score_exclusion: ExclusionEvaluation,
    history_validation_exclusion: ExclusionEvaluation,
) -> ExclusionEvaluation:
    """İKİ, yapısal olarak BAĞIMSIZ post-analysis exclusion kararını
    (`evaluate_technical_score_exclusion()` ve
    `evaluate_history_validation_exclusion()`) TEK bir persisted
    `native_reason_code`'a indirger -- HATA 12 final closure, section
    "Single-reason precedence".

    Bu iki koşul nadiren ama GERÇEKTEN birlikte oluşabilir (bkz.
    `test_technical_score_none_and_leading_edge_unverified_can_coexist_in_real_engine_run`,
    `tests/test_technical_engine.py`) -- protokolün `missing_data_policy`'si
    aralarında açık bir sıralama BELİRTMEZ. KİLİTLİ, DOKÜMANTE EDİLMİŞ V1
    kuralı: `technical_score is None` önceliklidir, çünkü analiz çıktısının
    (skorun) kendisinin YOKLUĞU, girdi penceresinin kanıt durumuna dair bir
    provenance bayrağından DAHA DOĞRUDAN sonuç-geçersiz-kılıcıdır. Bu
    fonksiyon YENİ bir multi-reason şema GENİŞLEMESİ yapmaz -- yalnızca TEK
    bir `ExclusionEvaluation` döner (`AttemptResult.native_reason_code`
    tek skaler `str | None` olarak KALIR).

    Her iki girdi de `excluded=False` ise, sonuç da `excluded=False`
    (`reason_code=None`) olur -- gerçek bir `VALID_CANDIDATE` adayı."""
    if technical_score_exclusion.excluded:
        return technical_score_exclusion
    return history_validation_exclusion
