import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/asset_detail/asset_detail_screen.dart';
import 'package:ai_investment_app/models/price_quote.dart';
import 'package:ai_investment_app/services/api/market_data_api.dart';

// Fiyat sekmesi otomatik yenileme: 60 sn aralık, yalnızca fiyat + değişim
// (grafik geçmişi değil), yalnızca sekme seçili + rota en üstte + uygulama ön
// plandayken; çakışan istek yok; hatada son başarılı veri korunur.
class _FakeMarketDataApi implements MarketDataApi {
  int quoteCalls = 0;
  int changesCalls = 0;
  int historyCalls = 0;
  double nextPrice = 10;
  Object? quoteError;
  Completer<PriceQuote>? heldQuote;
  // Varsayılan: sağlayıcı kimliği doğrulanmış TRY (fiyat yanında "TL" gösterimi bu koşula bağlı).
  String? identityCheck = 'MATCH';
  String? currency = 'TRY';

  @override
  Future<PriceQuote> fetchQuote(String symbol) {
    quoteCalls++;
    final held = heldQuote;
    if (held != null) return held.future;
    final error = quoteError;
    if (error != null) return Future.error(error);
    return Future.value(quoteFor(symbol, nextPrice, identityCheck: identityCheck, currency: currency));
  }

  @override
  Future<Map<String, double?>> fetchChanges(String symbol) {
    changesCalls++;
    return Future.value({'1d': 1.0});
  }

  @override
  Future<List<PriceBar>> fetchHistory(String symbol, {required String period, required String interval}) {
    historyCalls++;
    return Future.value(const <PriceBar>[]);
  }

  static PriceQuote quoteFor(String symbol, double price, {String? identityCheck = 'MATCH', String? currency = 'TRY'}) =>
      PriceQuote(
        assetId: symbol,
        timestamp: DateTime.utc(2026, 9, 24, 8),
        lastPrice: price,
        previousClose: price,
        change: 0,
        changePercent: 0,
        open: price,
        high: price,
        low: price,
        volume: 1000,
        source: 'test',
        identityCheck: identityCheck,
        currency: currency,
      );
}

const _minute = Duration(seconds: 60);

Future<void> _open(WidgetTester tester, _FakeMarketDataApi api, {String symbol = 'THYAO'}) async {
  await tester.pumpWidget(MaterialApp(home: AssetDetailScreen(symbol: symbol, marketDataApi: api)));
  await tester.pump();
}

// Zamanlayıcı ve dinleyicilerin dispose'da temizlendiğini de doğrular: tree
// kaldırıldıktan sonra bekleyen timer kalırsa flutter_test testi düşürür.
Future<void> _close(WidgetTester tester) => tester.pumpWidget(const SizedBox());

