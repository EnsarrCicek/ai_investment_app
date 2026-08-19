import 'package:ai_investment_app/models/portfolio_transaction.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('PortfolioTransaction tüm alanları doğru ayrıştırır', () {
    final json = {
      'asset': 'TUPRS',
      'quantity': 10.0,
      'buy_price': 372.0,
      'buy_date': '2026-08-18T12:50:39.161328+00:00',
      'sell_price': 390.0,
      'sell_date': '2026-08-19T10:00:00+00:00',
      'realized_pnl': 180.0,
      'realized_pnl_percent': 4.84,
    };

    final t = PortfolioTransaction.fromJson(json);

    expect(t.asset, 'TUPRS');
    expect(t.quantity, 10.0);
    expect(t.buyPrice, 372.0);
    expect(t.sellPrice, 390.0);
    expect(t.realizedPnl, 180.0);
    expect(t.realizedPnlPercent, 4.84);
  });

  test('PortfolioHistorySummary iç içe işlem listesiyle birlikte doğru ayrıştırır', () {
    final json = {
      'transactions': [
        {
          'asset': 'TUPRS',
          'quantity': 10.0,
          'buy_price': 372.0,
          'buy_date': '2026-08-18T12:50:39.161328+00:00',
          'sell_price': 390.0,
          'sell_date': '2026-08-19T10:00:00+00:00',
          'realized_pnl': 180.0,
          'realized_pnl_percent': 4.84,
        },
      ],
      'total_realized_pnl': 180.0,
    };

    final summary = PortfolioHistorySummary.fromJson(json);

    expect(summary.transactions, hasLength(1));
    expect(summary.transactions.first.asset, 'TUPRS');
    expect(summary.totalRealizedPnl, 180.0);
  });

  test('boş işlem listesini doğru ayrıştırır', () {
    final json = {'transactions': [], 'total_realized_pnl': 0.0};
    final summary = PortfolioHistorySummary.fromJson(json);
    expect(summary.transactions, isEmpty);
    expect(summary.totalRealizedPnl, 0.0);
  });
}
