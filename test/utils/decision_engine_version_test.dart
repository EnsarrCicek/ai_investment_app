import 'package:ai_investment_app/utils/decision_engine_version.dart';
import 'package:ai_investment_app/utils/percent_format.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('isNewDecisionConfidenceSemantics (HATA 5C-UI2, 31.08.2026)', () {
    test('null -> legacy', () {
      expect(isNewDecisionConfidenceSemantics(null), isFalse);
    });

    test('"" -> legacy', () {
      expect(isNewDecisionConfidenceSemantics(''), isFalse);
    });

    test('"1.0.0" -> legacy', () {
      expect(isNewDecisionConfidenceSemantics('1.0.0'), isFalse);
    });

    test('"1.0.9" -> legacy', () {
      expect(isNewDecisionConfidenceSemantics('1.0.9'), isFalse);
    });

    test('"1.1.0" -> new', () {
      expect(isNewDecisionConfidenceSemantics('1.1.0'), isTrue);
    });

    test('"1.2.0" -> new', () {
      expect(isNewDecisionConfidenceSemantics('1.2.0'), isTrue);
    });

    test('"2.0.0" -> new', () {
      expect(isNewDecisionConfidenceSemantics('2.0.0'), isTrue);
    });

    test('"1.10.0" -> new (lexicographic string compare kullanılmadığının kanıtı)', () {
      expect(isNewDecisionConfidenceSemantics('1.10.0'), isTrue);
    });
  });

  group('journalConfidenceLabel (HATA 5C-UI2 madde 24 — Karar Günlüğü)', () {
    test('eski kayıt (decision_engine_version="1.0.0", confidence=60) -> "Eski Güven Skoru: %60"', () {
      const version = '1.0.0';
      final text = '${journalConfidenceLabel(version)}: ${formatDecisionConfidencePercent(60.0)}';
      expect(text, 'Eski Güven Skoru: %60');
    });

    test('yeni kayıt (decision_engine_version="1.1.0", confidence=60) -> "Sinyal Mutabakatı: %60"', () {
      const version = '1.1.0';
      final text = '${journalConfidenceLabel(version)}: ${formatDecisionConfidencePercent(60.0)}';
      expect(text, 'Sinyal Mutabakatı: %60');
    });

    test('eksik version (null) -> legacy label', () {
      expect(journalConfidenceLabel(null), 'Eski Güven Skoru');
    });
  });
}
