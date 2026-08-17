class TechnicalAnalysisDetail {
  final String asset;
  final double technicalScore;
  final String trend;
  final double confidence;
  final Map<String, double> components;
  final Map<String, dynamic> indicators;

  TechnicalAnalysisDetail({
    required this.asset,
    required this.technicalScore,
    required this.trend,
    required this.confidence,
    required this.components,
    required this.indicators,
  });

  factory TechnicalAnalysisDetail.fromJson(Map<String, dynamic> json) {
    return TechnicalAnalysisDetail(
      asset: json['asset'] as String,
      technicalScore: (json['technical_score'] as num).toDouble(),
      trend: json['trend'] as String,
      confidence: (json['confidence'] as num).toDouble(),
      components: (json['components'] as Map<String, dynamic>).map(
        (key, value) => MapEntry(key, (value as num).toDouble()),
      ),
      indicators: json['indicators'] as Map<String, dynamic>,
    );
  }
}
