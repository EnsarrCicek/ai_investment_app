import 'package:flutter/material.dart';

String fmtTl(double v) => '${v.toStringAsFixed(0)} TL';

String fmtPct(double? v) => v == null ? '—' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';

Color pctColor(double? v) {
  if (v == null) return Colors.grey;
  return v >= 0 ? Colors.green : Colors.red;
}

Color riskColor(String? riskLevel) {
  switch (riskLevel) {
    case 'YUKSEK':
      return Colors.red;
    case 'ORTA':
      return Colors.orange;
    case 'DUSUK':
      return Colors.green;
    default:
      return Colors.grey;
  }
}
