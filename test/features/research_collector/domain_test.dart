import 'dart:convert';
import 'dart:io';

import 'package:ai_investment_app/features/research_collector/data/yahoo_mobile_source.dart';
import 'package:ai_investment_app/features/research_collector/domain/canonical.dart';
import 'package:ai_investment_app/features/research_collector/domain/collector_constants.dart';
import 'package:ai_investment_app/features/research_collector/domain/market_time.dart';
import 'package:ai_investment_app/features/research_collector/domain/models.dart';
import 'package:ai_investment_app/features/research_collector/domain/study_anchors.g.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

void main() {
  group('canonical hashing (Windows-compatible)', () {
    test('python float repr', () {
      // Reference: Python repr() of the same floats.
      final cases = <double, String>{
        1.0: '1.0',
        0.1: '0.1',
        123.45: '123.45',
        1e16: '1e+16',
        1.5e-05: '1.5e-05',
        0.0001: '0.0001',
        12345678.0: '12345678.0',
        1e22: '1e+22',
        -2.5: '-2.5',
        0.30000000000000004: '0.30000000000000004',
        99.99: '99.99',
        1234567890123456.0: '1234567890123456.0',
      };
      cases.forEach((v, expected) => expect(pyFloatRepr(v), expected, reason: '$v'));
    });

    test('deterministic bar hash equals Python storage.bar_hash', () {
      expect(barHash(41.5, 41.92, 41.38, 41.8, 1234567.0),
          'f4c152a8399476323007309ce327aaf38ed7283fa272e77fd12965914f06f635');
      expect(barHash(41.5, 41.92, 41.38, 41.8, null),
          'd58ad68b527102a7d45a2e7f601164a3e2bebfeb55169b9ef25c61f72bf0aaa2');
      expect(barHash(41.5, 41.92, 41.38, 41.8, 1234567.0), barHash(41.5, 41.92, 41.38, 41.8, 1234567.0));
    });

    test('canonical JSON: sorted keys, ensure_ascii, null/bool', () {
      expect(canonicalSha256({'b': [1, 2.5, null], 'a': 'ş"x', 'c': true}),
          '78f770d1f837801dc4cabaa350230dc7b7532d44d2c2887ea1a006f1cb1afd7d');
      expect(() => canonicalJson(double.nan), throwsArgumentError);
    });

    test('UTC iso format matches pandas isoformat', () {
      expect(utcIsoFromNs(1792565700 * 1000000000), '2026-10-21T06:55:00+00:00');
      expect(istanbulIso(DateTime.utc(2026, 10, 21, 6, 55)), '2026-10-21T09:55:00+03:00');
    });
  });

  group('study anchors', () {
    final manifest = jsonDecode(
        File('backend/app/research/momentum_collector/momentum_prospective_manifest.json').readAsStringSync()) as Map;
    final config = manifest['config'] as Map;

    test('anchors equal the frozen study', () {
      expect(kLabelManifestSha256, '9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09');
      expect(kStudyManifestSha256, '635ff0b15c8387174779b105e8f45c9767184cab6b5ea13fb16a679cacab598b');
      expect(kUniverseSha256, '2d96684a0e83b59bf0ee93d3affd9f0b7e95f6e402863f25375d5a752fc687f0');
      expect(kProspectiveStartSession, '2026-10-22');
      expect(manifest['sha256'], kStudyManifestSha256);
      expect(config['manifest_status'], 'FINAL');
      expect(config['label_manifest_sha256'], kLabelManifestSha256);
    });

    test('universe is generated from the frozen manifest, hash verified in Dart', () {
      expect(kPrimaryUniverse, List<String>.from(config['universe'] as List));
      expect(kPrimaryUniverse.length, 87);
      expect(canonicalSha256([...kPrimaryUniverse]..sort()), kUniverseSha256);
      expect(kPrimaryUniverse, isNot(contains('KTLEV')));
      expect(shadowSymbols(), [...kPrimaryUniverse, 'XU100']);
      expect(shadowSymbols().toSet().length, 88);
    });

    test('app version constant matches pubspec', () {
      final version = RegExp(r'^version:\s*(\S+)', multiLine: true).firstMatch(File('pubspec.yaml').readAsStringSync())!;
      expect(kAppVersion, version.group(1));
    });
  });

  group('identity', () {
    test('MATCH', () {
      expect(identityStatus('AKBNK', reportedSymbol: 'AKBNK.IS', exchange: 'IST', currency: 'TRY'), kIdentityMatch);
      expect(identityStatus('XU100', reportedSymbol: 'XU100.IS', exchange: 'IST', currency: 'TRY'), kIdentityMatch);
    });
    test('UNVERIFIED when metadata missing (TRY/IST never assumed)', () {
      expect(identityStatus('AKBNK', reportedSymbol: 'AKBNK.IS', exchange: null, currency: 'TRY'), kIdentityUnverified);
      expect(identityStatus('AKBNK'), kIdentityUnverified);
      final r = result('AKBNK', '5m', [], retrievedAt: DateTime.utc(2026, 10, 22, 16), exchange: null, currency: null);
      expect(r.exchange, isNull);
      expect(r.currency, isNull);
      expect(r.identity, kIdentityUnverified);
    });
    test('MISMATCH', () {
      expect(identityStatus('AKBNK', reportedSymbol: 'AKBNK.IS', exchange: 'IST', currency: 'USD'), kIdentityMismatch);
      expect(identityStatus('AKBNK', reportedSymbol: 'AKBNK', exchange: null, currency: null), kIdentityMismatch);
    });
  });

  group('phases and calendar', () {
    test('PRE_START_SHADOW / PROSPECTIVE_SHADOW', () {
      expect(dataPhaseOf('2026-10-21'), kPhasePreStart);
      expect(dataPhaseOf('2026-10-22'), kPhaseProspective);
      expect(dataPhaseOf('2026-11-30'), kPhaseProspective);
    });
    test('consumed final days', () {
      expect(isConsumedFinalDay('2026-09-28'), isTrue);
      expect(isConsumedFinalDay('2026-10-15'), isTrue);
      expect(isConsumedFinalDay('2026-10-16'), isFalse);
    });
    test('next EOD slot is a weekday 19:15 Istanbul', () {
      expect(nextEodSlot(ist(2026, 10, 21, 10, 0)), ist(2026, 10, 21, 19, 15));
      expect(nextEodSlot(ist(2026, 10, 21, 19, 15)), ist(2026, 10, 22, 19, 15));
      expect(nextEodSlot(ist(2026, 10, 23, 20, 0)), ist(2026, 10, 26, 19, 15)); // Friday -> Monday
    });
    test('partial rule', () {
      final s = [for (final m in [55, 60, 65, 70]) nsOf(ist(2026, 10, 22, 9, 0).add(Duration(minutes: m)))];
      // 10:12 local: 10:10 bar still forming (end 10:15) and is the day's last bar.
      expect(partialFlags(s, '5m', ist(2026, 10, 22, 10, 12)), [false, false, false, true]);
      // 18:00 local: everything ended, but the day's last bar may still fill (before 18:30).
      expect(partialFlags(s, '5m', ist(2026, 10, 22, 18, 0)), [false, false, false, true]);
      // 19:15 local: all final.
      expect(partialFlags(s, '5m', ist(2026, 10, 22, 19, 15)), [false, false, false, false]);
      // Off-grid live row marks itself and its grid slot partial.
      final live = [...s, s.last + 90 * 1000000000];
      expect(partialFlags(live, '5m', ist(2026, 10, 23, 19, 15)), [false, false, false, true, true]);
    });
  });

  group('Yahoo parsing', () {
    String body({List<Object?>? closes}) => jsonEncode({
          'chart': {
            'result': [
              {
                'meta': {'symbol': 'AKBNK.IS', 'exchangeName': 'IST', 'currency': 'TRY'},
                'timestamp': [1792565700, 1792566000, 1792566300],
                'indicators': {
                  'quote': [
                    {
                      'open': [10, null, 10.2],
                      'high': [10.5, null, 10.4],
                      'low': [9.9, null, 10.1],
                      'close': closes ?? [10.1, null, 10.3],
                      'volume': [1000, null, null],
                    }
                  ]
                }
              }
            ],
            'error': null,
          }
        });

    test('rows taken as-is: no forward fill, no invented volume', () {
      final r = parseChartResponse(
          symbol: 'AKBNK',
          interval: '5m',
          range: '5d',
          body: body(),
          httpStatus: 200,
          requestedAt: DateTime.utc(2026, 10, 21, 16),
          retrievedAt: DateTime.utc(2026, 10, 21, 16));
      expect(r.identity, kIdentityMatch);
      expect(r.bars.length, 3);
      expect(r.bars[0].open, 10.0);
      expect(r.bars[0].volume, 1000.0);
      expect(r.bars[1].hasPrices, isFalse);
      expect(r.bars[1].close, isNull);
      expect(r.bars[2].volume, isNull);
    });

    test('provider error / empty result are typed failures', () {
      final err = jsonEncode({
        'chart': {'result': null, 'error': {'code': 'Not Found', 'description': 'No data found'}}
      });
      expect(
          () => parseChartResponse(
              symbol: 'XXXX', interval: '1m', range: '5d', body: err, httpStatus: 404,
              requestedAt: DateTime.utc(2026), retrievedAt: DateTime.utc(2026)),
          throwsA(isA<SourceException>().having((e) => e.errorType, 'type', 'ProviderError')));
      expect(
          () => parseChartResponse(
              symbol: 'XXXX', interval: '1m', range: '5d', body: 'not json', httpStatus: 200,
              requestedAt: DateTime.utc(2026), retrievedAt: DateTime.utc(2026)),
          throwsA(isA<SourceException>().having((e) => e.errorType, 'type', 'ParseError')));
    });

    test('request URL uses .IS, interval and 5d recovery range', () {
      final u = YahooMobileSource.chartUri('XU100', '1m', kRecoveryRange);
      expect(u.path, '/v8/finance/chart/XU100.IS');
      expect(u.queryParameters, {'interval': '1m', 'range': '5d', 'includePrePost': 'false'});
    });
  });
}
