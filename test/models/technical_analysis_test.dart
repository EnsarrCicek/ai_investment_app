import 'package:ai_investment_app/models/technical_analysis.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('temel alanlar zenginleştirme alanları olmadan da doğru ayrıştırılır (geriye dönük uyumluluk)', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -29.02,
      'trend': 'BEARISH',
      'confidence': 0.72,
      'components': {'rsi': -10.0, 'roc': -5.0},
      'indicators': {'rsi': 40.0},
    };

    final detail = TechnicalAnalysisDetail.fromJson(json);

    expect(detail.asset, 'THYAO');
    expect(detail.technicalScore, -29.02);
    // HATA 5B2D: `family_scores` eklenmeden önceki (backend flat 7-component
    // mimarisi) kayıtlar bu alanı hiç içermez -- boş map, geriye dönük uyumlu.
    expect(detail.familyScores, isEmpty);
    expect(detail.marketStructure, isNull);
    expect(detail.signalClass, isNull);
    expect(detail.candlestickPatterns, isEmpty);
    expect(detail.nearestSupport, isNull);
    expect(detail.breakout, isNull);
    expect(detail.allZones, isEmpty);
    expect(detail.narrative, '');
    expect(detail.investmentHorizon, isNull);
    expect(detail.investmentHorizonReason, '');
    expect(detail.marketDataAsOf, isNull);
  });

  test('AŞAMA 48/15 zenginleştirme alanlarını doğru ayrıştırır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -29.02,
      'trend': 'BEARISH',
      'confidence': 0.72,
      'components': {'rsi': -10.0},
      'indicators': {'rsi': 40.0},
      'market_data_as_of': '2026-08-24T00:00:00+03:00',
      'market_structure': 'DOWNTREND',
      'signal_class': 'BEARISH_CANDIDATE',
      'relative_volume_class': 'LOW',
      'relative_strength_class': 'UNDERPERFORMING',
      'volatility_regime': 'LOW',
      'trend_regime': 'TRENDING',
      'gap_class': 'NO_SIGNIFICANT_GAP',
      'candlestick_patterns': ['DOJI'],
      'nearest_support': {'type': 'SUPPORT', 'low': 305.25, 'high': 305.25, 'touch_count': 1},
      'nearest_resistance': {'type': 'RESISTANCE', 'low': 301.75, 'high': 301.75, 'touch_count': 1},
      'breakout': {
        'direction': 'BULLISH',
        'breakout_atr': 2.5,
        'confirmed': true,
        'retest_held': null,
        'zone': {'type': 'RESISTANCE', 'low': 100.0, 'high': 101.0, 'touch_count': 3},
      },
      'mtf_aligned': true,
      'mtf_consensus': 'DOWN',
      'investment_horizon': 'KISA_VADELI',
      'investment_horizon_reason': 'Yalnızca teknik skor yön veriyor.',
      'all_zones': [
        {'type': 'SUPPORT', 'low': 305.25, 'high': 305.25, 'touch_count': 1},
        {'type': 'RESISTANCE', 'low': 301.75, 'high': 301.75, 'touch_count': 1},
      ],
      'narrative': 'Fiyat, direnci yukarı yönlü kırdı.',
    };

    final detail = TechnicalAnalysisDetail.fromJson(json);

    expect(detail.marketStructure, 'DOWNTREND');
    expect(detail.signalClass, 'BEARISH_CANDIDATE');
    expect(detail.relativeStrengthClass, 'UNDERPERFORMING');
    expect(detail.candlestickPatterns, ['DOJI']);
    expect(detail.nearestSupport!.low, 305.25);
    expect(detail.nearestResistance!.touchCount, 1);
    expect(detail.breakout!.direction, 'BULLISH');
    expect(detail.breakout!.confirmed, true);
    expect(detail.breakout!.retestHeld, isNull);
    expect(detail.breakout!.zone.type, 'RESISTANCE');
    expect(detail.mtfAligned, true);
    expect(detail.mtfConsensus, 'DOWN');
    expect(detail.allZones.length, 2);
    expect(detail.allZones.first.type, 'SUPPORT');
    expect(detail.narrative, 'Fiyat, direnci yukarı yönlü kırdı.');
    expect(detail.investmentHorizon, 'KISA_VADELI');
    expect(detail.investmentHorizonReason, 'Yalnızca teknik skor yön veriyor.');
    expect(detail.marketDataAsOf, DateTime.parse('2026-08-24T00:00:00+03:00'));
  });

  test('27.08.2026 (HATA 5B1): technical_score null iken crash olmadan ayrıştırılır', () {
    // Backend 7 bileşenin TAMAMI unavailable olduğunda (son derece nadir)
    // `technical_score: null` döner -- eski `(json['technical_score'] as num)
    // .toDouble()` deseni bu durumda Dart runtime TypeError fırlatırdı.
    // FINAL PRE-COMMIT GATE (madde 2): aynı durumda `trend` de `null` döner
    // (eski `json['trend'] as String` deseni de burada TypeError fırlatırdı).
    final json = {
      'asset': 'THYAO',
      'technical_score': null,
      'trend': null,
      'confidence': 0.0,
      'components': <String, dynamic>{},
      'indicators': {'rsi': 40.0},
    };

    final detail = TechnicalAnalysisDetail.fromJson(json);

    expect(detail.technicalScore, isNull);
    expect(detail.trend, isNull);
    expect(detail.components, isEmpty);
  });

  test('27.08.2026 (HATA 5B1 FINAL PRE-COMMIT GATE): technical_score=0.0 iken trend gerçek bir string olarak kalır', () {
    // score=0.0 GEÇERLİ bir skordur (unavailable İLE KARIŞTIRILMAMALI) --
    // trend de her zamanki gibi gerçek bir "NEUTRAL" string'i olarak kalır.
    final json = {
      'asset': 'THYAO',
      'technical_score': 0.0,
      'trend': 'NEUTRAL',
      'confidence': 0.62,
      'components': {'rsi': 0.0, 'trend': 0.0},
      'indicators': {'rsi': 50.0},
    };

    final detail = TechnicalAnalysisDetail.fromJson(json);

    expect(detail.technicalScore, 0.0);
    expect(detail.trend, 'NEUTRAL');
  });

  test('27.08.2026 (HATA 5B2D): family_scores mevcutken doğru ayrıştırılır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': 27.77,
      'trend': 'NEUTRAL',
      'confidence': 0.7,
      'components': {'rsi': 40.0, 'bollinger': 20.0, 'ema_slope': -10.0},
      'family_scores': {'trend': 30.0, 'oscillator_position': 15.0, 'momentum_rate': 38.32},
      'indicators': {'rsi': 55.0},
    };

    final detail = TechnicalAnalysisDetail.fromJson(json);

    expect(detail.familyScores, {'trend': 30.0, 'oscillator_position': 15.0, 'momentum_rate': 38.32});
  });
}
