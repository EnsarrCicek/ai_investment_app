import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/dashboard/dashboard_screen.dart';
import 'package:ai_investment_app/main.dart';
import 'package:ai_investment_app/models/decision_dashboard.dart';
import 'package:ai_investment_app/services/api/decision_api.dart';

Map<String, dynamic> okItem(String asset, double score) => {
      'asset': asset,
      'status': 'OK',
      'reason': null,
      'decision': score >= 40 ? 'BUY' : 'HOLD',
      'final_score': score,
      'confidence': 80.0,
      'channel_completeness': 0.7,
      'technical_score': score,
      'news_score': null,
      'macro_score': -20.0,
      'decision_as_of': '2026-10-09T10:00:00+00:00',
      'decision_engine_version': '1.2.0',
    };

Map<String, dynamic> unavailableItem(String asset) => {
      'asset': asset,
      'status': 'UNAVAILABLE',
      'reason': 'FIRESTORE_QUOTA_EXHAUSTED',
      'decision': null,
      'final_score': null,
      'confidence': null,
      'channel_completeness': null,
      'technical_score': null,
      'news_score': null,
      'macro_score': null,
      'decision_as_of': null,
      'decision_engine_version': null,
    };

DecisionDashboard dashboard(List<Map<String, dynamic>> items, {String mode = 'NORMAL'}) => DecisionDashboard.fromJson({
      'generated_at': '2026-10-09T10:00:00+00:00',
      'mode': mode,
      'reason': mode == 'NORMAL' ? null : 'FIRESTORE_QUOTA_EXHAUSTED',
      'asset_source': 'FIRESTORE',
      'items': items,
    });

class Loader {
  int calls = 0;
  final DecisionDashboard response;

  Loader(this.response);

  Future<DecisionDashboard> call() async {
    calls++;
    return response;
  }
}

Widget app(Widget child) => MaterialApp(home: child);

void main() {
  testWidgets('tek istek ile yüklenir ve kararları gösterir', (tester) async {
    final loader = Loader(dashboard([okItem('AAA', 55), okItem('BBB', 10)]));
    await tester.pumpWidget(app(DashboardScreen(loadDashboard: loader.call)));
    await tester.pumpAndSettle();
    expect(loader.calls, 1);
    expect(find.text('AAA'), findsOneWidget);
    expect(find.text('BBB'), findsOneWidget);
    expect(find.text('Technical: +55'), findsOneWidget);
    expect(find.text('News: Veri yok'), findsNWidgets(2));
    expect(find.textContaining('Güncellendi:'), findsOneWidget);
  });

  testWidgets('çek-yenile tam olarak bir yeni istek atar', (tester) async {
    final loader = Loader(dashboard([okItem('AAA', 55)]));
    await tester.pumpWidget(app(DashboardScreen(loadDashboard: loader.call)));
    await tester.pumpAndSettle();
    await tester.fling(find.byType(ListView), const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(loader.calls, 2);
  });

  testWidgets('kota/eksik veri: sayısal skor veya karar gösterilmez', (tester) async {
    final loader = Loader(dashboard([unavailableItem('AAA')], mode: 'LOCAL_DEGRADED'));
    await tester.pumpWidget(app(DashboardScreen(loadDashboard: loader.call)));
    await tester.pumpAndSettle();
    expect(find.text(quotaUnavailableText), findsOneWidget);
    expect(find.textContaining('Yerel geliştirme modu'), findsOneWidget);
    expect(find.textContaining('Technical:'), findsNothing);
    expect(find.textContaining('Sinyal Mutabakatı'), findsNothing);
    expect(find.textContaining('Neden'), findsNothing);
  });

  testWidgets('hata satırı neden ile gösterilir, skor yok', (tester) async {
    final error = {...unavailableItem('BAD'), 'status': 'ERROR', 'reason': 'fiyat alınamadı'};
    await tester.pumpWidget(app(DashboardScreen(loadDashboard: Loader(dashboard([error])).call)));
    await tester.pumpAndSettle();
    expect(find.text('Veri alınamadı: fiyat alınamadı'), findsOneWidget);
    expect(find.textContaining('Technical:'), findsNothing);
  });

  testWidgets('istek hatası mesajla gösterilir', (tester) async {
    Future<DecisionDashboard> fail() async => throw Exception(DecisionApi.dashboardErrorMessage(
        503, '{"detail": {"code": "FIRESTORE_QUOTA_EXHAUSTED", "message": "x"}}'));
    await tester.pumpWidget(app(DashboardScreen(loadDashboard: fail)));
    await tester.pumpAndSettle();
    expect(find.textContaining('kotası geçici olarak doldu'), findsOneWidget);
  });

  test('503 dışındaki hatalar HTTP koduyla', () {
    expect(DecisionApi.dashboardErrorMessage(500, 'oops'), 'Piyasa analizi alınamadı (HTTP 500)');
  });

  testWidgets('sekme değişimi Analiz verisini yeniden çekmez', (tester) async {
    final loader = Loader(dashboard([okItem('AAA', 55)]));
    final built = <String, int>{};
    Widget probe(String name) => _Probe(name: name, built: built);
    await tester.pumpWidget(app(RootScreen(
      initializeNotifications: false,
      screens: [
        DashboardScreen(loadDashboard: loader.call),
        probe('portfoy'),
        probe('fonlar'),
        probe('makro'),
        probe('ayarlar'),
      ],
    )));
    await tester.pumpAndSettle();
    expect(loader.calls, 1);
    expect(built, isEmpty); // diğer sekmeler açılışta kurulmaz
    await tester.tap(find.text('Portföy'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Analiz'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Portföy'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Analiz'));
    await tester.pumpAndSettle();
    expect(loader.calls, 1);
    expect(built['portfoy'], 2); // Portföy her ziyarette yeniden kurulur (güncel veri)
    expect(find.text('AAA'), findsOneWidget);
  });
}

class _Probe extends StatefulWidget {
  final String name;
  final Map<String, int> built;

  const _Probe({required this.name, required this.built});

  @override
  State<_Probe> createState() => _ProbeState();
}

class _ProbeState extends State<_Probe> {
  @override
  void initState() {
    super.initState();
    widget.built[widget.name] = (widget.built[widget.name] ?? 0) + 1;
  }

  @override
  Widget build(BuildContext context) => Text('probe ${widget.name}');
}
