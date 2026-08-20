import 'package:ai_investment_app/models/fund_analysis.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('FundAnalysis tüm alanları doğru ayrıştırır', () {
    final json = {
      'fund_code': 'AAK',
      'fund_name': 'ATA PORTFÖY ÇOKLU VARLIK DEĞİŞKEN FON',
      'price': 35.46418,
      'portfolio_size': 35461839.75,
      'investor_count': 769,
      'return_1m_pct': 5.2,
      'return_3m_pct': null,
      'return_6m_pct': 12.1,
      'return_1y_pct': 30.0,
      'composite_score': 14.83,
      'as_of_date': '2026-08-20',
      'generated_at': '2026-08-20T09:39:36.325070Z',
    };

    final fund = FundAnalysis.fromJson(json);

    expect(fund.fundCode, 'AAK');
    expect(fund.investorCount, 769);
    expect(fund.return3mPct, isNull);
    expect(fund.return1yPct, 30.0);
    expect(fund.compositeScore, 14.83);
  });

  test('FundAllocationItem doğru ayrıştırır', () {
    final json = {
      'fund_code': 'AAK',
      'fund_name': 'ATA PORTFÖY ÇOKLU VARLIK DEĞİŞKEN FON',
      'amount_tl': 333.33,
      'composite_score': 14.83,
    };

    final item = FundAllocationItem.fromJson(json);

    expect(item.fundCode, 'AAK');
    expect(item.amountTl, 333.33);
  });
}
