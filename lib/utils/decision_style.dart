import 'package:flutter/material.dart';

const Map<String, String> decisionLabels = {
  'BUY': 'AL',
  'WEAK_BUY': 'ZAYIF AL',
  'HOLD': 'TUT',
  'WEAK_SELL': 'ZAYIF SAT',
  'SELL': 'SAT',
};

String decisionLabel(String decision) => decisionLabels[decision] ?? decision;

/// Bir skoru (-100..+100) DecisionEngine'deki DEFAULT_THRESHOLDS ile birebir
/// aynı eşiklerle AL/ZAYIF AL/TUT/ZAYIF SAT/SAT kararına sınıflandırır.
/// Tek bir haberin duygu skoru gibi, ağırlıklı toplam olmayan skorlar için.
String classifyScore(double score) {
  if (score >= 40) return 'BUY';
  if (score >= 15) return 'WEAK_BUY';
  if (score <= -40) return 'SELL';
  if (score <= -15) return 'WEAK_SELL';
  return 'HOLD';
}

Color decisionColor(String decision) {
  switch (decision) {
    case 'BUY':
    case 'WEAK_BUY':
      return Colors.green;
    case 'SELL':
    case 'WEAK_SELL':
      return Colors.red;
    default:
      return Colors.grey;
  }
}
