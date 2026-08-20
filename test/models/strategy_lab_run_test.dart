import 'package:ai_investment_app/models/strategy_lab_run.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('StrategyPresetAggregate toJson/fromJson round-trip', () {
    final aggregate = StrategyPresetAggregate(
      preset: 'MOMENTUM',
      avgReturnPct: 12.3,
      avgWinRatePct: 55.0,
      avgMaxDrawdownPct: -15.2,
      bestCount: 30,
      symbolCount: 95,
    );

    final roundTripped = StrategyPresetAggregate.fromJson(aggregate.toJson());

    expect(roundTripped.preset, 'MOMENTUM');
    expect(roundTripped.avgReturnPct, 12.3);
    expect(roundTripped.bestCount, 30);
  });

  test('StrategyLabRun tüm alanları doğru ayrıştırır', () {
    final json = {
      'period': '2y',
      'universe': 'BIST100',
      'tested_count': 95,
      'failed_count': 5,
      'results': [
        {
          'preset': 'MOMENTUM',
          'avg_return_pct': 12.3,
          'avg_win_rate_pct': 55.0,
          'avg_max_drawdown_pct': -15.2,
          'best_count': 30,
          'symbol_count': 95,
        },
      ],
      'winner_preset': 'MOMENTUM',
      'created_at': '2026-08-20T09:00:00+00:00',
    };

    final run = StrategyLabRun.fromJson(json);

    expect(run.universe, 'BIST100');
    expect(run.testedCount, 95);
    expect(run.results.length, 1);
    expect(run.winnerPreset, 'MOMENTUM');
  });
}
