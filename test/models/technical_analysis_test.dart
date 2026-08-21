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
    expect(detail.marketStructure, isNull);
    expect(detail.signalClass, isNull);
    expect(detail.candlestickPatterns, isEmpty);
    expect(detail.nearestSupport, isNull);
    expect(detail.breakout, isNull);
    expect(detail.allZones, isEmpty);
    expect(detail.narrative, '');
  });

  test('AŞAMA 48/15 zenginleştirme alanlarını doğru ayrıştırır', () {
    final json = {
      'asset': 'THYAO',
      'technical_score': -29.02,
      'trend': 'BEARISH',
      'confidence': 0.72,
      'components': {'rsi': -10.0},
      'indicators': {'rsi': 40.0},
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
  });
}
