class Explanation {
  final String asset;
  final String decision;
  final double finalScore;
  final double confidence;
  final String summary;
  final double? technicalWeight;
  final double? newsWeight;
  final double? macroWeight;
  final List<String> technicalReasons;
  final List<String> macroReasons;
  final List<String> newsReasons;
  final List<String> missing;

  Explanation({
    required this.asset,
    required this.decision,
    required this.finalScore,
    required this.confidence,
    required this.summary,
    this.technicalWeight,
    this.newsWeight,
    this.macroWeight,
    required this.technicalReasons,
    required this.macroReasons,
    required this.newsReasons,
    required this.missing,
  });

  factory Explanation.fromJson(Map<String, dynamic> json) {
    return Explanation(
      asset: json['asset'] as String,
      decision: json['decision'] as String,
      finalScore: (json['final_score'] as num).toDouble(),
      confidence: (json['confidence'] as num).toDouble(),
      summary: json['summary'] as String,
      technicalWeight: (json['technical_weight'] as num?)?.toDouble(),
      newsWeight: (json['news_weight'] as num?)?.toDouble(),
      macroWeight: (json['macro_weight'] as num?)?.toDouble(),
      technicalReasons: (json['technical_reasons'] as List).cast<String>(),
      macroReasons: (json['macro_reasons'] as List).cast<String>(),
      newsReasons: (json['news_reasons'] as List?)?.cast<String>() ?? const [],
      missing: (json['missing'] as List).cast<String>(),
    );
  }
}
