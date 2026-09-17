"""Technical V1 bağımsız bilimsel exclusion politikası -- SAF karşılaştırma
katmanı. HATA 12N3C2-E2-A / E2-A1.

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
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.research.attempt_reason_codes import TECHNICAL_SCORE_NONE
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
