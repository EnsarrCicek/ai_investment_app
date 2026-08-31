/// HATA 5C-UI1 (31.08.2026): `MacroSnapshotDetail.confidence` backend'de
/// 0.0..1.0 aralığında (`macro/engine.py`'deki `_clamp(..., 0.0, 1.0)`) raw
/// olarak taşınır -- ekranda yüzdeye çevirmek için ×100 GEREKİR. Bu saf
/// fonksiyon, macro ekranındaki eski `data.confidence.toStringAsFixed(0)`
/// (×100 YOK, ör. 0.87 → "%1") scale bug'ını kalıcı olarak test edilebilir
/// kılar.
String formatPercentFromFraction(double fraction) => '%${(fraction * 100).toStringAsFixed(0)}';

/// HATA 5C-UI2 (31.08.2026): `AIDecision.confidence` ("Sinyal Mutabakatı")
/// backend'de ZATEN 0..100 skalasında üretilir (`round(agreement*100,2)`,
/// `decision/engine.py`) -- `formatPercentFromFraction()` burada
/// KULLANILAMAZ (0..1 varsayar, 62.5 için yanlışlıkla "%6250" üretirdi).
/// Bu dar scope'lu fonksiyon decision-level confidence için TEK doğru
/// formatter'dır -- ×100 YAPMAZ.
String formatDecisionConfidencePercent(double confidencePercent) => '%${confidencePercent.toStringAsFixed(0)}';

/// HATA 5C-UI2 (31.08.2026): `evidence_coverage`/`channel_completeness`
/// `null` olduğunda bu HATA 5B1'in "veri yetersiz" (unavailable measurement)
/// contract'ı DEĞİLDİR -- bu iki alan HATA 5C3A/5C3B ile sonradan eklendi,
/// `null` yalnızca "bu kayıt o değişiklikten ÖNCE üretildi, metrik hiç
/// hesaplanmadı" anlamına gelir. `formatTechnicalSignalAgreementPercent()`'ın
/// "Veri yetersiz" mesajıyla KARIŞTIRILMAMALIDIR.
String formatCoveragePercent(double? coverage) =>
    coverage == null ? 'Hesaplanmadı' : formatPercentFromFraction(coverage);

/// HATA 5C-UI2 (31.08.2026): `TechnicalAnalysis.confidence` `null` iken
/// (`technical_score` de `null` -- 7 bileşenin tamamı unavailable, HATA
/// 5C3A) 0 gibi sahte bir mutabakat GÖSTERİLMEZ -- dürüst "Veri yetersiz"
/// mesajı verilir. `0.0` GERÇEK bir değerdir (bkz. HATA 5B1 "valid zero vs
/// missing"), `formatPercentFromFraction(0.0)` = "%0" olarak gösterilir.
String formatTechnicalSignalAgreementPercent(double? confidence) =>
    confidence == null ? 'Veri yetersiz' : formatPercentFromFraction(confidence);
