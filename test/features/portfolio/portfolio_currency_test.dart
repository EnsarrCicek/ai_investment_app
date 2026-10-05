import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/asset_detail/asset_detail_screen.dart';
import 'package:ai_investment_app/features/portfolio/portfolio_history_screen.dart';
import 'package:ai_investment_app/features/portfolio/portfolio_screen.dart';
import 'package:ai_investment_app/models/portfolio_position.dart';
import 'package:ai_investment_app/models/portfolio_transaction.dart';
import 'package:ai_investment_app/models/price_quote.dart';
import 'package:ai_investment_app/services/api/portfolio_api.dart';

// Bu dosya para birimi kurallarını sınar; kâr/zarar sayısının görünmesi için doğrulanmış fixture (verified=true).
PortfolioPosition pos({String? currency, String? cur = 'TRY', String? identity = 'MATCH', String? error, bool verified = true}) =>
    PortfolioPosition.fromJson({
      'asset': 'AAA',
      'buy_price': 10.0,
      'quantity': 5.0,
      'lot_count': 1,
      if (error == null) ...{
        'current_price': 12.0,
        'invested_amount': 50.0,
        'current_value': 60.0,
        'profit_loss': 10.0,
        'return_percent': 20.0,
      },
      'error': error,
      'currency': currency,
      'current_price_currency': cur,
      'current_price_identity_check': identity,
      'pnl_basis_verified': verified,
    });

PriceQuote quote({String? identity, String? currency}) => PriceQuote(
      assetId: 'AAA',
      timestamp: DateTime.utc(2026, 10, 5, 8),
      lastPrice: 12.0,
      previousClose: 11.0,
      change: 1,
      changePercent: 9.09,
      open: 11,
      high: 12,
      low: 11,
      volume: 1,
      source: 'test',
      identityCheck: identity,
      currency: currency,
    );

PortfolioTransaction tx({String? currency}) => PortfolioTransaction.fromJson({
      'asset': 'AAA',
      'quantity': 1.0,
      'buy_price': 10.0,
      'buy_date': '2026-01-01T00:00:00Z',
      'sell_price': 12.0,
      'sell_date': '2026-02-01T00:00:00Z',
      'realized_pnl': 2.0,
      'realized_pnl_percent': 20.0,
      'currency': ?currency,
    });

Future<void> pumpTile(WidgetTester tester, PortfolioPosition p) => tester.pumpWidget(MaterialApp(
      home: Scaffold(body: PortfolioPositionTile(position: p, onEdit: () {}, onClose: () {}, onLimits: () {})),
    ));

final summary = PortfolioSummary.fromJson(
    {'total_invested': 100.0, 'total_current_value': 120.0, 'total_profit_loss': 20.0, 'total_return_percent': 20.0});

