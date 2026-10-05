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

  // Geriye uyumlu ek alanlar: eski backend göndermezse null (bilinmiyor). `timestamp` anlamı değişmedi.
  /// INTRADAY_BAR_CLOSE | DAILY_BAR_CLOSE
  final String? priceType;
  final DateTime? barStart;
  final String? interval;
  final DateTime? retrievedAt;
  final String? currency;
  final String? exchange;
  /// MATCH | UNVERIFIED
  final String? identityCheck;
  final bool? fallbackUsed;
  final String? fallbackReason;
  /// Yalnız sağlayıcı aynı yanıtta aynı fiyat için bildirdiyse.
  final DateTime? lastTradeAt;

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
    this.priceType,
    this.barStart,
    this.interval,
    this.retrievedAt,
    this.currency,
    this.exchange,
    this.identityCheck,
    this.fallbackUsed,
    this.fallbackReason,
    this.lastTradeAt,
  });

  static DateTime? _dt(Object? v) => v == null ? null : DateTime.parse(v as String);

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
      priceType: json['price_type'] as String?,
      barStart: _dt(json['bar_start']),
      interval: json['interval'] as String?,
      retrievedAt: _dt(json['retrieved_at']),
      currency: json['currency'] as String?,
      exchange: json['exchange'] as String?,
      identityCheck: json['identity_check'] as String?,
      fallbackUsed: json['fallback_used'] as bool?,
      fallbackReason: json['fallback_reason'] as String?,
      lastTradeAt: _dt(json['last_trade_at']),
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
