class StrategyPresetAggregate {
  final String preset;
  final double avgReturnPct;
  final double avgWinRatePct;
  final double avgMaxDrawdownPct;
  final int bestCount;
  final int symbolCount;

  StrategyPresetAggregate({
    required this.preset,
    required this.avgReturnPct,
    required this.avgWinRatePct,
    required this.avgMaxDrawdownPct,
    required this.bestCount,
    required this.symbolCount,
  });

  Map<String, dynamic> toJson() => {
        'preset': preset,
        'avg_return_pct': avgReturnPct,
        'avg_win_rate_pct': avgWinRatePct,
        'avg_max_drawdown_pct': avgMaxDrawdownPct,
        'best_count': bestCount,
        'symbol_count': symbolCount,
      };

  factory StrategyPresetAggregate.fromJson(Map<String, dynamic> json) {
    return StrategyPresetAggregate(
      preset: json['preset'] as String,
      avgReturnPct: (json['avg_return_pct'] as num).toDouble(),
      avgWinRatePct: (json['avg_win_rate_pct'] as num).toDouble(),
      avgMaxDrawdownPct: (json['avg_max_drawdown_pct'] as num).toDouble(),
      bestCount: json['best_count'] as int,
      symbolCount: json['symbol_count'] as int,
    );
  }
}

class StrategyLabRun {
  final String period;
  final String universe;
  final int testedCount;
  final int failedCount;
  final List<StrategyPresetAggregate> results;
  final String? winnerPreset;
  final DateTime createdAt;

  StrategyLabRun({
    required this.period,
    required this.universe,
    required this.testedCount,
    required this.failedCount,
    required this.results,
    required this.winnerPreset,
    required this.createdAt,
  });

  factory StrategyLabRun.fromJson(Map<String, dynamic> json) {
    return StrategyLabRun(
      period: json['period'] as String,
      universe: json['universe'] as String,
      testedCount: json['tested_count'] as int,
      failedCount: json['failed_count'] as int,
      results: (json['results'] as List)
          .map((e) => StrategyPresetAggregate.fromJson(e as Map<String, dynamic>))
          .toList(),
      winnerPreset: json['winner_preset'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
