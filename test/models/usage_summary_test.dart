import 'package:ai_investment_app/models/usage_summary.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('tüm alanları ve günlük dökümü doğru ayrıştırır', () {
    final json = {
      'budget_usd': 5.0,
      'spent_total_usd': 0.0003,
      'remaining_usd': 4.9997,
      'spent_today_usd': 0.0003,
      'calls_today': 1,
      'calls_total': 1,
      'tokens_today': 714,
      'tokens_total': 714,
      'daily_breakdown': [
        {'date': '2026-08-18', 'spent_usd': 0.0003},
      ],
    };

    final usage = UsageSummary.fromJson(json);

    expect(usage.budgetUsd, 5.0);
    expect(usage.spentTotalUsd, 0.0003);
    expect(usage.remainingUsd, 4.9997);
    expect(usage.spentTodayUsd, 0.0003);
    expect(usage.callsToday, 1);
    expect(usage.callsTotal, 1);
    expect(usage.tokensToday, 714);
    expect(usage.tokensTotal, 714);
    expect(usage.dailyBreakdown, hasLength(1));
    expect(usage.dailyBreakdown.first.date, '2026-08-18');
    expect(usage.dailyBreakdown.first.spentUsd, 0.0003);
  });

  test('boş günlük döküm listesini doğru ayrıştırır', () {
    final json = {
      'budget_usd': 5.0,
      'spent_total_usd': 0.0,
      'remaining_usd': 5.0,
      'spent_today_usd': 0.0,
      'calls_today': 0,
      'calls_total': 0,
      'tokens_today': 0,
      'tokens_total': 0,
      'daily_breakdown': [],
    };

    final usage = UsageSummary.fromJson(json);
    expect(usage.dailyBreakdown, isEmpty);
  });
}
