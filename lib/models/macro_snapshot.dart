class MacroSnapshotDetail {
  final double macroScore;
  final double confidence;
  final Map<String, double> components;
  final Map<String, dynamic> indicators;

  MacroSnapshotDetail({
    required this.macroScore,
    required this.confidence,
    required this.components,
    required this.indicators,
  });

  factory MacroSnapshotDetail.fromJson(Map<String, dynamic> json) {
    return MacroSnapshotDetail(
      macroScore: (json['macro_score'] as num).toDouble(),
      confidence: (json['confidence'] as num).toDouble(),
      components: (json['components'] as Map<String, dynamic>).map(
        (key, value) => MapEntry(key, (value as num).toDouble()),
      ),
      indicators: json['indicators'] as Map<String, dynamic>,
    );
  }
}
