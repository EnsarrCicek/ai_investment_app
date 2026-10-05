import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/portfolio/position_limits_sheet.dart';
import 'package:ai_investment_app/models/position_limits.dart';

// Sentetik değerler; gerçek bir portföyden alınmadı.
ManualLimitCalc calc({double qty = 10, double cost = 50, required double price, double? target, double? loss}) =>
    ManualLimitCalc(quantity: qty, avgCost: cost, price: price, currency: 'TRY', profitTargetPct: target, maxLossPct: loss);

Future<void> pumpSection(WidgetTester tester) async {
  await tester.pumpWidget(const MaterialApp(
    home: Scaffold(body: SingleChildScrollView(child: ManualLimitCalcSection())),
  ));
}

Future<void> fill(WidgetTester tester, Map<String, String> values, {String? currency = 'TRY'}) async {
  for (final e in values.entries) {
    await tester.enterText(find.byKey(Key(e.key)), e.value);
  }
  if (currency != null) {
    await tester.tap(find.byKey(const Key('manual_currency')));
    await tester.pumpAndSettle();
    await tester.tap(find.text(currency).last);
    await tester.pumpAndSettle();
  }
}

Future<void> tapCalc(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('manual_calc')));
  await tester.tap(find.byKey(const Key('manual_calc')));
  await tester.pumpAndSettle();
}

void main() {
  group('ayrıştırma', () {
    test('virgül veya nokta ondalık; belirsiz/geçersiz reddedilir', () {
      expect(parseManualDecimal('12,5').value, 12.5);
      expect(parseManualDecimal('12.5').value, 12.5);
      expect(parseManualDecimal('7').value, 7);
      for (final bad in ['1.547', '1.547,00', '1,547.00', '-3', '0', '0,0', 'abc', '12,', ' ']) {
        final r = parseManualDecimal(bad);
        expect(r.value, isNull, reason: bad);
        expect(r.error, isNotNull, reason: bad);
      }
      expect(parseManualDecimal('', required: false).error, isNull);
    });

    test('Türkçe gösterim', () {
      expect(formatTr(1234.5), '1.234,50');
      expect(formatTr(-1234567.891), '-1.234.567,89');
      expect(formatTr(0.5), '0,50');
    });
  });

  group('hesap', () {
    test('pozitif fark ve hedef seviyesi; eşitlik aşım değil', () {
      final r = calc(price: 55, target: 10);
      expect(r.totalCost, 500);
      expect(r.comparisonValue, 550);
      expect(r.difference, 50);
      expect(r.differencePct, closeTo(10, 1e-9));
      expect(r.targetLevel, closeTo(55, 1e-9));
      expect(r.profitStatus, LimitCheckResult.within); // %10 == %10
      expect(calc(price: 55, target: 9.99).profitStatus, LimitCheckResult.exceeded);
    });

    test('negatif fark ve zarar sınırı; eşitlik aşım değil', () {
      final r = calc(price: 46, loss: 8);
      expect(r.difference, -40);
      expect(r.differencePct, closeTo(-8, 1e-9));
      expect(r.lossLevel, closeTo(46, 1e-9));
      expect(r.lossStatus, LimitCheckResult.within);
      expect(calc(price: 45.9, loss: 8).lossStatus, LimitCheckResult.exceeded);
      expect(r.profitStatus, isNull);
    });

    test('yuvarlanmadan hesaplanır', () {
      final r = calc(qty: 3, cost: 7.3, price: 7.31);
      expect(r.differencePct, (7.31 / 7.3 - 1) * 100);
      expect(r.difference, 3 * 7.31 - 3 * 7.3);
    });
  });

  group('ekran', () {
    testWidgets('açıklama görünür; hesap sonucu gösterilir; girdi değişince temizlenir', (tester) async {
      await pumpSection(tester);
      expect(find.text(manualNoticeText), findsOneWidget);
      await fill(tester, {'manual_qty': '10', 'manual_cost': '50', 'manual_price': '55', 'manual_profit': '10'});
      await tapCalc(tester);
      expect(find.byKey(const Key('manual_result')), findsOneWidget);
      expect(find.text('Toplam maliyet: 500,00 TRY'), findsOneWidget);
      expect(find.text('Fark: +50,00 TRY'), findsOneWidget);
      expect(find.textContaining('hedef seviyesi 55,00 TRY — sınır içinde'), findsOneWidget);
      expect(find.textContaining('net satış geliri veya net getiri değildir'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('manual_price')), '56');
      await tester.pump();
      expect(find.byKey(const Key('manual_result')), findsNothing);
    });

    testWidgets('geçersiz giriş ve eksik para birimi hata verir, sonuç üretmez', (tester) async {
      await pumpSection(tester);
      await fill(tester, {'manual_qty': '10', 'manual_cost': '1.547', 'manual_price': '55'});
      await tapCalc(tester);
      expect(find.textContaining('Ortalama maliyet: Belirsiz sayı'), findsOneWidget);
      expect(find.byKey(const Key('manual_result')), findsNothing);
      await tester.pumpWidget(const SizedBox()); // temiz durum
      await pumpSection(tester);
      await fill(tester, {'manual_qty': '10', 'manual_cost': '50', 'manual_price': '55'}, currency: null);
      await tapCalc(tester);
      expect(find.text('Para birimi seçin'), findsOneWidget);
      expect(find.byKey(const Key('manual_result')), findsNothing);
    });

    testWidgets('negatif fark ve aşılan zarar sınırı gösterilir', (tester) async {
      await pumpSection(tester);
      await fill(tester, {'manual_qty': '10', 'manual_cost': '50', 'manual_price': '45,9', 'manual_loss': '8'});
      await tapCalc(tester);
      expect(find.text('Fark: -41,00 TRY'), findsOneWidget);
      expect(find.textContaining('sınır seviyesi 46,00 TRY — aşıldı'), findsOneWidget);
    });
  });
}
