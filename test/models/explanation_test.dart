import 'package:ai_investment_app/models/explanation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('tüm alanlar (ağırlıklar dahil) doğru ayrıştırır', () {
    final json = {
      'asset': 'THYAO',
      'decision': 'BUY',
      'final_score': 42.5,
      'confidence': 71.0,
      'summary': "THYAO için 'AL' kararı verildi.",
      'technical_weight': 0.5,
      'news_weight': 0.3,
      'macro_weight': 0.2,
      'technical_reasons': ['RSI: +12.0 puan, olumlu yönde katkı yapıyor'],
      'macro_reasons': ['DXY: -3.0 puan, nötr'],
      'news_reasons': ['Bilanço/Kâr: beklenti üstü kâr açıklandı (+40 puan)'],
      'missing': [],
    };

    final explanation = Explanation.fromJson(json);

    expect(explanation.decision, 'BUY');
    expect(explanation.technicalWeight, 0.5);
    expect(explanation.newsWeight, 0.3);
    expect(explanation.macroWeight, 0.2);
    expect(explanation.newsReasons, ['Bilanço/Kâr: beklenti üstü kâr açıklandı (+40 puan)']);
  });

  test('ağırlıklar ve news_reasons eksikse (eski/kayıtsız durum) güvenli varsayılana düşer', () {
    final json = {
      'asset': 'THYAO',
      'decision': 'HOLD',
      'final_score': 0.0,
      'confidence': 40.0,
      'summary': "THYAO için 'TUT' kararı verildi.",
      'technical_reasons': <String>[],
      'macro_reasons': <String>[],
      'missing': ['Güncel bir makro veri anlık görüntüsü bulunamadı.'],
    };

    final explanation = Explanation.fromJson(json);

    expect(explanation.technicalWeight, isNull);
    expect(explanation.newsWeight, isNull);
    expect(explanation.macroWeight, isNull);
    expect(explanation.newsReasons, isEmpty);
    expect(explanation.missing, ['Güncel bir makro veri anlık görüntüsü bulunamadı.']);
  });
}
