class NotificationRecord {
  final String? asset;
  final String kind; // "TEST" / "BUY" / "SELL"
  final String title;
  final String body;
  final DateTime createdAt;

  NotificationRecord({
    required this.asset,
    required this.kind,
    required this.title,
    required this.body,
    required this.createdAt,
  });

  factory NotificationRecord.fromJson(Map<String, dynamic> json) {
    return NotificationRecord(
      asset: json['asset'] as String?,
      kind: json['kind'] as String,
      title: json['title'] as String,
      body: json['body'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
