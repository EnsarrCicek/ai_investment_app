import 'package:ai_investment_app/models/ipo.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('IpoListing tüm alanları doğru ayrıştırır', () {
    final json = {
      'company_name': 'VEYAS A.Ş.',
      'bist_code': 'VEYAS',
      'detail_url': 'https://halkarz.com/veyas/',
      'date_text': '12-13-14 Ağustos 2026',
      'badge_text': 'Gong!',
    };

    final listing = IpoListing.fromJson(json);

    expect(listing.companyName, 'VEYAS A.Ş.');
    expect(listing.bistCode, 'VEYAS');
    expect(listing.badgeText, 'Gong!');
  });

  test('IpoListing bist_code ve badge_text null olabilir', () {
    final json = {
      'company_name': 'ABC A.Ş.',
      'bist_code': null,
      'detail_url': 'https://halkarz.com/abc/',
      'date_text': 'Hazırlanıyor...',
      'badge_text': null,
    };

    final listing = IpoListing.fromJson(json);

    expect(listing.bistCode, isNull);
    expect(listing.badgeText, isNull);
  });

  test('IpoDetail fields ve demand_results doğru ayrıştırılır', () {
    final json = {
      'company_name': 'VEYAS A.Ş.',
      'bist_code': 'VEYAS',
      'fields': {'Halka Arz Fiyatı/Aralığı': '136,00 TL'},
      'demand_results': [
        {'grup': 'Yurt İçi Bireysel', 'kisi': '364.592', 'lot': '15.533.163', 'oran': '%35'},
      ],
      'fetched_at': '2026-08-21T09:00:00+00:00',
    };

    final detail = IpoDetail.fromJson(json);

    expect(detail.fields['Halka Arz Fiyatı/Aralığı'], '136,00 TL');
    expect(detail.demandResults.length, 1);
    expect(detail.demandResults.first['grup'], 'Yurt İçi Bireysel');
  });

  test('IpoNote doğru ayrıştırılır', () {
    final json = {
      'id': 'abc123',
      'user_id': 'user1',
      'company_name': 'VEYAS A.Ş.',
      'bist_code': 'VEYAS',
      'note_text': 'Şu an çok fazla satış var, bence satmalıyım.',
      'created_at': '2026-08-21T09:00:00+00:00',
    };

    final note = IpoNote.fromJson(json);

    expect(note.id, 'abc123');
    expect(note.noteText, 'Şu an çok fazla satış var, bence satmalıyım.');
  });
}
