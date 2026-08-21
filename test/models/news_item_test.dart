import 'package:ai_investment_app/models/news_item.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('NewsItem external_id dahil tüm alanları doğru ayrıştırır', () {
    final json = {
      'external_id': 'yahoo-abc-123',
      'title': 'Şirket rekor kâr açıkladı',
      'summary': 'Detaylı özet burada.',
      'url': 'https://example.com',
      'publisher': 'Test Publisher',
      'source_reliability': 0.8,
      'published_at': '2026-08-18T12:00:00+00:00',
    };

    final item = NewsItem.fromJson(json);

    expect(item.externalId, 'yahoo-abc-123');
    expect(item.title, 'Şirket rekor kâr açıkladı');
    expect(item.publisher, 'Test Publisher');
    expect(item.sourceReliability, 0.8);
    expect(item.isAnalystMention, isFalse);
  });

  test('is_analyst_mention alanı doğru ayrıştırılır', () {
    final json = {
      'external_id': 'google_news:xyz',
      'title': 'HSBC hedef fiyatı yükseltti',
      'summary': '',
      'url': 'https://example.com',
      'publisher': 'Paratic Haber',
      'source_reliability': 0.8,
      'published_at': '2026-08-18T12:00:00+00:00',
      'is_analyst_mention': true,
    };

    final item = NewsItem.fromJson(json);

    expect(item.isAnalystMention, isTrue);
    expect(item.analystFirm, isNull);
  });

  test('analyst_firm alanı doğru ayrıştırılır', () {
    final json = {
      'external_id': 'google_news:abc',
      'title': 'HSBC hedef fiyatı yükseltti',
      'summary': '',
      'url': 'https://example.com',
      'publisher': 'Paratic Haber',
      'source_reliability': 0.8,
      'published_at': '2026-08-18T12:00:00+00:00',
      'is_analyst_mention': true,
      'analyst_firm': 'HSBC',
    };

    final item = NewsItem.fromJson(json);

    expect(item.analystFirm, 'HSBC');
  });
}
