class StrategyPresetResult {
  final String preset;
  final double totalReturnPct;
  final double buyAndHoldReturnPct;
  final double maxDrawdownPct;
  final int tradeCount;
  final double winRatePct;

  StrategyPresetResult({
    required this.preset,
    required this.totalReturnPct,
    required this.buyAndHoldReturnPct,
    required this.maxDrawdownPct,
    required this.tradeCount,
    required this.winRatePct,
  });

  factory StrategyPresetResult.fromJson(Map<String, dynamic> json) {
    return StrategyPresetResult(
      preset: json['preset'] as String,
      totalReturnPct: (json['total_return_pct'] as num).toDouble(),
      buyAndHoldReturnPct: (json['buy_and_hold_return_pct'] as num).toDouble(),
      maxDrawdownPct: (json['max_drawdown_pct'] as num).toDouble(),
      tradeCount: json['trade_count'] as int,
      winRatePct: (json['win_rate_pct'] as num).toDouble(),
    );
  }
}

class StrategyComparisonResult {
  final String asset;
  final String period;
  final String fromDate;
  final String toDate;
  final List<StrategyPresetResult> results;

  StrategyComparisonResult({
    required this.asset,
    required this.period,
    required this.fromDate,
    required this.toDate,
    required this.results,
  });

  factory StrategyComparisonResult.fromJson(Map<String, dynamic> json) {
    return StrategyComparisonResult(
      asset: json['asset'] as String,
      period: json['period'] as String,
      fromDate: json['from_date'] as String,
      toDate: json['to_date'] as String,
      results: (json['results'] as List)
          .map((e) => StrategyPresetResult.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

const Map<String, String> strategyPresetLabelsTr = {
  'BALANCED': 'Dengeli (Varsayılan)',
  'TREND_FOLLOWING': 'Trend Takibi',
  'MOMENTUM': 'Momentum Odaklı',
  'MEAN_REVERSION': 'Ortalamaya Dönüş',
  'MACD_FOCUSED': 'MACD Odaklı',
};
