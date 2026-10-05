import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/portfolio/position_limits_sheet.dart';
import 'package:ai_investment_app/models/portfolio_position.dart';
import 'package:ai_investment_app/models/position_limits.dart';
import 'package:ai_investment_app/services/position_limit_store.dart';

class MemoryBackend implements LimitStorageBackend {
  final Map<String, String> data = {};

  @override
  Future<String?> read(String key) async => data[key];

  @override
  Future<void> write(String key, String content) async => data[key] = content;
}

PortfolioPosition pos({String? version = 'v1'}) =>
    PortfolioPosition(asset: 'AAA', buyPrice: 100, quantity: 10, lotCount: 1, positionVersion: version);

PositionLimits limits({String? version = 'v1', double? profit = 12, double? loss}) =>
    PositionLimits(profitTargetPct: profit, maxLossPct: loss, positionVersion: version, savedAt: DateTime.utc(2025));

const blockedJson = {
  'asset': 'AAA',
  'state': 'DEGERLENDIRILEMEDI',
  'block_code': 'PRICE_BASIS_UNVERIFIED',
  'block_message': 'Fiyat ve alış maliyetinin aynı temelde olduğu doğrulanamadı (veri kaynağı düzeltilmiş fiyat serisi veriyor).',
  'expected_session': '2025-07-11',
  'price_used': null,
  'checks': null,
  'last_known_price': null,
  'notes': <String>[],
};

const withinJson = {
  'asset': 'AAA',
  'state': 'SINIR_ICINDE',
  'expected_session': '2025-07-11',
  'price_used': {'session': '2025-07-11', 'close': 110.0, 'source': 'fake_source', 'price_basis': 'RAW_UNADJUSTED'},
  'checks': {
    'profit_target': {'limit_pct': 10.0, 'gain_pct_vs_cost': 10.0, 'status': 'SINIR_ICINDE'},
    'max_loss': {'limit_pct': null, 'loss_pct_vs_cost': -10.0, 'status': 'SINIR_TANIMLI_DEGIL'},
  },
};

