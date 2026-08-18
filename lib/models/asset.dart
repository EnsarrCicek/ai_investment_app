class Asset {
  final String symbol;
  final String name;
  final String market;
  final String assetType;
  final String currency;
  final bool active;

  Asset({
    required this.symbol,
    required this.name,
    required this.market,
    required this.assetType,
    required this.currency,
    required this.active,
  });

  factory Asset.fromJson(Map<String, dynamic> json) {
    return Asset(
      symbol: json['symbol'] as String,
      name: json['name'] as String,
      market: json['market'] as String,
      assetType: json['asset_type'] as String,
      currency: json['currency'] as String,
      active: json['active'] as bool,
    );
  }
}
