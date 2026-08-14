class PortfolioPosition {
  final String id;
  final String asset;
  final double buyPrice;
  final double quantity;
  final double? currentPrice;
  final double? investedAmount;
  final double? currentValue;
  final double? profitLoss;
  final double? returnPercent;
  final String? error;

  PortfolioPosition({
    required this.id,
    required this.asset,
    required this.buyPrice,
    required this.quantity,
    this.currentPrice,
    this.investedAmount,
    this.currentValue,
    this.profitLoss,
    this.returnPercent,
    this.error,
  });

  factory PortfolioPosition.fromJson(Map<String, dynamic> json) {
    return PortfolioPosition(
      id: json['id'] as String,
      asset: json['asset'] as String,
      buyPrice: (json['buy_price'] as num).toDouble(),
      quantity: (json['quantity'] as num).toDouble(),
      currentPrice: (json['current_price'] as num?)?.toDouble(),
      investedAmount: (json['invested_amount'] as num?)?.toDouble(),
      currentValue: (json['current_value'] as num?)?.toDouble(),
      profitLoss: (json['profit_loss'] as num?)?.toDouble(),
      returnPercent: (json['return_percent'] as num?)?.toDouble(),
      error: json['error'] as String?,
    );
  }
}

class PortfolioSummary {
  final double totalInvested;
  final double totalCurrentValue;
  final double totalProfitLoss;
  final double totalReturnPercent;

  PortfolioSummary({
    required this.totalInvested,
    required this.totalCurrentValue,
    required this.totalProfitLoss,
    required this.totalReturnPercent,
  });

  factory PortfolioSummary.fromJson(Map<String, dynamic> json) {
    return PortfolioSummary(
      totalInvested: (json['total_invested'] as num).toDouble(),
      totalCurrentValue: (json['total_current_value'] as num).toDouble(),
      totalProfitLoss: (json['total_profit_loss'] as num).toDouble(),
      totalReturnPercent: (json['total_return_percent'] as num).toDouble(),
    );
  }
}
