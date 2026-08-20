class FundAnalysis {
  final String fundCode;
  final String fundName;
  final double price;
  final double portfolioSize;
  final int investorCount;
  final double? return1mPct;
  final double? return3mPct;
  final double? return6mPct;
  final double? return1yPct;
  final double compositeScore;
  final String asOfDate;

  FundAnalysis({
    required this.fundCode,
    required this.fundName,
    required this.price,
    required this.portfolioSize,
    required this.investorCount,
    required this.return1mPct,
    required this.return3mPct,
    required this.return6mPct,
    required this.return1yPct,
    required this.compositeScore,
    required this.asOfDate,
  });

  factory FundAnalysis.fromJson(Map<String, dynamic> json) {
    double? toDoubleOrNull(dynamic v) => v == null ? null : (v as num).toDouble();
    return FundAnalysis(
      fundCode: json['fund_code'] as String,
      fundName: json['fund_name'] as String,
      price: (json['price'] as num).toDouble(),
      portfolioSize: (json['portfolio_size'] as num).toDouble(),
      investorCount: json['investor_count'] as int,
      return1mPct: toDoubleOrNull(json['return_1m_pct']),
      return3mPct: toDoubleOrNull(json['return_3m_pct']),
      return6mPct: toDoubleOrNull(json['return_6m_pct']),
      return1yPct: toDoubleOrNull(json['return_1y_pct']),
      compositeScore: (json['composite_score'] as num).toDouble(),
      asOfDate: json['as_of_date'] as String,
    );
  }
}

class FundAllocationItem {
  final String fundCode;
  final String fundName;
  final double amountTl;
  final double compositeScore;

  FundAllocationItem({
    required this.fundCode,
    required this.fundName,
    required this.amountTl,
    required this.compositeScore,
  });

  factory FundAllocationItem.fromJson(Map<String, dynamic> json) {
    return FundAllocationItem(
      fundCode: json['fund_code'] as String,
      fundName: json['fund_name'] as String,
      amountTl: (json['amount_tl'] as num).toDouble(),
      compositeScore: (json['composite_score'] as num).toDouble(),
    );
  }
}
