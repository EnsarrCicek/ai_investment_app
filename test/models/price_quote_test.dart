import 'package:ai_investment_app/models/price_quote.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('PriceQuote tüm alanları doğru ayrıştırır', () {
    final json = {
      'asset_id': 'THYAO',
      'timestamp': '2026-08-18T12:45:00+03:00',
      'last_price': 301.5,
      'previous_close': 301.25,
      'change': 0.25,
      'change_percent': 0.08,
      'open': 298.5,
      'high': 302.5,
      'low': 297.75,
      'volume': 12614579,
      'source': 'yahoo_finance',
    };

    final quote = PriceQuote.fromJson(json);

    expect(quote.assetId, 'THYAO');
    expect(quote.lastPrice, 301.5);
    expect(quote.previousClose, 301.25);
    expect(quote.change, 0.25);
    expect(quote.changePercent, 0.08);
    expect(quote.open, 298.5);
    expect(quote.high, 302.5);
    expect(quote.low, 297.75);
    expect(quote.volume, 12614579);
    expect(quote.source, 'yahoo_finance');
  });

  test('change_percent null olabilir (önceki kapanış 0 ise)', () {
    final json = {
      'asset_id': 'THYAO',
      'timestamp': '2026-08-18T12:45:00+03:00',
      'last_price': 301.5,
      'previous_close': 0.0,
      'change': 301.5,
      'change_percent': null,
      'open': 298.5,
      'high': 302.5,
      'low': 297.75,
      'volume': 0,
      'source': 'yahoo_finance',
    };

    final quote = PriceQuote.fromJson(json);
    expect(quote.changePercent, isNull);
  });

  test('PriceBar doğru ayrıştırır', () {
    final json = {
      'timestamp': '2026-08-18T00:00:00+03:00',
      'open': 298.5,
      'high': 302.5,
      'low': 297.75,
      'close': 301.5,
      'volume': 12614579,
    };

    final bar = PriceBar.fromJson(json);

    expect(bar.open, 298.5);
    expect(bar.high, 302.5);
    expect(bar.low, 297.75);
    expect(bar.close, 301.5);
    expect(bar.volume, 12614579);
  });
}
