import 'package:ai_investment_app/models/decision_journal_entry.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('DecisionJournalEntry karar alanlarını ve outcomes/dominant_factor\'ı doğru ayrıştırır', () {
    final json = {
      'asset': 'THYAO',
      'created_at': '2026-08-13T13:16:27.123137+00:00',
      'technical_score': -23.25,
      'news_score': 18.42,
      'macro_score': 6.35,
      'final_score': -4.83,
      'decision': 'WEAK_SELL',
      'confidence': 86.0,
      'outcomes': {
        '7': {'status': 'DOGRU', 'realized_return_pct': -2.11},
        '30': {'status': 'BEKLEMEDE'},
      },
      'dominant_factor': 'technical',
    };

    final entry = DecisionJournalEntry.fromJson(json);

    expect(entry.decision.asset, 'THYAO');
    expect(entry.decision.decision, 'WEAK_SELL');
    expect(entry.outcomes['7']!.status, 'DOGRU');
    expect(entry.outcomes['7']!.realizedReturnPct, -2.11);
    expect(entry.outcomes['30']!.status, 'BEKLEMEDE');
    expect(entry.outcomes['30']!.realizedReturnPct, isNull);
    expect(entry.dominantFactor, 'technical');
    expect(dominantFactorLabelsTr[entry.dominantFactor], 'Teknik');
  });

  test('dominant_factor null olabilir (hiç skor yoksa)', () {
    final json = {
      'asset': 'THYAO',
      'created_at': '2026-08-13T13:16:27.123137+00:00',
      'final_score': 0.0,
      'decision': 'HOLD',
      'confidence': 60.0,
      'outcomes': <String, dynamic>{},
      'dominant_factor': null,
    };

    final entry = DecisionJournalEntry.fromJson(json);

    expect(entry.dominantFactor, isNull);
    expect(entry.outcomes, isEmpty);
  });
}
