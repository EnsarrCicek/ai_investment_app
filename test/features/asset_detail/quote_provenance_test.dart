import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/asset_detail/asset_detail_screen.dart';
import 'package:ai_investment_app/models/price_quote.dart';

Map<String, dynamic> base() => {
      'asset_id': 'ABC',
      'timestamp': '2026-10-05T11:55:00+03:00',
      'last_price': 12.5,
      'previous_close': 12.0,
      'change': 0.5,
      'change_percent': 4.17,
      'open': 12.0,
      'high': 12.6,
      'low': 11.9,
      'volume': 1000,
      'source': 'yahoo_finance',
    };

List<String> texts(PriceQuote q) => quoteProvenanceLines(q).map((e) => e.$1).toList();

void main() {
  test('yeni alanlar ayrıştırılır', () {
    final q = PriceQuote.fromJson(base()
      ..addAll({
        'price_type': 'INTRADAY_BAR_CLOSE',
        'bar_start': '2026-10-05T11:55:00+03:00',
        'interval': '5m',
        'retrieved_at': '2026-10-05T09:14:27+00:00',
        'currency': 'TRY',
        'exchange': 'IST',
        'identity_check': 'MATCH',
        'fallback_used': false,
        'fallback_reason': null,
        'last_trade_at': '2026-10-05T08:59:28+00:00',
      }));
    expect(q.priceType, 'INTRADAY_BAR_CLOSE');
    expect(q.retrievedAt!.toUtc(), DateTime.utc(2026, 10, 5, 9, 14, 27));
    expect(q.lastTradeAt!.toUtc(), DateTime.utc(2026, 10, 5, 8, 59, 28));
    final t = texts(q);
    expect(t, contains('Fiyat türü: gün içi 5 dakikalık bar kapanışı'));
    expect(t.any((l) => l.startsWith('Bar başlangıcı: ')), isTrue);
    expect(t.any((l) => l.startsWith('Alınma zamanı: ') && !l.contains('bilinmiyor')), isTrue);
    expect(t.any((l) => l.contains('Para birimi: TRY') && l.contains('doğrulandı')), isTrue);
    expect(t, contains('Gecikme süresi doğrulanmadı.'));
  });

  test('günlük fallback görünür ve ayrı etiketlenir', () {
    final q = PriceQuote.fromJson(base()
      ..addAll({
        'timestamp': '2026-10-05T00:00:00+03:00',
        'price_type': 'DAILY_BAR_CLOSE',
        'bar_start': '2026-10-05T00:00:00+03:00',
        'interval': '1d',
        'fallback_used': true,
        'fallback_reason': 'INTRADAY_EMPTY',
        'identity_check': 'UNVERIFIED',
      }));
    final lines = quoteProvenanceLines(q);
    final t = lines.map((e) => e.$1).toList();
    expect(t, contains('Fiyat türü: günlük bar kapanışı'));
    expect(t.any((l) => l.startsWith('Bar tarihi: ') && !l.contains(':00')), isTrue);
    expect(lines.firstWhere((e) => e.$1.contains('günlük bar kapanışı gösteriliyor')).$2, isTrue); // uyarı
    expect(t.any((l) => l.contains('Para birimi: bilinmiyor') && l.contains('doğrulanmadı')), isTrue);
    expect(t.any((l) => l.contains('işlem zamanı')), isFalse);
  });

  test('eski backend: alanlar yoksa bilinmiyor gösterilir', () {
    final q = PriceQuote.fromJson(base());
    expect(q.priceType, isNull);
    expect(q.fallbackUsed, isNull);
    final t = texts(q);
    expect(t, contains('Fiyat türü: bilinmiyor (backend bu bilgiyi göndermedi)'));
    expect(t.any((l) => l.contains('anlamı bilinmiyor')), isTrue);
    expect(t, contains('Alınma zamanı: bilinmiyor'));
    expect(t.any((l) => l.contains('Borsa: bilinmiyor')), isTrue);
  });

  testWidgets('ekranda gecikme veya gerçek zamanlı iddiası yok', (tester) async {
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: QuoteProvenance(quote: PriceQuote.fromJson(base())))));
    expect(find.text('Gecikme süresi doğrulanmadı.'), findsOneWidget);
    for (final claim in ['gecikmeli', 'dakika gecik', 'gerçek zamanlı', 'Anlık', 'Son işlem']) {
      expect(find.textContaining(claim), findsNothing, reason: claim);
    }
  });

  test('TL yalnız MATCH + TRY ise', () {
    PriceQuote q(Map<String, dynamic> extra) => PriceQuote.fromJson(base()..addAll(extra));
    expect(formatQuoteAmount(q({'identity_check': 'MATCH', 'currency': 'TRY'}), 12.5), '12.50 TL');
    expect(formatQuoteAmount(q({'identity_check': 'UNVERIFIED', 'currency': 'TRY'}), 12.5), '12.50');
    expect(formatQuoteAmount(q({'identity_check': 'UNVERIFIED'}), 12.5), '12.50');
    expect(formatQuoteAmount(q({'identity_check': 'MATCH', 'currency': 'USD'}), 12.5), '12.50');
    expect(formatQuoteAmount(q({}), 12.5), '12.50');
  });
}
