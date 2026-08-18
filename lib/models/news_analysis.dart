class NewsAnalysis {
  final String newsId;
  final double sentimentScore;
  final double confidence;
  final double importance;
  final String eventType;
  final String reasoning;
  final String modelUsed;
  final DateTime createdAt;

  NewsAnalysis({
    required this.newsId,
    required this.sentimentScore,
    required this.confidence,
    required this.importance,
    required this.eventType,
    required this.reasoning,
    required this.modelUsed,
    required this.createdAt,
  });

  factory NewsAnalysis.fromJson(Map<String, dynamic> json) {
    return NewsAnalysis(
      newsId: json['news_id'] as String,
      sentimentScore: (json['sentiment_score'] as num).toDouble(),
      confidence: (json['confidence'] as num).toDouble(),
      importance: (json['importance'] as num).toDouble(),
      eventType: json['event_type'] as String,
      reasoning: json['reasoning'] as String,
      modelUsed: json['model_used'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
