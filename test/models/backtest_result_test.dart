import 'package:ai_investment_app/models/backtest_result.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BacktestTrade doğru ayrıştırır', () {
    final trade = BacktestTrade.fromJson({
      'entry_date': '2026-06-04',
      'exit_date': '2026-07-21',
      'entry_price': 299.75,
      'exit_price': 317.50,
      'return_pct': 5.9,
    });

    expect(trade.entryDate, '2026-06-04');
    expect(trade.returnPct, 5.9);
  });

  test('BacktestResult, iç içe işlem listesiyle birlikte doğru ayrıştırır', () {
    final result = BacktestResult.fromJson({
      'asset': 'THYAO',
      'period': '2y',
      'from_date': '2024-11-13',
      'to_date': '2026-08-17',
      'total_return_pct': -2.4,
      'buy_and_hold_return_pct': 8.9,
      'max_drawdown_pct': -19.3,
      'trade_count': 1,
      'win_rate_pct': 50.0,
      'trades': [
        {
          'entry_date': '2026-06-04',
          'exit_date': '2026-07-21',
          'entry_price': 299.75,
          'exit_price': 317.50,
          'return_pct': 5.9,
        },
      ],
    });

    expect(result.asset, 'THYAO');
    expect(result.trades, hasLength(1));
    expect(result.trades.first.returnPct, 5.9);
  });
}
