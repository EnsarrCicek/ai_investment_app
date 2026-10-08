import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/portfolio/portfolio_history_screen.dart';
import 'package:ai_investment_app/features/portfolio/portfolio_screen.dart';
import 'package:ai_investment_app/features/portfolio/position_sell_dialog.dart';
import 'package:ai_investment_app/models/portfolio_position.dart';
import 'package:ai_investment_app/models/portfolio_transaction.dart';
import 'package:ai_investment_app/services/api/portfolio_api.dart';

PortfolioPosition pos({double qty = 150, String? version = 'v1', String? currency = 'TRY'}) => PortfolioPosition.fromJson({
      'asset': 'AAA',
      'buy_price': 10.0,
      'quantity': qty,
      'lot_count': 1,
      'current_price': 12.0,
      'invested_amount': qty * 10,
      'current_value': qty * 12,
      'profit_loss': qty * 2,
      'return_percent': 20.0,
      'position_version': version,
      'currency': currency,
      'current_price_currency': 'TRY',
      'current_price_identity_check': 'MATCH',
    });

PortfolioTransaction tx({double qty = 60, bool? verified, String? method = 'WEIGHTED_AVERAGE'}) => PortfolioTransaction.fromJson({
      'asset': 'AAA',
      'quantity': qty,
      'buy_price': 13.333333,
      'buy_date': '2026-01-01T00:00:00Z',
      'sell_price': 25.0,
      'sell_date': '2026-02-01T00:00:00Z',
      'realized_pnl': 700.0,
      'realized_pnl_percent': 87.5,
      'currency': 'TRY',
      'basis_verified': ?verified,
      'disposal_method': ?method,
    });

class SellCall {
  final String asset;
  final double quantity;
  final double sellPrice;
  final String positionVersion;
  final String? currency;

  SellCall(this.asset, this.quantity, this.sellPrice, this.positionVersion, this.currency);
}

class FakeSell {
  final calls = <SellCall>[];
  Object? error;

  Future<PortfolioTransaction> call({
    required String asset,
    required double quantity,
    required double sellPrice,
    required String positionVersion,
    String? currency,
    DateTime? sellDate,
  }) async {
    calls.add(SellCall(asset, quantity, sellPrice, positionVersion, currency));
    final e = error;
    if (e != null) throw e;
    return tx(qty: quantity, verified: false);
  }
}

class FakePortfolioApi implements PortfolioApi {
  int fetchCalls = 0;
  List<PortfolioPosition> positions;
  List<PortfolioTransaction> transactions;
  final FakeSell seller = FakeSell();

  FakePortfolioApi({required this.positions, this.transactions = const []});

  @override
  Future<(List<PortfolioPosition>, PortfolioSummary)> fetchPositions() async {
    fetchCalls++;
    return (
      positions,
      PortfolioSummary.fromJson(
          {'total_invested': 1500.0, 'total_current_value': 1800.0, 'total_profit_loss': 300.0, 'total_return_percent': 20.0}),
    );
  }

  @override
  Future<PortfolioTransaction> sellPosition({
    required String asset,
    required double quantity,
    required double sellPrice,
    required String positionVersion,
    String? currency,
    DateTime? sellDate,
  }) =>
      seller.call(
          asset: asset, quantity: quantity, sellPrice: sellPrice, positionVersion: positionVersion, currency: currency);

