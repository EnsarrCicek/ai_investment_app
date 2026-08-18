class DailyUsage {
  final String date;
  final double spentUsd;

  DailyUsage({required this.date, required this.spentUsd});

  factory DailyUsage.fromJson(Map<String, dynamic> json) {
    return DailyUsage(
      date: json['date'] as String,
      spentUsd: (json['spent_usd'] as num).toDouble(),
    );
  }
}

class UsageSummary {
  final double budgetUsd;
  final double spentTotalUsd;
  final double remainingUsd;
  final double spentTodayUsd;
  final int callsToday;
  final int callsTotal;
  final int tokensToday;
  final int tokensTotal;
  final List<DailyUsage> dailyBreakdown;

  UsageSummary({
    required this.budgetUsd,
    required this.spentTotalUsd,
    required this.remainingUsd,
    required this.spentTodayUsd,
    required this.callsToday,
    required this.callsTotal,
    required this.tokensToday,
    required this.tokensTotal,
    required this.dailyBreakdown,
  });

  factory UsageSummary.fromJson(Map<String, dynamic> json) {
    return UsageSummary(
      budgetUsd: (json['budget_usd'] as num).toDouble(),
      spentTotalUsd: (json['spent_total_usd'] as num).toDouble(),
      remainingUsd: (json['remaining_usd'] as num).toDouble(),
      spentTodayUsd: (json['spent_today_usd'] as num).toDouble(),
      callsToday: json['calls_today'] as int,
      callsTotal: json['calls_total'] as int,
      tokensToday: json['tokens_today'] as int,
      tokensTotal: json['tokens_total'] as int,
      dailyBreakdown: (json['daily_breakdown'] as List)
          .map((e) => DailyUsage.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}
