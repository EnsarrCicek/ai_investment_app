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
  // alanıdır (tek sayıya birleştirilmez). UI label/gösterim BU turda DEĞİŞMEDİ
  // (5C-UI2'ye bırakıldı).
  final double confidence;
  // 28.08.2026 (HATA 5C3B): "Veri Kapsamı" -- technical/news/macro kanallarının
  // configured ağırlık açısından ne kadarının mevcut olduğunu ölçer. Bu alan
  // eklenmeden önceki kayıtlarda yoktur; `null` bunu geriye dönük uyumlu
  // şekilde ifade eder. Henüz UI'da GÖSTERİLMİYOR (5C-UI2).
  final double? channelCompleteness;
  final DateTime? createdAt;

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
    );
  }
}
