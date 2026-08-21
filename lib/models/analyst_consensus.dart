class AnalystRecommendationPeriod {
  final String? period;
  final int strongBuy;
  final int buy;
  final int hold;
  final int sell;
  final int strongSell;

  AnalystRecommendationPeriod({
    required this.period,
    required this.strongBuy,
    required this.buy,
    required this.hold,
    required this.sell,
    required this.strongSell,
  });

  factory AnalystRecommendationPeriod.fromJson(Map<String, dynamic> json) {
    return AnalystRecommendationPeriod(
      period: json['period'] as String?,
      strongBuy: json['strong_buy'] as int? ?? 0,
      buy: json['buy'] as int? ?? 0,
      hold: json['hold'] as int? ?? 0,
      sell: json['sell'] as int? ?? 0,
      strongSell: json['strong_sell'] as int? ?? 0,
    );
  }
}

class AnalystConsensus {
  final String symbol;
  final DateTime asOf;
  final int strongBuy;
  final int buy;
  final int hold;
  final int sell;
  final int strongSell;
  final int totalAnalysts;
  final double? consensusScore;
  final String consensusLabel;
  final double? priceTargetCurrent;
  final double? priceTargetHigh;
  final double? priceTargetLow;
  final double? priceTargetMean;
  final double? priceTargetMedian;
  final double? upsidePct;
  final List<AnalystRecommendationPeriod> trend;
  final String source;

  AnalystConsensus({
    required this.symbol,
    required this.asOf,
    required this.strongBuy,
    required this.buy,
    required this.hold,
    required this.sell,
    required this.strongSell,
    required this.totalAnalysts,
    required this.consensusScore,
    required this.consensusLabel,
    required this.priceTargetCurrent,
    required this.priceTargetHigh,
    required this.priceTargetLow,
    required this.priceTargetMean,
    required this.priceTargetMedian,
    required this.upsidePct,
    required this.trend,
    required this.source,
  });

  factory AnalystConsensus.fromJson(Map<String, dynamic> json) {
    double? toDoubleOrNull(dynamic v) => v == null ? null : (v as num).toDouble();
    return AnalystConsensus(
      symbol: json['symbol'] as String,
      asOf: DateTime.parse(json['as_of'] as String),
      strongBuy: json['strong_buy'] as int? ?? 0,
      buy: json['buy'] as int? ?? 0,
      hold: json['hold'] as int? ?? 0,
      sell: json['sell'] as int? ?? 0,
      strongSell: json['strong_sell'] as int? ?? 0,
      totalAnalysts: json['total_analysts'] as int? ?? 0,
      consensusScore: toDoubleOrNull(json['consensus_score']),
      consensusLabel: json['consensus_label'] as String? ?? 'VERI_YOK',
      priceTargetCurrent: toDoubleOrNull(json['price_target_current']),
      priceTargetHigh: toDoubleOrNull(json['price_target_high']),
      priceTargetLow: toDoubleOrNull(json['price_target_low']),
      priceTargetMean: toDoubleOrNull(json['price_target_mean']),
      priceTargetMedian: toDoubleOrNull(json['price_target_median']),
      upsidePct: toDoubleOrNull(json['upside_pct']),
      trend: (json['trend'] as List? ?? const [])
          .map((e) => AnalystRecommendationPeriod.fromJson(e as Map<String, dynamic>))
          .toList(),
      source: json['source'] as String? ?? 'yahoo_finance',
    );
  }
}

const Map<String, String> analystConsensusLabelsTr = {
  'GUCLU_AL': 'Güçlü Al',
  'AL': 'Al',
  'TUT': 'Tut',
  'SAT': 'Sat',
  'GUCLU_SAT': 'Güçlü Sat',
  'VERI_YOK': 'Veri Yok',
};
