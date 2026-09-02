import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_investment_app/features/asset_detail/asset_detail_screen.dart';
import 'package:ai_investment_app/models/technical_analysis.dart';

// HATA 8C (02.09.2026): HATA 8/8A empirik doğrulaması, mevcut
// investment_horizon (KISA/ORTA/UZUN_VADELI) etiketlerinin gerçek bir
// yatırım vadesi olarak kalibre edilmediğini kanıtladı; bu yüzden "Vade: ..."
// rozeti ve gerekçe metni kullanıcıya artık gösterilmiyor. Bu testler o
// kararı kilitler: backend alanı hâlâ parse edilebilir olmalı (geriye dönük
// uyumluluk/araştırma), ama SignalSummaryCard bunu ASLA render etmemeli.
TechnicalAnalysisDetail _buildData({String? investmentHorizon, String investmentHorizonReason = ''}) {
  return TechnicalAnalysisDetail(
    asset: 'TEST',
    technicalScore: 42.0,
    trend: 'BULLISH',
    confidence: 0.8,
    components: const {},
    indicators: const {},
    marketStructure: 'UPTREND',
    signalClass: 'BULLISH_CONFIRMED',
    trendRegime: 'TRENDING',
    investmentHorizon: investmentHorizon,
    investmentHorizonReason: investmentHorizonReason,
  );
}

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child)));

void main() {
  testWidgets('Vade rozeti UZUN_VADELI icin gosterilmiyor', (tester) async {
    final data = _buildData(
      investmentHorizon: 'UZUN_VADELI',
      investmentHorizonReason: 'Bu benzersiz gerekce metni asla gorunmemeli.',
    );

    await tester.pumpWidget(_wrap(SignalSummaryCard(data: data)));

    expect(find.textContaining('Vade:'), findsNothing);
    expect(find.text('Bu benzersiz gerekce metni asla gorunmemeli.'), findsNothing);
  });

  testWidgets('Vade rozeti KISA_VADELI icin de gosterilmiyor', (tester) async {
    final data = _buildData(investmentHorizon: 'KISA_VADELI', investmentHorizonReason: 'kisa vadeli gerekce');

    await tester.pumpWidget(_wrap(SignalSummaryCard(data: data)));

    expect(find.textContaining('Vade:'), findsNothing);
    expect(find.text('kisa vadeli gerekce'), findsNothing);
  });

  testWidgets('investmentHorizon null olsa bile diger teknik bilgiler gorunur kalir', (tester) async {
    final data = _buildData(investmentHorizon: null, investmentHorizonReason: '');

    await tester.pumpWidget(_wrap(SignalSummaryCard(data: data)));

    expect(find.textContaining('Vade:'), findsNothing);
    expect(find.text('Yükseliş Trendi'), findsOneWidget); // market_structure chip
    expect(find.text('Güçlü/Az Gürültülü'), findsOneWidget); // trend_regime chip
    expect(find.text('Yükseliş Teyitli'), findsOneWidget); // signal_class badge
  });

  testWidgets('field parse edilebilir kaliyor ama render edilmiyor (backward compatibility)', (tester) async {
    final data = _buildData(investmentHorizon: 'UZUN_VADELI', investmentHorizonReason: 'gerekce');

    // Backend/API şekli hâlâ okunabilir olmalı (HATA 8C, madde 2-4: alan
    // silinmedi) -- yalnızca UI'da render edilmemesi doğrulanıyor.
    expect(data.investmentHorizon, 'UZUN_VADELI');
    expect(data.investmentHorizonReason, 'gerekce');

    await tester.pumpWidget(_wrap(SignalSummaryCard(data: data)));
    expect(find.textContaining('Vade:'), findsNothing);
  });
}
