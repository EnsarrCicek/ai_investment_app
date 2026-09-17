"""Technical V1 attempt sabit/kararlı reason-code sözlüğü -- HATA
12N3C2-B2-D / E1-R3 / E2-A1.

Bu sabitler `AttemptResult.native_reason_code` (mevcut, kapalı olmayan
`str | None` şema -- bkz. `attempt_models.py`) alanına YAZILACAK adaylardır,
ama bu modülün KENDİSİ hiçbir `AttemptResult`/`AttemptClaim` inşa ETMEZ,
hiçbir sınıflandırma (`AttemptResultClassification`) eşlemesi YAPMAZ --
bu eşleme, gelecekteki attempt-execution servisinin sorumluluğudur (bkz.
HATA 12N3C2-B2-D section 4/23, E1-R3 section 14, E2-A section 14).

İki AYRI kategori bulunur, KARIŞTIRILMAZ:

  1. KİMLİK-KAPISI FAIL nedenleri (dört sabit, TAM OLARAK dört kimlik-
     kapısının -- CONFIG/METHODOLOGY/RUNTIME/UNIVERSE -- her biri için
     TEK, kararlı bir FAIL nedeni; gelecekte `BLOCKED_*` sınıflandırmalarına
     eşlenmesi beklenir):
       - SCORING_CONFIG_HASH_MISMATCH
       - METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH
       - RUNTIME_IDENTITY_UNAUTHORIZED
       - SYMBOL_NOT_IN_FROZEN_UNIVERSE

  2. BAĞIMSIZ BİLİMSEL EXCLUSION nedenleri (protokolün `missing_data_
     policy.excluded_categories` listesindeki kategorilere karşılık gelir;
     gelecekte `AttemptResultClassification.EXCLUSION`'a eşlenmesi
     beklenir, `BLOCKED_*`'A DEĞİL):
       - TECHNICAL_SCORE_NONE (HATA 12N3C2-E2-A/E2-A1): `TechnicalAnalysis.
         technical_score is None` -- 7 ham component'in TAMAMI unavailable
         olduğu, son derece nadir, TAMAMEN meşru bir matematiksel çıktı
         (bkz. `scoring.py::aggregate_available_components`). Bu, bir
         data-quality veto'sunun SEMPTOMU DEĞİLDİR -- yapısal olarak
         MUTUALLY EXCLUSIVE'dir (bir veto zaten `TechnicalAnalysis`
         nesnesinin oluşmasını ENGELLER, bkz. HATA 12N3C2-E2-A audit
         raporu). Diğer 6 excluded_category (leading-edge/incomplete-
         snapshot/continuity/OHLCV/history/forward-horizon) bu HATA'nın
         kapsamı DIŞINDADIR, henüz KİLİTLENMEDİ.

`SYMBOL_NOT_IN_FROZEN_UNIVERSE` (HATA 12N3C2-E1-R3): bu, YALNIZCA POST-
CLAIM `evaluate_universe_gate()` FAIL durumu için bir persisted `native_
reason_code` ADAYIDIR -- gelecekteki bir controller'ın PRE-CLAIM
reddetme gerekçesiyle (o, hiçbir zaman bir `AttemptResult`'a
YAZILMAYACAK, farklı bir persistence/kontrol bağlamı) AYNI string
DEĞER olabilir ama İKİSİ KARIŞTIRILMAZ (bkz. HATA 12N3C2-E1 section 17/
21). `ASSET_CONFIG_MISSING`/`ASSET_CONFIG_MISMATCH` KASITLI OLARAK
YOKTUR -- Technical V1'de frozen 100-sembol evren üyeliğinin ÖTESİNDE
hiçbir dondurulmuş per-sembol asset config alanı yoktur (bkz. HATA
12N3C2-E1 audit raporu, Decision B).

Serbest metin/exception mesajı/traceback/URL/credential/kullanıcı verisi
HİÇBİR sabit için ASLA taşınmaz.
"""

from __future__ import annotations

SCORING_CONFIG_HASH_MISMATCH = "SCORING_CONFIG_HASH_MISMATCH"
METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH = "METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH"
RUNTIME_IDENTITY_UNAUTHORIZED = "RUNTIME_IDENTITY_UNAUTHORIZED"
SYMBOL_NOT_IN_FROZEN_UNIVERSE = "SYMBOL_NOT_IN_FROZEN_UNIVERSE"
TECHNICAL_SCORE_NONE = "TECHNICAL_SCORE_NONE"
