import 'package:ai_investment_app/models/decision.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('tüm alanlar doluyken doğru ayrıştırır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -30.2,
      'news_score': null,
      'macro_score': -8.4,
      'final_score': -21.1,
      'decision': 'WEAK_SELL',
      'confidence': 58.1,
      'created_at': '2026-08-17T10:32:23.591826Z',
    };

    final decision = Decision.fromJson(json);

    expect(decision.asset, 'THYAO');
    expect(decision.technicalScore, -30.2);
    expect(decision.newsScore, isNull);
    expect(decision.macroScore, -8.4);
    expect(decision.finalScore, -21.1);
    expect(decision.decision, 'WEAK_SELL');
    expect(decision.confidence, 58.1);
    expect(decision.createdAt, DateTime.parse('2026-08-17T10:32:23.591826Z'));
  });

  test('created_at eksikse null döner (geriye dönük uyumluluk)', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': null,
      'news_score': null,
      'macro_score': null,
      'final_score': 0.0,
      'decision': 'HOLD',
      'confidence': 0.0,
    };

    final decision = Decision.fromJson(json);
    expect(decision.createdAt, isNull);
  });
}
