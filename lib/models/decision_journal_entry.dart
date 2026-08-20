import 'decision.dart';

class DecisionOutcome {
  final String status; // DOGRU, YANLIS, BEKLEMEDE, NOTR, VERI_YOK
  final double? realizedReturnPct;

  DecisionOutcome({required this.status, required this.realizedReturnPct});

  factory DecisionOutcome.fromJson(Map<String, dynamic> json) {
    return DecisionOutcome(
      status: json['status'] as String,
      realizedReturnPct: (json['realized_return_pct'] as num?)?.toDouble(),
    );
  }
}

/// AŞAMA 62: "Karar Günlüğü" — gerçek geçmiş AIDecision kayıtlarının gerçek
/// sonraki fiyat hareketiyle karşılaştırılmış hali (bkz. outcome_evaluator.py).
class DecisionJournalEntry {
  final Decision decision;
  final Map<String, DecisionOutcome> outcomes; // anahtarlar "7", "30" (gün)
  final String? dominantFactor; // "technical" | "news" | "macro" | null

  DecisionJournalEntry({required this.decision, required this.outcomes, required this.dominantFactor});

  factory DecisionJournalEntry.fromJson(Map<String, dynamic> json) {
    final outcomesJson = json['outcomes'] as Map<String, dynamic>? ?? {};
    return DecisionJournalEntry(
      decision: Decision.fromJson(json),
      outcomes: outcomesJson.map((k, v) => MapEntry(k, DecisionOutcome.fromJson(v as Map<String, dynamic>))),
      dominantFactor: json['dominant_factor'] as String?,
    );
  }
}

const Map<String, String> outcomeStatusLabelsTr = {
  'DOGRU': 'Doğru çıktı',
  'YANLIS': 'Yanlış çıktı',
  'BEKLEMEDE': 'Bekliyor',
  'NOTR': 'Nötr (TUT)',
  'VERI_YOK': 'Veri yok',
};

const Map<String, String> dominantFactorLabelsTr = {
  'technical': 'Teknik',
  'news': 'Haber',
  'macro': 'Makro',
};
