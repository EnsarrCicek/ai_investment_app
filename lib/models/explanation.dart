class Explanation {
  final String asset;
  final String decision;
  final double finalScore;
  final double confidence;
  final String summary;
  final List<String> technicalReasons;
  final List<String> macroReasons;
  final List<String> missing;

  Explanation({
    required this.asset,
    required this.decision,
    required this.finalScore,
    required this.confidence,
    required this.summary,
    required this.technicalReasons,
    required this.macroReasons,
    required this.missing,
  });

  factory Explanation.fromJson(Map<String, dynamic> json) {
    return Explanation(
      asset: json['asset'] as String,
      decision: json['decision'] as String,
      finalScore: (json['final_score'] as num).toDouble(),
      confidence: (json['confidence'] as num).toDouble(),
      summary: json['summary'] as String,
      technicalReasons: (json['technical_reasons'] as List).cast<String>(),
      macroReasons: (json['macro_reasons'] as List).cast<String>(),
      missing: (json['missing'] as List).cast<String>(),
    );
  }
}
