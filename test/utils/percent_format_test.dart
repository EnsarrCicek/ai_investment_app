import 'package:ai_investment_app/utils/percent_format.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('formatPercentFromFraction (HATA 5C-UI1, 31.08.2026)', () {
    test('0.0 -> %0', () {
      expect(formatPercentFromFraction(0.0), '%0');
    });

    test('0.01 -> %1', () {
      expect(formatPercentFromFraction(0.01), '%1');
    });

    test('0.50 -> %50', () {
      expect(formatPercentFromFraction(0.50), '%50');
    });

    test('0.87 -> %87 (macro confidence scale bug regresyonu)', () {
      expect(formatPercentFromFraction(0.87), '%87');
    });

    test('1.0 -> %100', () {
      expect(formatPercentFromFraction(1.0), '%100');
    });
  });

  group('formatDecisionConfidencePercent (HATA 5C-UI2, 31.08.2026)', () {
    test('62.5 -> %63 (0..100 skala, ×100 YOK)', () {
      expect(formatDecisionConfidencePercent(62.5), '%63');
    });

    test('100 -> %100', () {
      expect(formatDecisionConfidencePercent(100.0), '%100');
    });

    test('62.5 formatPercentFromFraction ile YANLIŞLIKLA %6250 üretmez', () {
      expect(formatDecisionConfidencePercent(62.5), isNot('%6250'));
    });
  });

  group('formatCoveragePercent (HATA 5C-UI2, 31.08.2026)', () {
    test('0.8 -> %80', () {
      expect(formatCoveragePercent(0.8), '%80');
    });

    test('0.2 -> %20', () {
      expect(formatCoveragePercent(0.2), '%20');
    });

    test('null -> Hesaplanmadı (eski kayıt, "veri yetersiz" DEĞİL)', () {
      expect(formatCoveragePercent(null), 'Hesaplanmadı');
    });
  });

  group('formatTechnicalSignalAgreementPercent (HATA 5C-UI2, 31.08.2026)', () {
    test('0.67 -> %67', () {
      expect(formatTechnicalSignalAgreementPercent(0.67), '%67');
    });

    test('0.0 -> %0 (gerçek sıfır, "veri yetersiz" DEĞİL)', () {
      expect(formatTechnicalSignalAgreementPercent(0.0), '%0');
    });

    test('null -> Veri yetersiz', () {
      expect(formatTechnicalSignalAgreementPercent(null), 'Veri yetersiz');
    });
  });

  group('Sinyal Mutabakatı + Veri Kapsamı aynı context (HATA 5C-UI2 madde 7/23)', () {
    test('only-one-channel: confidence=100, coverage=.2 -> ikisi de doğru ve BİRLİKTE üretilir', () {
      final confidenceText = 'Sinyal Mutabakatı ${formatDecisionConfidencePercent(100.0)}';
      final coverageText = 'Veri Kapsamı ${formatCoveragePercent(0.2)}';
      expect(confidenceText, 'Sinyal Mutabakatı %100');
      expect(coverageText, 'Veri Kapsamı %20');
    });

    test('technical confidence=.67 + coverage=.44 aynı context', () {
      final confidenceText = 'Sinyal Mutabakatı: ${formatTechnicalSignalAgreementPercent(0.67)}';
      final coverageText = 'Veri Kapsamı: ${formatCoveragePercent(0.44)}';
      expect(confidenceText, 'Sinyal Mutabakatı: %67');
      expect(coverageText, 'Veri Kapsamı: %44');
    });
  });
}