Future<void> pumpSheet(WidgetTester tester, PositionLimitStore store, LimitCheckFn check,
    {PortfolioPosition? position, String? uid = 'u1'}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: PositionLimitsSheet(position: position ?? pos(), uid: uid, store: store, check: check),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('store ve model', () {
    test('hesaplar ayrı; kaydet/kaldır', () async {
      final store = PositionLimitStore(backend: MemoryBackend());
      await store.save('u1', 'aaa', limits());
      expect((await store.load('u1', 'AAA'))!.profitTargetPct, 12);
      expect(await store.load('u2', 'AAA'), isNull);
      await store.remove('u1', 'AAA');
      expect(await store.load('u1', 'AAA'), isNull);
    });

    test('sürüm uyuşmazsa veya bilinmiyorsa pasif', () {
      expect(limits().isActiveFor('v1'), isTrue);
      expect(limits().isActiveFor('v2'), isFalse);
      expect(limits(version: null).isActiveFor(null), isFalse);
    });

    test('girdi doğrulaması: boş tanımsız, pozitif ve üst sınır içinde', () {
      expect(validateLimitInput('', max: 100), isNull);
      expect(validateLimitInput('8,5', max: 100), isNull);
      expect(parseLimitInput('8,5'), 8.5);
      for (final bad in ['0', '-1', '101', 'abc']) {
        expect(validateLimitInput(bad, max: 100), isNotNull);
      }
    });

    test('sonuç ayrıştırma', () {
      final r = LimitCheckResult.fromJson(Map<String, dynamic>.from(withinJson));
      expect(r.state, LimitCheckResult.within);
      expect(r.priceSession, '2025-07-11');
      expect(r.profitTarget!.valuePct, 10.0);
      expect(r.maxLoss!.status, 'SINIR_TANIMLI_DEGIL');
    });
  });

  group('ekran', () {
    testWidgets('sınır yokken bilgilendirme ve tanımsız durumu; kontrol kapalı', (tester) async {
      await pumpSheet(tester, PositionLimitStore(backend: MemoryBackend()), _neverCalled);
      expect(find.byKey(const Key('limits_notice')), findsOneWidget);
      expect(find.textContaining('telefon bildirimi bu sürümde aktif değildir'), findsOneWidget);
      expect(find.byKey(const Key('limits_none')), findsOneWidget);
      expect(tester.widget<OutlinedButton>(find.byKey(const Key('limits_check'))).onPressed, isNull);
      expect(find.text('10'), findsNothing); // varsayılan değer doldurulmaz
    });

    testWidgets('kaydet -> kontrol: engel nedeni ve seans gösterilir', (tester) async {
      final store = PositionLimitStore(backend: MemoryBackend());
      Map<String, Object?>? sent;
      Future<LimitCheckResult> check({required String asset, required String positionVersion, double? profitTargetPct, double? maxLossPct}) async {
        sent = {'asset': asset, 'v': positionVersion, 'p': profitTargetPct, 'l': maxLossPct};
        return LimitCheckResult.fromJson(Map<String, dynamic>.from(blockedJson));
      }

      await pumpSheet(tester, store, check);
      await tester.enterText(find.byKey(const Key('loss_field')), '8');
      await tester.tap(find.byKey(const Key('limits_save')));
      await tester.pumpAndSettle();
      expect((await store.load('u1', 'AAA'))!.maxLossPct, 8);
      await tester.tap(find.byKey(const Key('limits_check')));
      await tester.pumpAndSettle();
      expect(sent, {'asset': 'AAA', 'v': 'v1', 'p': null, 'l': 8.0});
      expect(find.text('Durum: Değerlendirilemedi'), findsOneWidget);
      expect(find.textContaining('aynı temelde olduğu doğrulanamadı'), findsOneWidget);
      expect(find.text('Beklenen son tamamlanmış seans: 2025-07-11'), findsOneWidget);
    });

    testWidgets('pozisyon değiştiyse sınır pasif, kontrol kapalı', (tester) async {
      final store = PositionLimitStore(backend: MemoryBackend());
      await store.save('u1', 'AAA', limits(version: 'eski'));
      await pumpSheet(tester, store, _neverCalled);
      expect(find.byKey(const Key('limits_passive')), findsOneWidget);
      expect(tester.widget<OutlinedButton>(find.byKey(const Key('limits_check'))).onPressed, isNull);
    });

    testWidgets('başka hesabın sınırı görünmez', (tester) async {
      final store = PositionLimitStore(backend: MemoryBackend());
      await store.save('u1', 'AAA', limits(profit: 15));
      await pumpSheet(tester, store, _neverCalled, uid: 'u2');
      expect(find.byKey(const Key('limits_none')), findsOneWidget);
      expect(find.text('15.0'), findsNothing);
    });

    testWidgets('yeni kontrol başarısızsa eski sonuç gösterilmez; kaldır sınırı siler', (tester) async {
      final store = PositionLimitStore(backend: MemoryBackend());
      await store.save('u1', 'AAA', limits(profit: 10));
      var fail = false;
      Future<LimitCheckResult> check({required String asset, required String positionVersion, double? profitTargetPct, double? maxLossPct}) async {
        if (fail) throw Exception('ağ yok');
        return LimitCheckResult.fromJson(Map<String, dynamic>.from(withinJson));
      }

      await pumpSheet(tester, store, check);
      await tester.tap(find.byKey(const Key('limits_check')));
      await tester.pumpAndSettle();
      expect(find.text('Durum: Sınır içinde'), findsOneWidget);
      expect(find.textContaining('kaynak: fake_source'), findsOneWidget);
      expect(find.textContaining('net kazanç değildir'), findsOneWidget);
      fail = true;
      await tester.tap(find.byKey(const Key('limits_check')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('limits_result')), findsNothing);
      expect(find.textContaining('Kontrol yapılamadı'), findsOneWidget);
      await tester.tap(find.byKey(const Key('limits_remove')));
      await tester.pumpAndSettle();
      expect(await store.load('u1', 'AAA'), isNull);
      expect(find.byKey(const Key('limits_none')), findsOneWidget);
    });

    testWidgets('sunucu pozisyon değişti derse eski başarılı sonuç kalmaz', (tester) async {
      final store = PositionLimitStore(backend: MemoryBackend());
      await store.save('u1', 'AAA', limits(profit: 10));
      var changed = false;
      Future<LimitCheckResult> check({required String asset, required String positionVersion, double? profitTargetPct, double? maxLossPct}) async {
        if (!changed) return LimitCheckResult.fromJson(Map<String, dynamic>.from(withinJson));
        return LimitCheckResult.fromJson({
          'asset': 'AAA',
          'state': 'DEGERLENDIRILEMEDI',
          'block_code': 'POSITION_CHANGED',
          'block_message': 'Pozisyon, sınırlar kaydedildikten sonra değişmiş. Sınırları yeniden onaylayın.',
        });
      }

      await pumpSheet(tester, store, check);
      await tester.tap(find.byKey(const Key('limits_check')));
      await tester.pumpAndSettle();
      expect(find.text('Durum: Sınır içinde'), findsOneWidget);
      changed = true;
      await tester.tap(find.byKey(const Key('limits_check')));
      await tester.pumpAndSettle();
      expect(find.text('Durum: Sınır içinde'), findsNothing);
      expect(find.text('Durum: Değerlendirilemedi'), findsOneWidget);
      expect(find.textContaining('yeniden onaylayın'), findsOneWidget);
      expect(find.textContaining('kaynak: fake_source'), findsNothing);
    });
  });
}

Future<LimitCheckResult> _neverCalled({required String asset, required String positionVersion, double? profitTargetPct, double? maxLossPct}) =>
    Future.error(StateError('çağrılmamalı'));
