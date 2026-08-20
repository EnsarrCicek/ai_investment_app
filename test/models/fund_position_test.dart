import 'package:ai_investment_app/models/fund_position.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('FundPosition kâr/zarar yüzdesini doğru hesaplar', () {
    final json = {
      'fund_code': 'AAK',
      'units': 100.0,
      'avg_cost': 30.0,
      'current_price': 33.0,
      'composite_score': 12.5,
      'current_value': 3300.0,
      'invested_amount': 3000.0,
    };

    final position = FundPosition.fromJson(json);

    expect(position.profitLoss, 300.0);
    expect(position.profitLossPct, closeTo(10.0, 0.001));
  });

  test('güncel fiyat alınamadığında değerler null olur', () {
    final json = {
      'fund_code': 'AAK',
      'units': 100.0,
      'avg_cost': 30.0,
      'current_price': null,
      'composite_score': null,
      'current_value': null,
      'invested_amount': 3000.0,
    };

    final position = FundPosition.fromJson(json);

    expect(position.currentValue, isNull);
    expect(position.profitLoss, isNull);
    expect(position.profitLossPct, isNull);
  });

  test('FundInvestmentSettings monthly_income null olabilir', () {
    final json = {'monthly_income': null, 'monthly_budget': 2000.0};

    final settings = FundInvestmentSettings.fromJson(json);

    expect(settings.monthlyIncome, isNull);
    expect(settings.monthlyBudget, 2000.0);
  });
}
