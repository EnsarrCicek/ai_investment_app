import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/portfolio/portfolio_screen.dart';
import 'package:ai_investment_app/models/portfolio_position.dart';

PortfolioPosition pos({
  bool? basis,
  bool includeBasis = true,
  bool pnl = false,
  String? identity = 'MATCH',
  String? cur = 'TRY',
  String? error,
}) =>
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
      'currency': 'TRY',
      'current_price_currency': cur,
      'current_price_identity_check': identity,
      'pnl_basis_verified': pnl,
      if (includeBasis) 'position_basis_verified': basis,
    });

final summary = PortfolioSummary.fromJson(
    {'total_invested': 100.0, 'total_current_value': 120.0, 'total_profit_loss': 20.0, 'total_return_percent': 20.0});

Future<void> pumpSummary(WidgetTester tester, List<PortfolioPosition> ps) =>
    tester.pumpWidget(MaterialApp(home: Scaffold(body: PortfolioSummaryCard(summary: summary, positions: ps))));

void main() {
  testWidgets('1: pozisyon tabanı doğrulanmamış → toplam güncel değer doğrulanmadı', (tester) async {
    await pumpSummary(tester, [pos(basis: false), pos(basis: false)]);
    expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
    expect(find.textContaining('120'), findsNothing);
    expect(find.text('Girilen Toplam Yatırım: 100 TL'), findsOneWidget); // toplam yatırım kapatılmadı
  });

  testWidgets('2: eski backend (alan yok / null) → doğrulanmadı', (tester) async {
    for (final ps in [
      [pos(includeBasis: false)],
      [pos(basis: null)],
    ]) {
      expect(ps.first.currentValueVerified, isFalse);
      await pumpSummary(tester, ps);
      expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
    }
  });

  testWidgets('3: biri doğrulanmış biri değil → doğrulanmadı', (tester) async {
    await pumpSummary(tester, [pos(basis: true), pos(basis: false)]);
    expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
  });

  testWidgets('4: tümü doğrulanmış + MATCH + aynı birim → sayısal toplam', (tester) async {
    await pumpSummary(tester, [pos(basis: true), pos(basis: true)]);
    expect(find.text('Toplam Güncel Değer: 120 TL'), findsOneWidget);
    expect(find.text(currentValueUnverifiedTotalText), findsNothing);
  });

  testWidgets('5: değerlenemeyen pozisyon varsa kalanlardan doğrulanmış toplam üretilmez', (tester) async {
    await pumpSummary(tester, [pos(basis: true), pos(error: 'veri yok')]);
    expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
  });

  testWidgets('6: karışık birim veya kimlik doğrulanmamış → doğrulanmadı', (tester) async {
    await pumpSummary(tester, [pos(basis: true), pos(basis: true, cur: 'USD')]);
    expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
    await pumpSummary(tester, [pos(basis: true, identity: 'UNVERIFIED')]);
    expect(find.text(currentValueUnverifiedTotalText), findsOneWidget);
  });

  testWidgets('7+8: güncel fiyat gizlenmez; K/Z "Doğrulanmadı" davranışı korunur', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
          body: PortfolioPositionTile(position: pos(basis: false), onEdit: () {}, onClose: () {}, onLimits: () {})),
    ));
    expect(find.text('Girilen Ort. Alış: 10.00 TL   Güncel: 12.00 TL'), findsOneWidget);
    expect(find.text(pnlUnverifiedText), findsOneWidget);
    expect(find.textContaining('+10'), findsNothing);
  });
}
