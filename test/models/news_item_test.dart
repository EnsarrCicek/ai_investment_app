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
  });
}
