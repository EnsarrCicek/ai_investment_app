class PriceQuote {
  final String assetId;
  final DateTime timestamp;
  final double lastPrice;
  final double previousClose;
  final double change;
  final double? changePercent;
  final double open;
  final double high;
  final double low;
  final int volume;
  final String source;

  PriceQuote({
    required this.assetId,
    required this.timestamp,
    required this.lastPrice,
    required this.previousClose,
    required this.change,
    required this.changePercent,
    required this.open,
    required this.high,
    required this.low,
    required this.volume,
    required this.source,
  });

  factory PriceQuote.fromJson(Map<String, dynamic> json) {
    return PriceQuote(
      assetId: json['asset_id'] as String,
      timestamp: DateTime.parse(json['timestamp'] as String),
      lastPrice: (json['last_price'] as num).toDouble(),
      previousClose: (json['previous_close'] as num).toDouble(),
      change: (json['change'] as num).toDouble(),
      changePercent: (json['change_percent'] as num?)?.toDouble(),
      open: (json['open'] as num).toDouble(),
      high: (json['high'] as num).toDouble(),
      low: (json['low'] as num).toDouble(),
      volume: json['volume'] as int,
      source: json['source'] as String,
    );
  }
}

class PriceBar {
  final DateTime timestamp;
  final double open;
  final double high;
  final double low;
  final double close;
  final int volume;

  PriceBar({
    required this.timestamp,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    required this.volume,
  });

  factory PriceBar.fromJson(Map<String, dynamic> json) {
    return PriceBar(
      timestamp: DateTime.parse(json['timestamp'] as String),
      open: (json['open'] as num).toDouble(),
      high: (json['high'] as num).toDouble(),
      low: (json['low'] as num).toDouble(),
      close: (json['close'] as num).toDouble(),
      volume: json['volume'] as int,
    );
  }
}
