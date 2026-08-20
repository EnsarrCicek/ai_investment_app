class FundPosition {
  final String fundCode;
  final double units;
  final double avgCost;
  final double? currentPrice;
  final double? compositeScore;
  final double? currentValue;
  final double investedAmount;

  FundPosition({
    required this.fundCode,
    required this.units,
    required this.avgCost,
    required this.currentPrice,
    required this.compositeScore,
    required this.currentValue,
    required this.investedAmount,
  });

  double? get profitLoss => currentValue == null ? null : currentValue! - investedAmount;

  double? get profitLossPct =>
      currentValue == null || investedAmount == 0 ? null : (currentValue! - investedAmount) / investedAmount * 100;

  factory FundPosition.fromJson(Map<String, dynamic> json) {
    double? toDoubleOrNull(dynamic v) => v == null ? null : (v as num).toDouble();
    return FundPosition(
      fundCode: json['fund_code'] as String,
      units: (json['units'] as num).toDouble(),
      avgCost: (json['avg_cost'] as num).toDouble(),
      currentPrice: toDoubleOrNull(json['current_price']),
      compositeScore: toDoubleOrNull(json['composite_score']),
      currentValue: toDoubleOrNull(json['current_value']),
      investedAmount: (json['invested_amount'] as num).toDouble(),
    );
  }
}

class FundInvestmentSettings {
  final double? monthlyIncome;
  final double monthlyBudget;

  FundInvestmentSettings({required this.monthlyIncome, required this.monthlyBudget});

  factory FundInvestmentSettings.fromJson(Map<String, dynamic> json) {
    return FundInvestmentSettings(
      monthlyIncome: json['monthly_income'] == null ? null : (json['monthly_income'] as num).toDouble(),
      monthlyBudget: (json['monthly_budget'] as num).toDouble(),
    );
  }
}
