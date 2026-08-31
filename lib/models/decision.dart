class Decision {
  final String asset;
  final double? technicalScore;
  final double? newsScore;
  final double? macroScore;
  final double finalScore;
  final String decision;
  // 28.08.2026 (HATA 5C3B): "Sinyal Mutabakatı" -- mevcut technical/news/macro
  // kanallarının final kararla ne kadar aynı yönde olduğunu ölçer (0-100).
  // Olasılık/doğruluk/veri eksiksizliği DEĞİLDİR -- o, ayrı `channelCompleteness`
  // alanıdır (tek sayıya birleştirilmez). UI'da "Sinyal Mutabakatı" etiketiyle
  // gösterilir (bkz. `utils/percent_format.dart::formatDecisionConfidencePercent`,
  // HATA 5C-UI2) -- ZATEN 0..100 skalasında, ×100 YAPILMAZ.
  final double confidence;
  // 28.08.2026 (HATA 5C3B): "Veri Kapsamı" -- technical/news/macro kanallarının
  // configured ağırlık açısından ne kadarının mevcut olduğunu ölçer. Bu alan
  // eklenmeden önceki kayıtlarda yoktur; `null` bunu geriye dönük uyumlu
  // şekilde ifade eder ("Hesaplanmadı", bkz. `formatCoveragePercent`, HATA
  // 5C-UI2) -- "veri yetersiz" İLE KARIŞTIRILMAZ.
  final double? channelCompleteness;
  final DateTime? createdAt;
  // HATA 5C-UI2 (31.08.2026): journal/geçmiş kayıtlarında `confidence`'ın
  // hangi formülle üretildiğini (eski heuristik mi, 1.1.0 Sinyal Mutabakatı
  // mı) ayırt etmek için gerekli -- bkz. `utils/decision_engine_version.dart`.
  // Eski (bu alan eklenmeden önceki) kayıtlarda `null`, LEGACY kabul edilir.
  final String? decisionEngineVersion;

  Decision({
    required this.asset,
    required this.technicalScore,
    required this.newsScore,
    required this.macroScore,
    required this.finalScore,
    required this.decision,
    required this.confidence,
    this.channelCompleteness,
    this.createdAt,
    this.decisionEngineVersion,
  });

  factory Decision.fromJson(Map<String, dynamic> json) {
    return Decision(
      asset: json['asset'] as String,
      technicalScore: (json['technical_score'] as num?)?.toDouble(),
      newsScore: (json['news_score'] as num?)?.toDouble(),
      macroScore: (json['macro_score'] as num?)?.toDouble(),
      finalScore: (json['final_score'] as num).toDouble(),
      decision: json['decision'] as String,
      confidence: (json['confidence'] as num).toDouble(),
      channelCompleteness: (json['channel_completeness'] as num?)?.toDouble(),
      createdAt: json['created_at'] != null ? DateTime.parse(json['created_at'] as String) : null,
      decisionEngineVersion: json['decision_engine_version'] as String?,
    );
  }
}
