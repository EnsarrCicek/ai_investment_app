import 'package:ai_investment_app/models/notification_record.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('AL/SAT bildirimini asset alanıyla birlikte doğru ayrıştırır', () {
    final json = {
      'asset': 'TUPRS',
      'kind': 'BUY',
      'title': 'TUPRS: AL sinyali',
      'body': 'Yaklaşık 25 adet (~5000 TL) ALMANIZ önerilir.',
      'created_at': '2026-08-19T12:00:00+00:00',
    };

    final record = NotificationRecord.fromJson(json);

    expect(record.asset, 'TUPRS');
    expect(record.kind, 'BUY');
    expect(record.body, contains('25 adet'));
  });

  test('test bildirimini asset alanı null olarak doğru ayrıştırır', () {
    final json = {
      'asset': null,
      'kind': 'TEST',
      'title': 'Test Bildirimi',
      'body': 'Bildirimler çalışıyor! Bu bir test mesajıdır.',
      'created_at': '2026-08-19T12:00:00+00:00',
    };

    final record = NotificationRecord.fromJson(json);

    expect(record.asset, isNull);
    expect(record.kind, 'TEST');
  });
}
