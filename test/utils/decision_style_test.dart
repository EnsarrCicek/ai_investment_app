import 'package:ai_investment_app/utils/decision_style.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('decisionLabel', () {
    test('bilinen kararları doğru Türkçe etikete çevirir', () {
      expect(decisionLabel('BUY'), 'AL');
      expect(decisionLabel('WEAK_BUY'), 'ZAYIF AL');
      expect(decisionLabel('HOLD'), 'TUT');
      expect(decisionLabel('WEAK_SELL'), 'ZAYIF SAT');
      expect(decisionLabel('SELL'), 'SAT');
    });

    test('bilinmeyen bir karar için kendisini döner', () {
      expect(decisionLabel('UNKNOWN'), 'UNKNOWN');
    });
  });

  group('decisionColor', () {
    test('AL kararları yeşil döner', () {
      expect(decisionColor('BUY'), Colors.green);
      expect(decisionColor('WEAK_BUY'), Colors.green);
    });

    test('SAT kararları kırmızı döner', () {
      expect(decisionColor('SELL'), Colors.red);
      expect(decisionColor('WEAK_SELL'), Colors.red);
    });

    test('TUT ve bilinmeyen kararlar gri döner', () {
      expect(decisionColor('HOLD'), Colors.grey);
      expect(decisionColor('UNKNOWN'), Colors.grey);
    });
  });

  group('classifyScore', () {
    test('eşik sınırlarını DecisionEngine ile birebir aynı sınıflandırır', () {
      expect(classifyScore(50), 'BUY');
      expect(classifyScore(40), 'BUY');
      expect(classifyScore(39.9), 'WEAK_BUY');
      expect(classifyScore(15), 'WEAK_BUY');
      expect(classifyScore(14.9), 'HOLD');
      expect(classifyScore(0), 'HOLD');
      expect(classifyScore(-14.9), 'HOLD');
      expect(classifyScore(-15), 'WEAK_SELL');
      expect(classifyScore(-39.9), 'WEAK_SELL');
      expect(classifyScore(-40), 'SELL');
      expect(classifyScore(-50), 'SELL');
    });
  });
}
