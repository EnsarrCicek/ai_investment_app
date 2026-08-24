import 'package:ai_investment_app/models/news_analysis.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('NewsAnalysis tüm alanları doğru ayrıştırır', () {
    final json = {
      'news_id': 'abc-123',
      'sentiment_score': 58.0,
      'confidence': 0.84,
      'importance': 0.82,
      'event_type': 'earnings',
      'time_horizon': 'short_term',
      'sentiment_label': 'positive',
      'reasoning': 'Güçlü yolcu büyümesi ve artan gelirler.',
      'model_used': 'gpt-5.6-luna',
      'created_at': '2026-08-18T12:00:00+00:00',
    };

    final analysis = NewsAnalysis.fromJson(json);

    expect(analysis.newsId, 'abc-123');
    expect(analysis.sentimentScore, 58.0);
    expect(analysis.confidence, 0.84);
    expect(analysis.importance, 0.82);
    expect(analysis.eventType, 'earnings');
    expect(analysis.timeHorizon, 'short_term');
    expect(analysis.sentimentLabel, 'positive');
    expect(analysis.reasoning, 'Güçlü yolcu büyümesi ve artan gelirler.');
    expect(analysis.modelUsed, 'gpt-5.6-luna');
  });

  test('time_horizon/sentiment_label eksikse geriye dönük uyumlu varsayılana düşer', () {
    final json = {
      'news_id': 'old-1',
      'sentiment_score': 10.0,
      'confidence': 0.6,
      'importance': 0.3,
      'event_type': 'other',
      'reasoning': 'Eski kayıt, bu alanlar eklenmeden önce oluşturulmuş.',
      'model_used': 'gpt-5.6-luna',
      'created_at': '2026-08-18T12:00:00+00:00',
    };

    final analysis = NewsAnalysis.fromJson(json);

    expect(analysis.timeHorizon, 'medium_term');
    expect(analysis.sentimentLabel, 'neutral');
  });
}
