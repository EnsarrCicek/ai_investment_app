import 'package:flutter/material.dart';

const Map<String, String> decisionLabels = {
  'BUY': 'AL',
  'WEAK_BUY': 'ZAYIF AL',
  'HOLD': 'TUT',
  'WEAK_SELL': 'ZAYIF SAT',
  'SELL': 'SAT',
};

String decisionLabel(String decision) => decisionLabels[decision] ?? decision;

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
