class Decision {
  final String asset;
  final double? technicalScore;
  final double? newsScore;
  final double? macroScore;
  final double finalScore;
  final String decision;
  final double confidence;

  Decision({
    required this.asset,
    required this.technicalScore,
    required this.newsScore,
    required this.macroScore,
    required this.finalScore,
    required this.decision,
    required this.confidence,
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
    );
  }
}