void main() {
  testWidgets('ilk açılış tek istek; her 60 sn yalnızca fiyat+değişim yenilenir, grafik geçmişi değil',
      (tester) async {
    final api = _FakeMarketDataApi();
    await _open(tester, api);
    expect((api.quoteCalls, api.changesCalls, api.historyCalls), (1, 1, 1));
    expect(find.text('10.00 TL'), findsOneWidget);

    api.nextPrice = 11;
    await tester.pump(const Duration(seconds: 59));
    expect(api.quoteCalls, 1);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect((api.quoteCalls, api.changesCalls, api.historyCalls), (2, 2, 1));
    expect(find.text('11.00 TL'), findsOneWidget);

    await tester.pump(_minute);
    await tester.pump();
    expect((api.quoteCalls, api.historyCalls), (3, 1));
    await _close(tester);
  });

  testWidgets('otomatik yenileme sırasında mevcut veri yükleme göstergesiyle kaldırılmaz; çakışan istek başlamaz',
      (tester) async {
    final api = _FakeMarketDataApi();
    await _open(tester, api);

    api.heldQuote = Completer<PriceQuote>();
    await tester.pump(_minute);
    expect(api.quoteCalls, 2);
    expect(find.text('10.00 TL'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    // İstek bekliyorken ne sonraki tick ne elle yenileme yeni fiyat isteği açar.
    await tester.pump(_minute);
    expect(api.quoteCalls, 2);
    await tester.fling(find.text('10.00 TL'), const Offset(0, 400), 1000);
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(api.quoteCalls, 2);

    api.heldQuote!.complete(_FakeMarketDataApi.quoteFor('THYAO', 12));
    api.heldQuote = null;
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('12.00 TL'), findsOneWidget);
    await _close(tester);
  });

  testWidgets('otomatik yenileme hatasında son başarılı veri kalır, snackbar yok', (tester) async {
    final api = _FakeMarketDataApi();
    await _open(tester, api);

    api.quoteError = Exception('HTTP 503');
    await tester.pump(_minute);
    await tester.pump();
    expect(api.quoteCalls, 2);
    expect(find.text('10.00 TL'), findsOneWidget);
    expect(find.textContaining('son başarılı veri gösteriliyor'), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);

    await tester.pump(_minute);
    await tester.pump();
    expect(find.text('10.00 TL'), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);

    api.quoteError = null;
    api.nextPrice = 13;
    await tester.pump(_minute);
    await tester.pump();
    expect(find.text('13.00 TL'), findsOneWidget);
    expect(find.textContaining('son başarılı veri gösteriliyor'), findsNothing);
    await _close(tester);
  });

  testWidgets('arka planda istek yok; dönüşte veri 60 sn+ bayatsa tek yenileme, taze ise hiç', (tester) async {
    final api = _FakeMarketDataApi();
    await _open(tester, api);

    // Kısa arka plan (<60 sn): dönüşte yenileme yok.
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 30));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(api.quoteCalls, 1);

    // Uzun arka plan: hiçbir periyodik istek yok; dönüşte tam bir yenileme.
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(minutes: 5));
    expect(api.quoteCalls, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(api.quoteCalls, 2);

    // Zamanlayıcılar birikmedi: sonraki 60 sn'de yalnızca bir istek.
    await tester.pump(_minute);
    expect(api.quoteCalls, 3);
    await _close(tester);
  });

  testWidgets('üstte başka sayfa açıkken istek yok; geri dönüşte bayatsa tek yenileme', (tester) async {
    final api = _FakeMarketDataApi();
    await _open(tester, api);

    final navigator = tester.state<NavigatorState>(find.byType(Navigator).first);
    navigator.push(MaterialPageRoute<void>(builder: (_) => const Scaffold(body: Text('ust sayfa'))));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(minutes: 3));
    expect(api.quoteCalls, 1);

    navigator.pop();
    await tester.pumpAndSettle();
    expect(api.quoteCalls, 2);
    await tester.pump(_minute);
    expect(api.quoteCalls, 3);
    await _close(tester);
  });

  testWidgets('başka sekme seçiliyken fiyat isteği yok', (tester) async {
    final api = _FakeMarketDataApi();
    await tester.pumpWidget(
        MaterialApp(home: AssetDetailScreen(symbol: 'THYAO', marketDataApi: api, initialTabIndex: 0)));
    await tester.pump();
    final controller = DefaultTabController.of(tester.element(find.text('10.00 TL')));

    // Sekme henüz ekranda (animasyon) iken bile seçim değişince durur.
    controller.index = 3;
    await tester.pump(const Duration(minutes: 3));
    expect(api.quoteCalls, 1);
    await _close(tester);
  });

  testWidgets('ekran kapandıktan sonra gelen yanıt hata üretmez; eski varlığın yanıtı yenisini ezmez',
      (tester) async {
    final api = _FakeMarketDataApi()..heldQuote = Completer<PriceQuote>();
    await _open(tester, api, symbol: 'THYAO');
    final staleThyao = api.heldQuote!;

    api.heldQuote = null;
    api.nextPrice = 20;
    await tester.pumpWidget(MaterialApp(home: AssetDetailScreen(symbol: 'GARAN', marketDataApi: api)));
    await tester.pump();
    expect(find.text('20.00 TL'), findsOneWidget);

    staleThyao.complete(_FakeMarketDataApi.quoteFor('THYAO', 99));
    await tester.pump();
    expect(find.text('20.00 TL'), findsOneWidget);
    expect(find.text('99.00 TL'), findsNothing);

    final late = Completer<PriceQuote>();
    api.heldQuote = late;
    await tester.pump(_minute);
    await _close(tester);
    late.complete(_FakeMarketDataApi.quoteFor('GARAN', 1));
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  group('fiyat yanında para birimi', () {
    for (final (label, identity, currency, expected) in [
      ('MATCH + TRY', 'MATCH', 'TRY', '10.00 TL'),
      ('UNVERIFIED + TRY', 'UNVERIFIED', 'TRY', '10.00'),
      ('UNVERIFIED + null', 'UNVERIFIED', null, '10.00'),
      ('eski backend (alan yok)', null, null, '10.00'),
    ]) {
      testWidgets(label, (tester) async {
        final api = _FakeMarketDataApi()
          ..identityCheck = identity
          ..currency = currency;
        await _open(tester, api);
        // Ana fiyat satırı (büyük yazı); açılış/yüksek/düşük hücreleri ayrı.
        final mainPrice = find.byWidgetPredicate((w) => w is Text && w.style?.fontSize == 32);
        expect(tester.widget<Text>(mainPrice).data, expected);
        if (!expected.endsWith('TL')) {
          expect(find.text('10.00 TL'), findsNothing);
          expect(find.text('Önceki kapanış: 10.00'), findsOneWidget);
          expect(find.textContaining('Para birimi: ${currency ?? 'bilinmiyor'}'), findsOneWidget);
          expect(find.textContaining('doğrulanmadı)'), findsOneWidget);
        } else {
          expect(find.text('Önceki kapanış: 10.00 TL'), findsOneWidget);
        }
        await _close(tester);
      });
    }
  });
}
