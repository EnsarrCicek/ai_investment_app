import '../utils/currency_label.dart';

class PortfolioPosition {
  final String asset;
  final double buyPrice;
  final double quantity;
  final int lotCount;
  final double? currentPrice;
  final double? investedAmount;
  final double? currentValue;
  final double? profitLoss;
  final double? returnPercent;
  final String? error;

  /// Lot kimliklerinden türetilen pozisyon sürümü (düzenleme/kapatıp yeniden açma değiştirir).
  /// Kullanıcı kâr/zarar sınırları bu sürüme bağlanır; eski backend yanıtında yoksa null.
  final String? positionVersion;

  /// Kayıtlı alış fiyatının para birimi (ISO). Eski kayıtlarda null = bilinmiyor.
  final String? currency;

  /// Güncel piyasa fiyatının kaynağı (aynı sağlayıcı yanıtı); [currency] ile karıştırılmaz.
  final String? currentPriceCurrency;
  final String? currentPriceExchange;
  final String? currentPriceIdentityCheck;

  /// Güncel fiyatın temeli (ör. PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST); eski backend'de null.
  final String? currentPriceBasis;

  /// true = maliyet ve değerleme fiyatı aynı güvenilir temelde karşılaştırılabilir ve kurumsal işlem etkileri
  /// doğrulandı. false/null (eski backend) = sayısal hesap olabilir ama doğrulanmış sonuç DEĞİL.
  final bool? pnlBasisVerified;
  final String? pnlUnverifiedReason;

  PortfolioPosition({
    required this.asset,
    required this.buyPrice,
    required this.quantity,
    required this.lotCount,
    this.currentPrice,
    this.investedAmount,
    this.currentValue,
    this.profitLoss,
    this.returnPercent,
    this.error,
    this.positionVersion,
    this.currency,
    this.currentPriceCurrency,
    this.currentPriceExchange,
    this.currentPriceIdentityCheck,
    this.currentPriceBasis,
    this.pnlBasisVerified,
    this.pnlUnverifiedReason,
  });

  /// Yalnız backend açıkça true gönderdiyse; alan yok/null ise doğrulanmamış (fail-closed).
  bool get pnlVerified => pnlBasisVerified == true;

  /// Alış fiyatı / yatırım tutarı birimi: yalnız kayıtlı para birimi.
  String? get buyPriceUnit => currencyUnit(currency);

  /// Güncel fiyat / güncel değer birimi: yalnız sağlayıcı kimliği doğrulandıysa (MATCH).
  String? get currentPriceUnit => currentPriceIdentityCheck == 'MATCH' ? currencyUnit(currentPriceCurrency) : null;

  /// Kâr/zarar birimi: kayıtlı para birimi ile doğrulanmış güncel fiyat para birimi biliniyor ve AYNI ise.
  String? get pnlUnit => currency != null &&
          currentPriceIdentityCheck == 'MATCH' &&
          currentPriceCurrency != null &&
          currency == currentPriceCurrency
      ? currencyUnit(currency)
      : null;

  factory PortfolioPosition.fromJson(Map<String, dynamic> json) {
    return PortfolioPosition(
      asset: json['asset'] as String,
      buyPrice: (json['buy_price'] as num).toDouble(),
      quantity: (json['quantity'] as num).toDouble(),
      lotCount: json['lot_count'] as int,
      currentPrice: (json['current_price'] as num?)?.toDouble(),
      investedAmount: (json['invested_amount'] as num?)?.toDouble(),
      currentValue: (json['current_value'] as num?)?.toDouble(),
      profitLoss: (json['profit_loss'] as num?)?.toDouble(),
      returnPercent: (json['return_percent'] as num?)?.toDouble(),
      error: json['error'] as String?,
      positionVersion: json['position_version'] as String?,
      currency: json['currency'] as String?,
      currentPriceCurrency: json['current_price_currency'] as String?,
      currentPriceExchange: json['current_price_exchange'] as String?,
      currentPriceIdentityCheck: json['current_price_identity_check'] as String?,
      currentPriceBasis: json['current_price_basis'] as String?,
      pnlBasisVerified: json['pnl_basis_verified'] as bool?,
      pnlUnverifiedReason: json['pnl_unverified_reason'] as String?,
    );
  }
}

class PortfolioSummary {
  final double totalInvested;
  final double totalCurrentValue;
  final double totalProfitLoss;
  final double totalReturnPercent;

  PortfolioSummary({
    required this.totalInvested,
    required this.totalCurrentValue,
    required this.totalProfitLoss,
    required this.totalReturnPercent,
  });

  factory PortfolioSummary.fromJson(Map<String, dynamic> json) {
    return PortfolioSummary(
      totalInvested: (json['total_invested'] as num).toDouble(),
      totalCurrentValue: (json['total_current_value'] as num).toDouble(),
      totalProfitLoss: (json['total_profit_loss'] as num).toDouble(),
      totalReturnPercent: (json['total_return_percent'] as num).toDouble(),
    );
  }
}

/// Özet kartı birimleri. Backend özeti yalnız değerlenebilen (hatasız) pozisyonları topladığı için aynı küme
/// kullanılır. Toplamdaki tüm pozisyonların ilgili birimi bilinmiyor veya farklıysa birim null'dır.
({String? invested, String? current, String? pnl}) summaryUnits(List<PortfolioPosition> positions) {
  final valued = positions.where((p) => p.error == null).toList();
  if (valued.isEmpty) return (invested: null, current: null, pnl: null);
  return (
    invested: commonUnit(valued.map((p) => p.buyPriceUnit)),
    current: commonUnit(valued.map((p) => p.currentPriceUnit)),
    pnl: commonUnit(valued.map((p) => p.pnlUnit)),
  );
}

/// Toplam kâr/zarar yalnız TÜM pozisyonlar değerlenebilmiş ve her birinin kâr/zararı doğrulanmışsa doğrulanmış sayılır.
/// Değerlenemeyen bir pozisyon toplamdan sessizce çıkarılıp kalanlar "doğrulanmış toplam" yapılmaz.
bool summaryPnlVerified(List<PortfolioPosition> positions) =>
    positions.isNotEmpty && positions.every((p) => p.error == null && p.pnlVerified);
