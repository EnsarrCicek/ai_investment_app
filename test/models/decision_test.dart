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

  test('28.08.2026 (HATA 5C3B): channel_completeness mevcutken doğru ayrıştırılır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': 80.0,
      'news_score': -80.0,
      'macro_score': null,
      'final_score': 20.0,
      'decision': 'WEAK_BUY',
      'confidence': 62.5,
      'channel_completeness': 0.8,
    };

    final decision = Decision.fromJson(json);
    expect(decision.confidence, 62.5);
    expect(decision.channelCompleteness, 0.8);
  });

  test('28.08.2026 (HATA 5C3B): channel_completeness eklenmeden önceki kayıtlarda null olarak geriye dönük uyumludur', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -30.2,
      'news_score': null,
      'macro_score': -8.4,
      'final_score': -21.1,
      'decision': 'WEAK_SELL',
      'confidence': 58.1,
    };

    final decision = Decision.fromJson(json);
    expect(decision.channelCompleteness, isNull);
  });

  test('31.08.2026 (HATA 5C-UI2): decision_engine_version mevcutken doğru ayrıştırılır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': 80.0,
      'news_score': -80.0,
      'macro_score': null,
      'final_score': 20.0,
      'decision': 'WEAK_BUY',
      'confidence': 62.5,
      'channel_completeness': 0.8,
      'decision_engine_version': '1.1.0',
    };

    final decision = Decision.fromJson(json);
    expect(decision.decisionEngineVersion, '1.1.0');
  });

  test('31.08.2026 (HATA 5C-UI2): decision_engine_version eklenmeden önceki kayıtlarda null olarak geriye dönük uyumludur', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -30.2,
      'news_score': null,
      'macro_score': -8.4,
      'final_score': -21.1,
      'decision': 'WEAK_SELL',
      'confidence': 58.1,
    };

    final decision = Decision.fromJson(json);
    expect(decision.decisionEngineVersion, isNull);
  });
}
