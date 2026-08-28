class SrZone {
  final String type;
  final double low;
  final double high;
  final int touchCount;

  SrZone({required this.type, required this.low, required this.high, required this.touchCount});

  double get mid => (low + high) / 2;

  factory SrZone.fromJson(Map<String, dynamic> json) {
    return SrZone(
      type: json['type'] as String,
      low: (json['low'] as num).toDouble(),
      high: (json['high'] as num).toDouble(),
      touchCount: json['touch_count'] as int,
    );
  }
}

class BreakoutInfo {
  final String direction;
  final double breakoutAtr;
  final bool? confirmed;
  final bool? retestHeld;
  final SrZone zone;

  BreakoutInfo({
    required this.direction,
    required this.breakoutAtr,
    required this.confirmed,
    required this.retestHeld,
    required this.zone,
  });

  factory BreakoutInfo.fromJson(Map<String, dynamic> json) {
    return BreakoutInfo(
      direction: json['direction'] as String,
      breakoutAtr: (json['breakout_atr'] as num).toDouble(),
      confirmed: json['confirmed'] as bool?,
      retestHeld: json['retest_held'] as bool?,
      zone: SrZone.fromJson(json['zone'] as Map<String, dynamic>),
    );
  }
}

class TechnicalAnalysisDetail {
  final String asset;
  // 27.08.2026 (HATA 5B1): backend'in 7 bileşeninin TAMAMI unavailable
  // olduğunda (son derece nadir) `null` dönebilir -- 0.0 ile KARIŞTIRILMAMALI:
  // 0.0 gerçek bir teknik skordur, `null` skorun HİÇ üretilemediği anlamına
  // gelir.
  final double? technicalScore;
  // 27.08.2026 (HATA 5B1 FINAL PRE-COMMIT GATE): `technicalScore` `null`
  // olduğunda `trend` de `null` olur -- "NEUTRAL" gerçek bir teknik yön
  // bilgisidir (skor hesaplandı ama [-15, 15] aralığında), "yön
  // hesaplanamadı" ile AYNI şey DEĞİLDİR. `technicalScore == 0.0` hâlâ
  // `trend == 'NEUTRAL'` üretir.
  final String? trend;
  final double confidence;
  final Map<String, double> components;
  final Map<String, dynamic> indicators;

  // 25.08.2026 (HATA 2A): analizde kullanılan SON TAMAMLANMIŞ günlük barın
  // tarihi — bu, motorun HESABI YAPTIĞI an (varsa gösterilen "güncel fiyat"
  // ile karıştırılmamalı, o ayrı bir canlı `quote` akışıdır) DEĞİL, veriNİN
  // ait olduğu andır. Eski (bu alan eklenmeden önceki) kayıtlarda null olur.
  final DateTime? marketDataAsOf;

  // AŞAMA 48/15 — zenginleştirme katmanı (skoru etkilemez, yalnızca bağlam)
  final String? marketStructure;
  final String? signalClass;
  final String? relativeVolumeClass;
  final String? relativeStrengthClass;
  final String? volatilityRegime;
  final String? trendRegime;
  final String? gapClass;
  final List<String> candlestickPatterns;
  final SrZone? nearestSupport;
  final SrZone? nearestResistance;
  final BreakoutInfo? breakout;
  final bool? mtfAligned;
  final String? mtfConsensus;

  // 25.08.2026: saf teknik yapıya dayanan, kural tabanlı vade sınıflandırması
  // (bkz. backend/app/engines/technical/horizon_classifier.py) — haber/makro
  // KARIŞTIRILMAZ.
  final String? investmentHorizon;
  final String investmentHorizonReason;

  // AŞAMA 66: kullanıcı isteği "grafikte dirençler nasıl çiziliyor, neden AL
  // diyorsun detaylı açıkla" — grafikte çizilecek tüm destek/direnç bölgeleri
  // + kural tabanlı (LLM'siz) Türkçe anlatı.
  final List<SrZone> allZones;
  final String narrative;

  TechnicalAnalysisDetail({
    required this.asset,
    required this.technicalScore,
    required this.trend,
    required this.confidence,
    required this.components,
    required this.indicators,
    this.marketDataAsOf,
    this.marketStructure,
    this.signalClass,
    this.relativeVolumeClass,
    this.relativeStrengthClass,
    this.volatilityRegime,
    this.trendRegime,
    this.gapClass,
    this.candlestickPatterns = const [],
    this.nearestSupport,
    this.nearestResistance,
    this.breakout,
    this.mtfAligned,
    this.mtfConsensus,
    this.investmentHorizon,
    this.investmentHorizonReason = '',
    this.allZones = const [],
    this.narrative = '',
  });

  factory TechnicalAnalysisDetail.fromJson(Map<String, dynamic> json) {
    return TechnicalAnalysisDetail(
      asset: json['asset'] as String,
      technicalScore: (json['technical_score'] as num?)?.toDouble(),
      trend: json['trend'] as String?,
      confidence: (json['confidence'] as num).toDouble(),
      components: (json['components'] as Map<String, dynamic>).map(
        (key, value) => MapEntry(key, (value as num).toDouble()),
      ),
      indicators: json['indicators'] as Map<String, dynamic>,
      marketDataAsOf: json['market_data_as_of'] == null ? null : DateTime.parse(json['market_data_as_of'] as String),
      marketStructure: json['market_structure'] as String?,
      signalClass: json['signal_class'] as String?,
      relativeVolumeClass: json['relative_volume_class'] as String?,
      relativeStrengthClass: json['relative_strength_class'] as String?,
      volatilityRegime: json['volatility_regime'] as String?,
      trendRegime: json['trend_regime'] as String?,
      gapClass: json['gap_class'] as String?,
      candlestickPatterns:
          (json['candlestick_patterns'] as List<dynamic>?)?.map((e) => e as String).toList() ?? const [],
      nearestSupport: json['nearest_support'] == null
          ? null
          : SrZone.fromJson(json['nearest_support'] as Map<String, dynamic>),
      nearestResistance: json['nearest_resistance'] == null
          ? null
          : SrZone.fromJson(json['nearest_resistance'] as Map<String, dynamic>),
      breakout: json['breakout'] == null ? null : BreakoutInfo.fromJson(json['breakout'] as Map<String, dynamic>),
      mtfAligned: json['mtf_aligned'] as bool?,
      mtfConsensus: json['mtf_consensus'] as String?,
      investmentHorizon: json['investment_horizon'] as String?,
      investmentHorizonReason: json['investment_horizon_reason'] as String? ?? '',
      allZones:
          (json['all_zones'] as List<dynamic>?)?.map((e) => SrZone.fromJson(e as Map<String, dynamic>)).toList() ??
          const [],
      narrative: json['narrative'] as String? ?? '',
    );
  }
}
