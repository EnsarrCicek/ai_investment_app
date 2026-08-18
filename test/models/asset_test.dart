import 'package:ai_investment_app/models/asset.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Asset tüm alanları doğru ayrıştırır', () {
    final json = {
      'symbol': 'THYAO',
      'name': 'Türk Hava Yolları Anonim Ortaklığı',
      'market': 'BIST',
      'asset_type': 'STOCK',
      'currency': 'TRY',
      'active': true,
    };

    final asset = Asset.fromJson(json);

    expect(asset.symbol, 'THYAO');
    expect(asset.name, 'Türk Hava Yolları Anonim Ortaklığı');
    expect(asset.market, 'BIST');
    expect(asset.assetType, 'STOCK');
    expect(asset.currency, 'TRY');
    expect(asset.active, true);
  });
}
