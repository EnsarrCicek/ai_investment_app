class NewsItem {
  final String externalId;
  final String title;
  final String summary;
  final String url;
  final String publisher;
  final double sourceReliability;
  final DateTime publishedAt;

  NewsItem({
    required this.externalId,
    required this.title,
    required this.summary,
    required this.url,
    required this.publisher,
    required this.sourceReliability,
    required this.publishedAt,
  });

  factory NewsItem.fromJson(Map<String, dynamic> json) {
    return NewsItem(
      externalId: json['external_id'] as String,
      title: json['title'] as String,
      summary: json['summary'] as String,
      url: json['url'] as String,
      publisher: json['publisher'] as String,
      sourceReliability: (json['source_reliability'] as num).toDouble(),
      publishedAt: DateTime.parse(json['published_at'] as String),
    );
  }
}
