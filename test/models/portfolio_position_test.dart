import 'package:ai_investment_app/models/portfolio_position.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('birleştirilmiş (çoklu lot) pozisyonu doğru ayrıştırır', () {
    final json = {
      'asset': 'GARAN',
      'quantity': 10.0,
      'buy_price': 150.0,
      'lot_count': 2,
      'current_price': 131.3,
      'invested_amount': 1500.0,
      'current_value': 1313.0,
      'profit_loss': -187.0,
      'return_percent': -12.5,
    };

    final position = PortfolioPosition.fromJson(json);

    expect(position.asset, 'GARAN');
    expect(position.quantity, 10.0);
    expect(position.buyPrice, 150.0);
    expect(position.lotCount, 2);
    expect(position.profitLoss, -187.0);
  });

  test('hata alanı varsa fiyat alanları null olabilir', () {
    final json = {
      'asset': 'XYZ',
      'quantity': 5.0,
      'buy_price': 10.0,
      'lot_count': 1,
      'error': "'XYZ' için market data bulunamadı",
    };

    final position = PortfolioPosition.fromJson(json);

    expect(position.error, isNotNull);
    expect(position.currentPrice, isNull);
  });

  test('PortfolioSummary doğru ayrıştırır', () {
    final summary = PortfolioSummary.fromJson({
      'total_invested': 1500.0,
      'total_current_value': 1313.0,
      'total_profit_loss': -187.0,
      'total_return_percent': -12.5,
    });

    expect(summary.totalInvested, 1500.0);
    expect(summary.totalReturnPercent, -12.5);
  });
}
