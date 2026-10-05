/// Kullanıcının bir pozisyon için kendi belirlediği kâr/zarar sınırları (yüzde, maliyete göre).
///
/// Varsayılan değer YOKTUR; iki alan da isteğe bağlıdır. [positionVersion], sınırların kaydedildiği
/// pozisyon sürümüdür: pozisyon düzenlenir veya kapatılıp yeniden açılırsa sürüm değişir ve kayıt
/// yeniden onaylanana kadar pasif kalır.
class PositionLimits {
  final double? profitTargetPct;
  final double? maxLossPct;
  final String? positionVersion;
  final DateTime savedAt;

  const PositionLimits({
    required this.profitTargetPct,
    required this.maxLossPct,
    required this.positionVersion,
    required this.savedAt,
  });

  bool get isEmpty => profitTargetPct == null && maxLossPct == null;

  /// Kayıt yalnızca aynı (bilinen) pozisyon sürümü için etkindir.
  bool isActiveFor(String? currentVersion) =>
      currentVersion != null && positionVersion != null && positionVersion == currentVersion;

  Map<String, dynamic> toJson() => {
        'profit_target_pct': profitTargetPct,
        'max_loss_pct': maxLossPct,
        'position_version': positionVersion,
        'saved_at': savedAt.toUtc().toIso8601String(),
      };

  factory PositionLimits.fromJson(Map<String, dynamic> json) => PositionLimits(
        profitTargetPct: (json['profit_target_pct'] as num?)?.toDouble(),
        maxLossPct: (json['max_loss_pct'] as num?)?.toDouble(),
        positionVersion: json['position_version'] as String?,
        savedAt: DateTime.parse(json['saved_at'] as String),
      );
}

/// Girdi doğrulaması: boş = tanımsız; aksi hâlde pozitif ve üst sınır içinde olmalı.
/// Hata varsa mesaj, yoksa null döner.
String? validateLimitInput(String text, {required double max}) {
  final t = text.trim().replaceAll(',', '.');
  if (t.isEmpty) return null;
  final v = double.tryParse(t);
  if (v == null || !v.isFinite || v <= 0 || v > max) {
    return '0 ile ${max.toStringAsFixed(0)} arasında pozitif bir yüzde girin';
  }
  return null;
}

double? parseLimitInput(String text) {
  final t = text.trim().replaceAll(',', '.');
  return t.isEmpty ? null : double.parse(t);
}

class LimitCheckItem {
  final double? limitPct;
  final double? valuePct;
  final String status;

  const LimitCheckItem({required this.limitPct, required this.valuePct, required this.status});
}

/// Backend `POST /portfolio/positions/{asset}/limit-check` sonucu.
class LimitCheckResult {
  static const noLimits = 'SINIR_TANIMLI_DEGIL';
  static const within = 'SINIR_ICINDE';
  static const exceeded = 'SINIR_ASILDI';
  static const notEvaluated = 'DEGERLENDIRILEMEDI';

  final String asset;
  final String state;
  final String? blockCode;
  final String? blockMessage;
  final String? expectedSession;
  final String? priceSession;
  final double? priceClose;
  final String? priceSource;
  final String? priceBasis;
  final String? lastKnownSession;
  final String? lastKnownSource;
  final LimitCheckItem? profitTarget;
  final LimitCheckItem? maxLoss;
  final List<String> notes;

  const LimitCheckResult({
    required this.asset,
    required this.state,
    this.blockCode,
    this.blockMessage,
    this.expectedSession,
    this.priceSession,
    this.priceClose,
    this.priceSource,
    this.priceBasis,
    this.lastKnownSession,
    this.lastKnownSource,
    this.profitTarget,
    this.maxLoss,
    this.notes = const [],
  });

