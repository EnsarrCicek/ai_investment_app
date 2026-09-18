"""Technical V1 attempt sabit/kararlı reason-code sözlüğü -- HATA
12N3C2-B2-D / E1-R3 / E2-A1 / E2-B-R1 / HATA 12 final closure / HATA 13C.

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
         raporu).
       - LEADING_EDGE_UNVERIFIED (HATA 12N3C2-E2-B/E2-B-R1): `TechnicalAnalysis.
         history_validation_status == "LEADING_EDGE_UNVERIFIED"` (bkz.
         `app.engines.technical.history_window.HistoryValidationStatus`,
         AYNI string spelling yeniden kullanılır, yeni bir isim
         İCAT EDİLMEZ). `TECHNICAL_SCORE_NONE`'ın aksine bu, tek başına
         bir hard veto DEĞİLDİR -- `analyze_with_id()` bu durumla BİRLİKTE
         geçerli, non-None bir `technical_score` üretebilir (bkz. E2-B-R1
         audit raporu, section "Design B"). KİLİTLİ tek-neden ÖNCELİK
         kuralı (schema-genişletme YAPILMADAN, section "Single-reason
         precedence" -- final closure raporu): (a) `resolve_expected_start()`
         SONRASI çalışan spesifik bir hard veto (continuity/raw-OHLCV/
         insufficient-history) varsa, bu HİÇBİR ZAMAN persist edilmez --
         zaten o durumda `TechnicalAnalysis` nesnesi hiç OLUŞMAZ; (b) bir
         `TechnicalAnalysis` başarıyla üretildiyse VE aynı anda hem
         `technical_score is None` hem `history_validation_status ==
         LEADING_EDGE_UNVERIFIED` ise (yapısal olarak BAĞIMSIZ iki koşul,
         nadiren ama gerçekten birlikte oluşabilir), `TECHNICAL_SCORE_NONE`
         TEK persisted reason olarak seçilir (analiz çıktısının kendisini
         geçersiz kılan koşul, bir provenance/kanıt bayrağından daha
         doğrudan sonuç-geçersiz-kılıcıdır) -- bkz.
         `exclusion_policy.resolve_post_analysis_exclusion()`.

  Diğer 4 excluded_category (continuity/raw-OHLCV/insufficient-history/
  incomplete-snapshot/forward-horizon) YENİ bir sabit GEREKTİRMEZ:
  continuity/raw-OHLCV/insufficient-history zaten `app.engines.technical.
  data_quality`'nin KENDİ `DataQualityError.reason_code`'unda (ör.
  `MISSING_TRADING_SESSION`/`UNEXPECTED_TRADING_SESSION`/`INVALID_OHLCV`/
  `MISSING_OHLCV`/`INSUFFICIENT_HISTORY`) mevcuttur -- burada TEKRAR
  TANIMLANMAZ/ALIAS'LANMAZ. `forward horizon lacking sufficient completed
  future sessions` bir CAPTURE-TIME `AttemptResult` reddi DEĞİL, bir
  OUTCOME-EVALUATION olgunlaşma (maturation) kavramıdır -- burada bir
  reason code GEREKTİRMEZ. `incomplete input snapshot`, gelecekteki
  attempt-execution/evidence-upload servisine ERTELENMİŞTİR (henüz hiçbir
  kod bunu üretmiyor -- bkz. `technical_v1_freeze_manifest.json`'daki
  `input_snapshot_evidence_design: "TO_BE_DEFINED_BEFORE_HOLDOUT"`). Tümü
  için detaylı taksonomi tablosu: HATA 12 final closure raporu.

  3. OPERASYONEL FAILED nedeni (HATA 13C -- `AttemptResultClassification.
     FAILED`'e eşlenir, EXCLUSION/BLOCKED_*'A DEĞİL, bir bilimsel gözlem/
     kimlik-yetkilendirme kararı DEĞİLDİR):
       - PROVIDER_DATA_UNAVAILABLE: sağlayıcı (yfinance/BistProvider) veri
         çekme sınırının (asset ya da benchmark, retry'lar tükendikten
         SONRA) BAŞARISIZ olduğu durum -- bkz. `technical_v1_attempt_
         execution.py`, "provider fetch boundary". Ham exception mesajı/
         traceback/URL BURAYA ASLA taşınmaz (bu kural HİÇBİR sabit için
         istisnasız geçerlidir, bkz. dosya sonu notu) -- sağlayıcının
         GERÇEKTE fırlattığı istisna türü kapalı bir taksonomi OLUŞTURMADIĞI
         için (bkz. `bist_provider.py`'nin kendi retry-tükenme deseni)
         BURADA tek, kararlı bir sabit yeterlidir, alt-kategori İCAT
         EDİLMEZ. `MISSING_COLUMNS`/`MISSING_OHLCV`/`STALE_DATA`/
         `TRADING_CALENDAR_UNSUPPORTED_YEAR` (bkz. `data_quality.py`)
         KASITLI OLARAK buraya eşlenmez -- HATA 12'nin onayladığı
         taksonomide bunlar için AÇIK bir karar YOK, bu yüzden (tahmin
         yerine) internal-defect sınırına (section 21/HATA 13C raporu)
         bırakılır, ASLA FAILED'e "guess" edilmez.

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
LEADING_EDGE_UNVERIFIED = "LEADING_EDGE_UNVERIFIED"
PROVIDER_DATA_UNAVAILABLE = "PROVIDER_DATA_UNAVAILABLE"