  @override
  Future<PortfolioHistorySummary> fetchHistory() async => PortfolioHistorySummary(
      transactions: transactions, totalRealizedPnl: transactions.fold(0.0, (a, t) => a + t.realizedPnl));

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

SellDialogResult? lastResult;

Future<void> openDialog(WidgetTester tester, PortfolioPosition p, FakeSell sell) async {
  lastResult = null;
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(
        builder: (ctx) => TextButton(
          onPressed: () async {
            lastResult = await showDialog<SellDialogResult>(
                context: ctx, builder: (_) => PositionSellDialog(position: p, sell: sell.call));
          },
          child: const Text('open'),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}

Future<void> fillAndSubmit(WidgetTester tester, {String? qty, String? price}) async {
  if (qty != null) await tester.enterText(find.byKey(const Key('sell_quantity')), qty);
  if (price != null) await tester.enterText(find.byKey(const Key('sell_price')), price);
  await tester.tap(find.byKey(const Key('sell_submit')));
  await tester.pumpAndSettle();
}

const staleBody = '{"detail": {"code": "POSITION_CHANGED", "message": "Pozisyon değişmiş."}}';

void main() {
  group('satış dialogu', () {
    testWidgets('1: mevcut adet gösterilir; 10: TRY -> "Satış Fiyatı (TL)"', (tester) async {
      await openDialog(tester, pos(), FakeSell());
      expect(find.text('Mevcut adet: 150'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Satış Fiyatı (TL)'), findsOneWidget);
    });

    testWidgets('10: para birimi bilinmiyorsa "Satış Fiyatı"', (tester) async {
      await openDialog(tester, pos(currency: null), FakeSell());
      expect(find.widgetWithText(TextField, 'Satış Fiyatı'), findsOneWidget);
      expect(find.textContaining('(TL)'), findsNothing);
    });

    testWidgets('2: 150 pozisyonda 60 satış isteği', (tester) async {
      final sell = FakeSell();
      await openDialog(tester, pos(), sell);
      await fillAndSubmit(tester, qty: '60', price: '25,5');
      expect(sell.calls, hasLength(1));
      final c = sell.calls.single;
      expect([c.asset, c.quantity, c.sellPrice, c.positionVersion, c.currency], ['AAA', 60.0, 25.5, 'v1', 'TRY']);
      expect(lastResult, isA<SellCompleted>());
    });

    testWidgets('4: Tümü ile tam satış aynı /sell yolundan', (tester) async {
      final sell = FakeSell();
      await openDialog(tester, pos(), sell);
      await tester.tap(find.byKey(const Key('sell_all')));
      await tester.pump();
      await fillAndSubmit(tester);
      expect(sell.calls.single.quantity, 150.0);
    });

    testWidgets('5-7: fazla, sıfır, negatif adet gönderilmez; dialog açık kalır', (tester) async {
      final sell = FakeSell();
      await openDialog(tester, pos(), sell);
      await fillAndSubmit(tester, qty: '151');
      expect(find.text(sellExceedsText), findsOneWidget);
      for (final bad in ['0', '-5']) {
        await fillAndSubmit(tester, qty: bad);
        expect(find.byKey(const Key('sell_error')), findsOneWidget);
      }
      expect(sell.calls, isEmpty);
      expect(find.byType(PositionSellDialog), findsOneWidget);
    });

    testWidgets('5b: backend 422 (adet fazla) güvenli gösterilir, dialog kapanmaz', (tester) async {
      final sell = FakeSell()
        ..error = PortfolioApi.parseSellError(
            422, '{"detail": {"code": "QUANTITY_EXCEEDS_AVAILABLE", "message": "Satış adedi mevcut adetten fazla."}}');
      await openDialog(tester, pos(), sell);
      await fillAndSubmit(tester, qty: '100');
      expect(find.text(sellExceedsText), findsOneWidget);
      expect(find.byType(PositionSellDialog), findsOneWidget);
      expect(lastResult, isNull);
    });

    testWidgets('8: POSITION_CHANGED -> dialog kapanır, otomatik yeniden deneme yok', (tester) async {
      final sell = FakeSell()..error = PortfolioApi.parseSellError(409, staleBody);
      await openDialog(tester, pos(), sell);
      await fillAndSubmit(tester, qty: '60');
      expect(sell.calls, hasLength(1));
      expect(lastResult, isA<SellPositionChanged>());
      expect((lastResult as SellPositionChanged).message, 'Pozisyon değişti. Güncel bilgiler yeniden yüklendi.');
    });

    testWidgets('9: pozisyon sürümü yoksa (eski backend) satış isteği gönderilmez', (tester) async {
      final sell = FakeSell();
      await openDialog(tester, pos(version: null), sell);
      expect(find.text(sellVersionUnavailableText), findsOneWidget);
      expect(tester.widget<FilledButton>(find.byKey(const Key('sell_submit'))).onPressed, isNull);
      expect(sell.calls, isEmpty);
    });
  });

  group('portföy ekranı', () {
    Future<FakePortfolioApi> pumpScreen(WidgetTester tester) async {
      final api = FakePortfolioApi(positions: [pos()]);
      await tester.pumpWidget(MaterialApp(home: PortfolioScreen(api: api, loadSymbols: () async => const <String>[])));
      await tester.pumpAndSettle();
      return api;
    }

    testWidgets('3: başarılı kısmi satış sonrası portföy backend\'den yeniden yüklenir', (tester) async {
      final api = await pumpScreen(tester);
      expect(api.fetchCalls, 1);
      api.positions = [pos(qty: 90, version: 'v2')]; // kalan adet yalnız backend yenilemesinden gelir
      await tester.tap(find.byTooltip('Sattım'));
      await tester.pumpAndSettle();
      await fillAndSubmit(tester, qty: '60', price: '25');
      expect(api.seller.calls.single.quantity, 60.0);
      expect(api.fetchCalls, 2);
      expect(find.textContaining('AAA  •  90 adet'), findsOneWidget);
      expect(find.textContaining('60 adet satış kaydedildi'), findsOneWidget);
    });

    testWidgets('8b: POSITION_CHANGED -> mesaj + yenileme, yeniden deneme yok', (tester) async {
      final api = await pumpScreen(tester);
      api.seller.error = PortfolioApi.parseSellError(409, staleBody);
      await tester.tap(find.byTooltip('Sattım'));
      await tester.pumpAndSettle();
      await fillAndSubmit(tester, qty: '60', price: '25');
      expect(api.seller.calls, hasLength(1));
      expect(api.fetchCalls, 2);
      expect(find.text('Pozisyon değişti. Güncel bilgiler yeniden yüklendi.'), findsOneWidget);
    });
  });

  group('geçmiş', () {
    Future<void> pumpCard(WidgetTester tester, PortfolioTransaction t) => tester.pumpWidget(
        MaterialApp(home: Scaffold(body: SingleChildScrollView(child: PortfolioTransactionCard(transaction: t)))));

    testWidgets('11 + 13: doğrulanmamış K/Z sayısal görünmez; satılan adet ve yöntem görünür', (tester) async {
      for (final t in [tx(verified: false), tx(verified: null), tx(verified: null, method: null)]) {
        await pumpCard(tester, t);
        expect(find.text(realizedUnverifiedText), findsOneWidget);
        expect(find.text(realizedUnverifiedNote), findsOneWidget);
        expect(find.textContaining('700'), findsNothing);
        expect(find.textContaining('kâr edildi'), findsNothing);
        expect(find.textContaining('60 adet'), findsOneWidget);
      }
      await pumpCard(tester, tx(verified: false));
      expect(find.text('Maliyet yöntemi: Ağırlıklı Ortalama'), findsOneWidget);
    });

    testWidgets('12: doğrulanmış K/Z sayısal görünür', (tester) async {
      await pumpCard(tester, tx(verified: true));
      expect(find.textContaining('+700 TL'), findsOneWidget);
      expect(find.text(realizedUnverifiedText), findsNothing);
      expect(find.textContaining('60 adet alındı'), findsOneWidget);
    });

    test('14: tek doğrulanmamış işlem varsa gerçekleşen toplam doğrulanmış sayılmaz', () {
      expect(realizedPnlVerified([tx(verified: true), tx(verified: false)]), isFalse);
      expect(realizedPnlVerified([tx(verified: true)]), isTrue);
      expect(realizedPnlVerified(const []), isTrue);
    });

    testWidgets('14b: geçmiş özetinde gerçekleşen ve toplam K/Z doğrulanmadı', (tester) async {
      final verifiedOpen = PortfolioPosition.fromJson({
        'asset': 'AAA', 'buy_price': 10.0, 'quantity': 90.0, 'lot_count': 1, 'current_price': 12.0,
        'invested_amount': 900.0, 'current_value': 1080.0, 'profit_loss': 180.0, 'return_percent': 20.0,
        'pnl_basis_verified': true,
      });
      final api = FakePortfolioApi(positions: [verifiedOpen], transactions: [tx(verified: false)]);
      await tester.pumpWidget(MaterialApp(home: PortfolioHistoryScreen(api: api)));
      await tester.pumpAndSettle();
      expect(find.text('Doğrulanmadı'), findsNWidgets(2)); // gerçekleşen + toplam; açık K/Z doğrulanmış
      expect(find.textContaining('+700'), findsNothing);
      expect(find.textContaining('+880'), findsNothing);
    });
  });
}