void main() {
  group('pozisyon kartı', () {
    testWidgets('1+3+5: kayıtlı TRY + güncel MATCH/TRY → alış, güncel ve K/Z TL', (tester) async {
      await pumpTile(tester, pos(currency: 'TRY'));
      expect(find.text('Ort. Alış: 10.00 TL   Güncel: 12.00 TL'), findsOneWidget);
      expect(find.text('+10 TL'), findsOneWidget);
    });

    testWidgets('2+6: kayıtlı birim yok → alışta ve K/Z\'de TL yok; güncel MATCH ise TL', (tester) async {
      await pumpTile(tester, pos());
      expect(find.text('Ort. Alış: 10.00   Güncel: 12.00 TL'), findsOneWidget);
      expect(find.text('+10'), findsOneWidget);
      expect(find.text('+10 TL'), findsNothing);
    });

    testWidgets('4: UNVERIFIED + TRY → güncel fiyatta ve K/Z\'de TL yok', (tester) async {
      await pumpTile(tester, pos(currency: 'TRY', identity: 'UNVERIFIED'));
      expect(find.text('Ort. Alış: 10.00 TL   Güncel: 12.00'), findsOneWidget);
      expect(find.text('+10'), findsOneWidget);
    });

    test('6: birim uyuşmazlığı veya eski backend → K/Z birimi yok; başka birim ISO kodu', () {
      final mismatch = pos(currency: 'TRY', cur: 'USD');
      expect(mismatch.pnlUnit, isNull);
      expect(mismatch.currentPriceUnit, 'USD');
      expect(pos(currency: 'USD', cur: 'USD').pnlUnit, 'USD');
      final old = PortfolioPosition.fromJson({'asset': 'AAA', 'buy_price': 1.0, 'quantity': 1.0, 'lot_count': 1});
      expect([old.buyPriceUnit, old.currentPriceUnit, old.pnlUnit], [null, null, null]);
    });
  });

  group('özet kartı', () {
    testWidgets('10: karışık/bilinmeyen birim → toplamlarda TL yok', (tester) async {
      final mixed = [pos(currency: 'TRY'), pos()];
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: PortfolioSummaryCard(summary: summary, positions: mixed))));
      expect(find.text('Toplam Yatırım: 100'), findsOneWidget);
      expect(find.text('Güncel Değer: 120 TL'), findsOneWidget); // ikisinde de güncel MATCH/TRY
      expect(find.text('+20'), findsOneWidget);
      expect(summaryUnits([pos(currency: 'TRY'), pos(currency: 'TRY', identity: 'UNVERIFIED')]).current, isNull);
      expect(summaryUnits([pos(currency: 'TRY'), pos(currency: 'USD', cur: 'USD')]).invested, isNull);
    });

    testWidgets('tümü TRY ve doğrulanmış → toplamlarda TL; hatalı pozisyon toplam dışı', (tester) async {
      final all = [pos(currency: 'TRY'), pos(currency: 'TRY'), pos(error: 'veri yok')];
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: PortfolioSummaryCard(summary: summary, positions: all))));
      expect(find.text('Toplam Yatırım: 100 TL'), findsOneWidget);
      expect(summaryUnits(all).pnl, 'TL'); // birim kuralı: hatalı pozisyon birim kararına katılmaz
      // Ancak değerlenemeyen pozisyon varken toplam K/Z doğrulanmış sayı olarak gösterilmez (fail-closed).
      expect(find.text('+20 TL'), findsNothing);
      expect(find.text(pnlUnverifiedTotalText), findsOneWidget);
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(body: PortfolioSummaryCard(summary: summary, positions: all.take(2).toList()))));
      expect(find.text('+20 TL'), findsOneWidget);
      expect(summaryUnits(const []).pnl, isNull);
    });
  });

  group('hızlı alım', () {
    test('7: MATCH + TRY → "Alış Fiyatı (TL)" ve istek currency TRY', () {
      final q = quote(identity: 'MATCH', currency: 'TRY');
      expect(quickBuyPriceLabel(q), 'Alış Fiyatı (TL)');
      final body = PortfolioApi.positionBody(
          asset: 'AAA', buyPrice: 13.0, quantity: 1, buyDate: DateTime.utc(2026), currency: verifiedQuoteCurrency(q));
      expect(body['currency'], 'TRY');
      expect(quickBuyPriceLabel(quote(identity: 'MATCH', currency: 'USD')), 'Alış Fiyatı (USD)');
    });

    test('8: UNVERIFIED / eski backend → "Alış Fiyatı" ve istek currency null', () {
      for (final q in [quote(identity: 'UNVERIFIED', currency: 'TRY'), quote(), quote(identity: 'MATCH')]) {
        expect(quickBuyPriceLabel(q), 'Alış Fiyatı');
        final body = PortfolioApi.positionBody(
            asset: 'AAA', buyPrice: 12.0, quantity: 1, buyDate: DateTime.utc(2026), currency: verifiedQuoteCurrency(q));
        expect(body.containsKey('currency'), isTrue);
        expect(body['currency'], isNull);
      }
    });
  });

  group('geçmiş', () {
    test('9: eski/null currency işlem → birim yok; TRY → TL; karışık → yok', () {
      expect(tx().currency, isNull);
      expect(historyUnits([tx()], const []).realized, isNull);
      expect(historyUnits([tx(currency: 'TRY')], const []).total, 'TL');
      expect(historyUnits([tx(currency: 'TRY'), tx()], const []).realized, isNull);
      expect(historyUnits([tx(currency: 'TRY')], [pos(currency: 'TRY')]).total, 'TL');
      expect(historyUnits([tx(currency: 'TRY')], [pos()]).total, isNull);
      expect(historyUnits([tx(currency: 'USD')], const []).realized, 'USD');
    });
  });
}
