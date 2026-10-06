import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/portfolio/portfolio_history_screen.dart';
import 'package:ai_investment_app/features/portfolio/portfolio_screen.dart';
import 'package:ai_investment_app/models/portfolio_position.dart';

PortfolioPosition pos({bool? verified, bool includeField = true, String? error}) => PortfolioPosition.fromJson({
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
      'currency': 'TRY',
      'current_price_currency': 'TRY',
      'current_price_identity_check': 'MATCH',
      'current_price_basis': 'PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST',
      if (includeField) 'pnl_basis_verified': verified,
    });

final summary = PortfolioSummary.fromJson(
    {'total_invested': 100.0, 'total_current_value': 120.0, 'total_profit_loss': 20.0, 'total_return_percent': 20.0});

Future<void> pumpTile(WidgetTester tester, PortfolioPosition p) => tester.pumpWidget(MaterialApp(
      home: Scaffold(body: PortfolioPositionTile(position: p, onEdit: () {}, onClose: () {}, onLimits: () {})),
    ));

Future<void> pumpSummary(WidgetTester tester, List<PortfolioPosition> ps) =>
    tester.pumpWidget(MaterialApp(home: Scaffold(body: PortfolioSummaryCard(summary: summary, positions: ps))));

void main() {
  testWidgets('1: doğrulanmamış K/Z sayı olarak gösterilmez', (tester) async {
    await pumpTile(tester, pos(verified: false));
    expect(find.text(pnlUnverifiedText), findsOneWidget);
    expect(find.text(pnlUnverifiedNote), findsOneWidget);
    expect(find.text('+10 TL'), findsNothing);
    expect(find.textContaining('+10'), findsNothing);
    expect(find.text('Girilen Ort. Alış: 10.00 TL   Güncel: 12.00 TL'), findsOneWidget); // para birimi kuralları korunur
  });

  testWidgets('2: eski backend (alan yok / null) → doğrulanmadı', (tester) async {
    for (final p in [pos(includeField: false), pos(verified: null)]) {
      expect(p.pnlVerified, isFalse);
      await pumpTile(tester, p);
      expect(find.text(pnlUnverifiedText), findsOneWidget);
      expect(find.textContaining('+10'), findsNothing);
    }
  });

  testWidgets('3: doğrulanmış fixture → mevcut sayısal görünüm', (tester) async {
    await pumpTile(tester, pos(verified: true));
    expect(find.text('+10 TL'), findsOneWidget);
    expect(find.text(pnlUnverifiedText), findsNothing);
  });

  testWidgets('4: özette tek doğrulanmamış pozisyon → toplam K/Z doğrulanmadı', (tester) async {
    await pumpSummary(tester, [pos(verified: true), pos(verified: false)]);
    expect(find.text(pnlUnverifiedTotalText), findsOneWidget);
    expect(find.text('+20 TL'), findsNothing);
    expect(find.text('%20.0'), findsNothing);
    expect(find.text('Girilen Toplam Yatırım: 100 TL'), findsOneWidget); // yatırım/güncel değer değişmedi
  });

  testWidgets('4b: değerlenemeyen pozisyon toplamdan sessizce çıkarılıp doğrulanmış sayılmaz', (tester) async {
    await pumpSummary(tester, [pos(verified: true), pos(error: 'veri yok')]);
    expect(find.text(pnlUnverifiedTotalText), findsOneWidget);
  });

  testWidgets('5: tümü doğrulanmış → mevcut toplam görünümü', (tester) async {
    await pumpSummary(tester, [pos(verified: true), pos(verified: true)]);
    expect(find.text('+20 TL'), findsOneWidget);
    expect(find.text('%20.0'), findsOneWidget);
    expect(find.text(pnlUnverifiedTotalText), findsNothing);
  });

  test('geçmiş: açık K/Z doğrulaması (alınamadı / boş / doğrulanmamış / doğrulanmış)', () {
    expect(openPnlVerified(null), isFalse);
    expect(openPnlVerified(const []), isTrue); // açık pozisyon yok: değer gerçekten 0
    expect(openPnlVerified([pos(verified: false)]), isFalse);
    expect(openPnlVerified([pos(verified: true)]), isTrue);
  });
}
