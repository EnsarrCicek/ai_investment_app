import 'package:ai_investment_app/models/analyst_consensus.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('AnalystConsensus tüm alanları doğru ayrıştırır', () {
    final json = {
      'symbol': 'THYAO',
      'as_of': '2026-08-21T09:00:00+00:00',
      'strong_buy': 3,
      'buy': 8,
      'hold': 2,
      'sell': 0,
      'strong_sell': 0,
      'total_analysts': 13,
      'consensus_score': 1.08,
      'consensus_label': 'AL',
      'price_target_current': 301.25,
      'price_target_high': 580.0,
      'price_target_low': 330.0,
      'price_target_mean': 463.54,
      'price_target_median': 460.0,
      'upside_pct': 53.9,
      'trend': [
        {'period': '0m', 'strong_buy': 3, 'buy': 8, 'hold': 2, 'sell': 0, 'strong_sell': 0},
        {'period': '-1m', 'strong_buy': 3, 'buy': 7, 'hold': 2, 'sell': 0, 'strong_sell': 0},
      ],
      'source': 'yahoo_finance',
    };

    final consensus = AnalystConsensus.fromJson(json);

    expect(consensus.symbol, 'THYAO');
    expect(consensus.totalAnalysts, 13);
    expect(consensus.consensusLabel, 'AL');
    expect(consensus.priceTargetMean, 463.54);
    expect(consensus.upsidePct, 53.9);
    expect(consensus.trend.length, 2);
    expect(consensus.trend.first.buy, 8);
  });

  test('AnalystConsensus veri olmadığında null/varsayılan değerleri kabul eder', () {
    final json = {
      'symbol': 'SASA',
      'as_of': '2026-08-21T09:00:00+00:00',
      'total_analysts': 0,
      'consensus_label': 'VERI_YOK',
      'price_target_current': 2.27,
      'trend': [],
    };

    final consensus = AnalystConsensus.fromJson(json);

    expect(consensus.totalAnalysts, 0);
    expect(consensus.consensusScore, null);
    expect(consensus.priceTargetMean, null);
    expect(consensus.trend, isEmpty);
  });
}
