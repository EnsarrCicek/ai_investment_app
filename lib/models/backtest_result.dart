class BacktestTrade {
  final String entryDate;
  final String exitDate;
  final double entryPrice;
  final double exitPrice;
  final double returnPct;

  BacktestTrade({
    required this.entryDate,
    required this.exitDate,
    required this.entryPrice,
    required this.exitPrice,
    required this.returnPct,
  });

  factory BacktestTrade.fromJson(Map<String, dynamic> json) {
    return BacktestTrade(
      entryDate: json['entry_date'] as String,
      exitDate: json['exit_date'] as String,
      entryPrice: (json['entry_price'] as num).toDouble(),
      exitPrice: (json['exit_price'] as num).toDouble(),
      returnPct: (json['return_pct'] as num).toDouble(),
    );
  }
}

class BacktestResult {
  final String asset;
  final String period;
  final String fromDate;
  final String toDate;
  final double totalReturnPct;
  final double buyAndHoldReturnPct;
  final double maxDrawdownPct;
  final int tradeCount;
  final double winRatePct;
  final List<BacktestTrade> trades;

  BacktestResult({
    required this.asset,
    required this.period,
    required this.fromDate,
    required this.toDate,
    required this.totalReturnPct,
    required this.buyAndHoldReturnPct,
    required this.maxDrawdownPct,
    required this.tradeCount,
    required this.winRatePct,
    required this.trades,
  });

  factory BacktestResult.fromJson(Map<String, dynamic> json) {
    return BacktestResult(
      asset: json['asset'] as String,
      period: json['period'] as String,
      fromDate: json['from_date'] as String,
      toDate: json['to_date'] as String,
      totalReturnPct: (json['total_return_pct'] as num).toDouble(),
      buyAndHoldReturnPct: (json['buy_and_hold_return_pct'] as num).toDouble(),
      maxDrawdownPct: (json['max_drawdown_pct'] as num).toDouble(),
      tradeCount: json['trade_count'] as int,
      winRatePct: (json['win_rate_pct'] as num).toDouble(),
      trades: (json['trades'] as List)
          .map((e) => BacktestTrade.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}
