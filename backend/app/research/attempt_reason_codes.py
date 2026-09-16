"""Technical V1 kimlik-kapısı (identity gate) sabit/kararlı reason-code
sözlüğü -- HATA 12N3C2-B2-D.

Bu sabitler `AttemptResult.native_reason_code` (mevcut, kapalı olmayan
`str | None` şema -- bkz. `attempt_models.py`) alanına YAZILACAK adaylardır,
ama bu modülün KENDİSİ hiçbir `AttemptResult`/`AttemptClaim` inşa ETMEZ,
hiçbir sınıflandırma (`AttemptResultClassification`) eşlemesi YAPMAZ --
bu eşleme, gelecekteki attempt-execution servisinin sorumluluğudur (bkz.
HATA 12N3C2-B2-D section 4/23).

Üç sabit, TAM OLARAK üç kimlik-kapısının (CONFIG/METHODOLOGY/RUNTIME) her
biri için TEK, kararlı bir FAIL nedenini temsil eder -- serbest metin/
exception mesajı/traceback/URL/credential/kullanıcı verisi ASLA taşımazlar.
"""

from __future__ import annotations

SCORING_CONFIG_HASH_MISMATCH = "SCORING_CONFIG_HASH_MISMATCH"
METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH = "METHODOLOGY_SOURCE_FINGERPRINT_MISMATCH"
RUNTIME_IDENTITY_UNAUTHORIZED = "RUNTIME_IDENTITY_UNAUTHORIZED"
