/// `GET /decisions/dashboard` — toplu, salt-okunur dashboard özeti (backend
/// app/services/decisions/dashboard.py). Satır başına yalnız dashboard'un gösterdiği alanlar.
class DashboardItem {
  final String asset;

  /// OK: karar üretildi; ERROR: karar üretilemedi (`reason`); UNAVAILABLE: veri kaynağına
  /// erişilemedi (yalnız yerel geliştirme, ör. Firestore kotası) — skor/karar YOKTUR.
  final String status;
  final String? reason;
  final String? decision;
  final double? finalScore;
  final double? confidence;
  final double? channelCompleteness;
  final double? technicalScore;
  final double? newsScore;
  final double? macroScore;

  const DashboardItem({
    required this.asset,
    required this.status,
    this.reason,
    this.decision,
    this.finalScore,
    this.confidence,
    this.channelCompleteness,
    this.technicalScore,
    this.newsScore,
    this.macroScore,
  });

  bool get hasDecision => status == 'OK' && decision != null && confidence != null;

  factory DashboardItem.fromJson(Map<String, dynamic> json) {
    double? num_(String key) => (json[key] as num?)?.toDouble();
    return DashboardItem(
      asset: json['asset'] as String,
      status: json['status'] as String,
      reason: json['reason'] as String?,
      decision: json['decision'] as String?,
      finalScore: num_('final_score'),
      confidence: num_('confidence'),
      channelCompleteness: num_('channel_completeness'),
      technicalScore: num_('technical_score'),
      newsScore: num_('news_score'),
      macroScore: num_('macro_score'),
    );
  }
}

class DecisionDashboard {
  final DateTime generatedAt;

  /// NORMAL veya LOCAL_DEGRADED (yalnız yerel geliştirme: bazı veriler kasıtlı olarak eksik).
  final String mode;
  final String? reason;
  final String assetSource;
  final List<DashboardItem> items;

  const DecisionDashboard({
    required this.generatedAt,
    required this.mode,
    required this.assetSource,
    required this.items,
    this.reason,
  });

  bool get degraded => mode != 'NORMAL';

  factory DecisionDashboard.fromJson(Map<String, dynamic> json) {
    return DecisionDashboard(
      generatedAt: DateTime.parse(json['generated_at'] as String),
      mode: json['mode'] as String,
      reason: json['reason'] as String?,
      assetSource: json['asset_source'] as String,
      items: (json['items'] as List).map((e) => DashboardItem.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}
