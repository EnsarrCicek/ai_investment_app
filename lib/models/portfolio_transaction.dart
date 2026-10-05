class PortfolioTransaction {
  final String asset;
  final double quantity;
  final double buyPrice;
  final DateTime buyDate;
  final double sellPrice;
  final DateTime sellDate;
  final double realizedPnl;
  final double realizedPnlPercent;

  /// Pozisyonun kayıtlı para birimi; eski işlemlerde null = bilinmiyor.
  final String? currency;

  PortfolioTransaction({
    required this.asset,
    required this.quantity,
    required this.buyPrice,
    required this.buyDate,
    required this.sellPrice,
    required this.sellDate,
    required this.realizedPnl,
    required this.realizedPnlPercent,
    this.currency,
  });

  factory PortfolioTransaction.fromJson(Map<String, dynamic> json) {
    return PortfolioTransaction(
      asset: json['asset'] as String,
      quantity: (json['quantity'] as num).toDouble(),
      buyPrice: (json['buy_price'] as num).toDouble(),
      buyDate: DateTime.parse(json['buy_date'] as String),
      sellPrice: (json['sell_price'] as num).toDouble(),
      sellDate: DateTime.parse(json['sell_date'] as String),
      realizedPnl: (json['realized_pnl'] as num).toDouble(),
      realizedPnlPercent: (json['realized_pnl_percent'] as num).toDouble(),
      currency: json['currency'] as String?,
    );
  }
}

class PortfolioHistorySummary {
  final List<PortfolioTransaction> transactions;
  final double totalRealizedPnl;

  PortfolioHistorySummary({required this.transactions, required this.totalRealizedPnl});

  factory PortfolioHistorySummary.fromJson(Map<String, dynamic> json) {
    return PortfolioHistorySummary(
      transactions: (json['transactions'] as List)
          .map((e) => PortfolioTransaction.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalRealizedPnl: (json['total_realized_pnl'] as num).toDouble(),
    );
  }
}