  factory LimitCheckResult.fromJson(Map<String, dynamic> json) {
    final price = json['price_used'] as Map<String, dynamic>?;
    final last = json['last_known_price'] as Map<String, dynamic>?;
    final checks = json['checks'] as Map<String, dynamic>?;
    LimitCheckItem? item(String key, String valueKey) {
      final c = checks?[key] as Map<String, dynamic>?;
      if (c == null) return null;
      return LimitCheckItem(
        limitPct: (c['limit_pct'] as num?)?.toDouble(),
        valuePct: (c[valueKey] as num?)?.toDouble(),
        status: c['status'] as String,
      );
    }

    return LimitCheckResult(
      asset: json['asset'] as String,
      state: json['state'] as String,
      blockCode: json['block_code'] as String?,
      blockMessage: json['block_message'] as String?,
      expectedSession: json['expected_session'] as String?,
      priceSession: price?['session'] as String?,
      priceClose: (price?['close'] as num?)?.toDouble(),
      priceSource: price?['source'] as String?,
      priceBasis: price?['price_basis'] as String?,
      lastKnownSession: last?['session'] as String?,
      lastKnownSource: last?['source'] as String?,
      profitTarget: item('profit_target', 'gain_pct_vs_cost'),
      maxLoss: item('max_loss', 'loss_pct_vs_cost'),
      notes: ((json['notes'] as List?) ?? const []).cast<String>(),
    );
  }
}

/// Manuel hesap için katı ondalık ayrıştırma (uygulamadaki `replaceAll(',', '.')` deseni + belirsizlik reddi).
/// Virgül veya nokta ondalık ayırıcı olabilir; ikisi birlikte, birden çok ayırıcı veya noktadan sonra tam üç
/// basamak (ör. "1.547": binlik mi ondalık mı belirsiz) REDDEDİLİR. Hata varsa [error] dolu, [value] null.
({double? value, String? error}) parseManualDecimal(String text, {bool required = true}) {
  final t = text.trim();
  if (t.isEmpty) return (value: null, error: required ? 'Zorunlu alan' : null);
  final commas = ','.allMatches(t).length;
  final dots = '.'.allMatches(t).length;
  if (commas + dots > 1) return (value: null, error: 'Binlik ayırıcı kullanmayın (ör. 1547,25)');
  if (dots == 1 && RegExp(r'^\d+\.\d{3}$').hasMatch(t)) {
    return (value: null, error: 'Belirsiz sayı: ondalık için virgül kullanın (ör. 1,547)');
  }
  if (!RegExp(r'^\d+([.,]\d+)?$').hasMatch(t)) return (value: null, error: 'Geçersiz sayı');
  final v = double.parse(t.replaceAll(',', '.'));
  if (!v.isFinite || v <= 0) return (value: null, error: 'Pozitif bir sayı girin');
  return (value: v, error: null);
}

const manualCurrencies = ['TRY', 'USD', 'EUR'];

/// Manuel hesap sonucu — yalnız kullanıcının girdiği değerlerle aritmetik; değerler YUVARLANMADAN tutulur.
class ManualLimitCalc {
  final double quantity;
  final double avgCost;
  final double price;
  final String currency;
  final double? profitTargetPct;
  final double? maxLossPct;

  const ManualLimitCalc({
    required this.quantity,
    required this.avgCost,
    required this.price,
    required this.currency,
    this.profitTargetPct,
    this.maxLossPct,
  });

  double get totalCost => quantity * avgCost;
  double get comparisonValue => quantity * price;
  double get difference => comparisonValue - totalCost;
  double get differencePct => (price / avgCost - 1) * 100;
  double? get targetLevel => profitTargetPct == null ? null : avgCost * (1 + profitTargetPct! / 100);
  double? get lossLevel => maxLossPct == null ? null : avgCost * (1 - maxLossPct! / 100);

  /// Karşılaştırma `position_review` sözleşmesiyle aynı: ölçü 6 ondalığa yuvarlanır, tam eşitlik aşım değildir.
  static double _cmp(double x) => double.parse(x.toStringAsFixed(6));

  String? get profitStatus => profitTargetPct == null
      ? null
      : (_cmp(differencePct) > profitTargetPct! ? LimitCheckResult.exceeded : LimitCheckResult.within);

  String? get lossStatus => maxLossPct == null
      ? null
      : (_cmp(-differencePct) > maxLossPct! ? LimitCheckResult.exceeded : LimitCheckResult.within);
}
