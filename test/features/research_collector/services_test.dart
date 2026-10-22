import 'dart:convert';
import 'dart:io';

import 'package:ai_investment_app/features/research_collector/application/collector_export_service.dart';
import 'package:ai_investment_app/features/research_collector/application/collector_health_service.dart';
import 'package:ai_investment_app/features/research_collector/application/collector_scheduler.dart';
import 'package:ai_investment_app/features/research_collector/application/mobile_collector_service.dart';
import 'package:ai_investment_app/features/research_collector/data/collector_repository.dart';
import 'package:ai_investment_app/features/research_collector/data/yahoo_mobile_source.dart';
import 'package:ai_investment_app/features/research_collector/domain/collector_constants.dart';
import 'package:ai_investment_app/features/research_collector/domain/study_anchors.g.dart';
import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import 'helpers.dart';

class FakeRegistrar implements BackgroundRegistrar {
  final List<EodRegistration> registered = [];
  final List<String> cancelled = [];

  @override
  Future<void> registerOneOff(EodRegistration r) async => registered.add(r);

  @override
  Future<void> cancelAll(String tag) async => cancelled.add(tag);
}

void main() {
  late TestDb t;
  setUp(() async => t = await TestDb.create());
  tearDown(() async => t.dispose());

  final eod = ist(2026, 10, 22, 19, 20);
  final day = [ist(2026, 10, 22, 9, 55), ist(2026, 10, 22, 10, 0)];

  MobileCollectorService service(FakeSource source, {NetworkKind net = NetworkKind.wifi}) => MobileCollectorService(
        repo: t.repo,
        source: source,
        network: () async => net,
        clock: () => eod,
        pauseBetweenRequests: Duration.zero,
      );

  Future<List<Map<String, Object?>>> rows(String sql) async => (await t.database.db).rawQuery(sql);

  group('collection run', () {
    test('failed symbol does not fabricate bars and does not stop the run; summary counts', () async {
      final source = FakeSource({
        'AKBNK|1m': result('AKBNK', '1m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod),
        'AKBNK|5m': result('AKBNK', '5m', [bar(day[0], 1, 2, 0.5, 1.5, 10), bar(day[1], 1, 2, 0.5, 1.6, 5)],
            retrievedAt: eod),
        'THYAO|1m': SourceException('Timeout', 'no response'),
        'THYAO|5m': result('THYAO', '5m', [bar(day[0], 3, 3, 3, 3, 1)], retrievedAt: eod),
        'XU100|1m': result('XU100', '1m', [bar(day[0], 9, 9, 9, 9, 0)], retrievedAt: eod, currency: null),
        'XU100|5m': result('XU100', '5m', [bar(day[0], 9, 9, 9, 9, 0)], retrievedAt: eod, currency: 'USD'),
      });
      final s = await service(source).run(mode: kModeManualSync, symbols: ['AKBNK', 'THYAO', 'XU100']);
      expect(source.calls, [
        'AKBNK|1m|5d', 'AKBNK|5m|5d', 'THYAO|1m|5d', 'THYAO|5m|5d', 'XU100|1m|5d', 'XU100|5m|5d',
      ]);
      expect(s.status, 'PARTIAL');
      expect(s.symbolsRequested, 3);
      expect(s.symbolsSucceeded, ['AKBNK', 'XU100']);
      expect(s.symbolsFailed, ['THYAO']);
      expect(s.requests, 6);
      expect(s.newBars1m, 2);
      expect(s.newBars5m, 4);
      expect(s.identityMatches, 3);
      expect(s.identityUnverified, 1);
      expect(s.identityMismatches, 1);
      expect(s.errorCount, 1);
      // THYAO 1m failed: no THYAO 1m bars of any kind.
      expect((await rows("SELECT COUNT(*) AS n FROM bars WHERE symbol = 'THYAO' AND interval = '1m'")).first['n'], 0);
      expect((await rows("SELECT COUNT(*) AS n FROM partial_bars WHERE symbol = 'THYAO'")).first['n'], 0);
      final f = (await rows('SELECT * FROM fetch_failures')).single;
      expect(f['symbol'], 'THYAO');
      expect(f['interval'], '1m');
      expect(f['error_type'], 'Timeout');
      expect(f['collection_role'], kCollectionRole);
      final run = (await rows('SELECT * FROM collection_runs')).single;
      expect(run['mode'], kModeManualSync);
      expect(run['collection_role'], kCollectionRole);
      expect(run['status'], 'PARTIAL');
      expect(run['symbols_succeeded'], 2);
      expect(run['symbols_failed'], 1);
      expect(run['requests'], 6);
      expect(run['new_bars_1m'], 2);
      expect(run['new_bars_5m'], 4);
      expect(run['identity_mismatches'], 1);
      expect(run['identity_unverified'], 1);
      expect(run['identity_matches'], 3);
      expect(run['error_count'], 1);
      expect(run['failed_symbols'], '["THYAO"]');
      expect(run['started_at'], isNotNull);
      expect(run['finished_at'], isNotNull);
      expect(run['scheduled_for'], isNull);
      expect(run['study_manifest_sha256'], kStudyManifestSha256);
      // Mismatched response is stored but flagged.
      expect((await rows("SELECT identity_status FROM bars WHERE symbol = 'XU100' AND interval = '5m'")).single
          ['identity_status'], 'MISMATCH');
    });

    test('every stored row is MOBILE_SHADOW', () async {
      final source = FakeSource({
        'AKBNK|1m': result('AKBNK', '1m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod),
        'AKBNK|5m': result('AKBNK', '5m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod),
      });
      await service(source).run(mode: kModeBackgroundEod, symbols: ['AKBNK', 'THYAO'], scheduledFor: ist(2026, 10, 22, 19, 15));
      for (final table in ['bars', 'partial_bars', 'bar_revisions', 'fetch_failures', 'requests', 'collection_runs']) {
        final roles = (await rows('SELECT DISTINCT collection_role AS r FROM $table')).map((r) => r['r']).toSet();
        expect(roles.difference({kCollectionRole}), isEmpty, reason: table);
      }
      final run = (await rows('SELECT * FROM collection_runs')).single;
      expect(run['mode'], kModeBackgroundEod);
      expect(run['scheduled_for'], '2026-10-22T16:15:00+00:00');
    });

    test('all failing -> FAILED, no bars', () async {
      final s = await service(FakeSource({})).run(mode: kModeManualSync, symbols: ['AKBNK']);
      expect(s.status, 'FAILED');
      expect(await t.repo.countRows('bars'), 0);
      expect(await t.repo.countRows('fetch_failures'), 2);
    });

    test('network policy: mobile data off -> skipped, no requests', () async {
      await t.repo.setSetting(kSettingCollectOnMobileData, 'false', eod);
      final source = FakeSource({});
      final s = await service(source, net: NetworkKind.mobile).run(mode: kModeBackgroundEod, symbols: ['AKBNK']);
      expect(s.status, 'SKIPPED_MOBILE_DATA_DISABLED');
      expect(source.calls, isEmpty);
      final wifi = await service(source, net: NetworkKind.wifi).run(mode: kModeBackgroundEod, symbols: ['AKBNK']);
      expect(wifi.status, 'FAILED');
      expect(source.calls, isNotEmpty);
    });

    test('mobile data allowed by default', () async {
      expect(await t.repo.collectOnMobileData(), isTrue);
      expect(await t.repo.collectorEnabled(), isTrue);
    });

    test('cancel stops between symbols', () async {
      final cancel = CancelToken();
      final source = FakeSource({});
      final s = await service(source).run(
          mode: kModeManualSync,
          symbols: ['AKBNK', 'THYAO', 'GARAN'],
          cancel: cancel,
          onProgress: (done, total, _) {
            expect(total, 3);
            if (done == 1) cancel.cancel();
          });
      expect(s.status, 'CANCELLED');
      expect(source.calls.length, 2);
    });

    test('single writer lock; stale RUNNING runs become INTERRUPTED', () async {
      expect(await t.repo.acquireLock('other', eod), isTrue);
      final s = await service(FakeSource({})).run(mode: kModeManualSync, symbols: ['AKBNK']);
      expect(s.status, 'SKIPPED_ALREADY_RUNNING');
      await t.repo.releaseLock('other');
      final db = await t.database.db;
      await db.insert('collection_runs', {
        'run_id': 'killed',
        'mode': kModeBackgroundEod,
        'collection_role': kCollectionRole,
        'study_manifest_sha256': kStudyManifestSha256,
        'label_manifest_sha256': kLabelManifestSha256,
        'universe_sha256': kUniverseSha256,
        'collector_version': kCollectorVersion,
        'started_at': '2026-10-21T16:15:00+00:00',
        'status': 'RUNNING',
      });
      await service(FakeSource({})).run(mode: kModeManualSync, symbols: ['AKBNK']);
      expect((await rows("SELECT status FROM collection_runs WHERE run_id = 'killed'")).single['status'], 'INTERRUPTED');
    });
  });

  group('WorkManager job registration', () {
    test('registers the next weekday 19:15 slot as unique one-off work', () async {
      final reg = FakeRegistrar();
      final now = ist(2026, 10, 21, 12, 0);
      final plan = await CollectorScheduler(repo: t.repo, registrar: reg, clock: () => now).ensureScheduled();
      expect(reg.registered.single, same(plan));
      expect(plan!.uniqueName, 'momentum_shadow_eod_2026-10-21');
      expect(plan.taskName, kEodTaskName);
      expect(plan.tag, kEodTaskTag);
      expect(plan.slot, ist(2026, 10, 21, 19, 15));
      expect(plan.initialDelay, const Duration(hours: 7, minutes: 15));
      expect(plan.unmeteredOnly, isFalse);
      expect(await t.repo.setting(kSettingSetupCompletedAt), isNotNull);
      expect(await t.repo.setting(kSettingSchedulerNextSlot), '2026-10-21T16:15:00+00:00');
    });

    test('after the slot / on Friday evening it chains to the next weekday', () async {
      final reg = FakeRegistrar();
      final friday = ist(2026, 10, 23, 19, 16);
      final plan = await CollectorScheduler(repo: t.repo, registrar: reg, clock: () => friday).ensureScheduled();
      expect(plan!.uniqueName, 'momentum_shadow_eod_2026-10-26');
    });

    test('mobile data off -> unmetered constraint; disabled -> cancelled', () async {
      final reg = FakeRegistrar();
      final sch = CollectorScheduler(repo: t.repo, registrar: reg, clock: () => ist(2026, 10, 21, 12, 0));
      await t.repo.setSetting(kSettingCollectOnMobileData, 'false', eod);
      expect((await sch.ensureScheduled(reset: true))!.unmeteredOnly, isTrue);
      expect(reg.cancelled, [kEodTaskTag]);
      await t.repo.setSetting(kSettingCollectorEnabled, 'false', eod);
      expect(await sch.ensureScheduled(), isNull);
      expect(reg.cancelled, [kEodTaskTag, kEodTaskTag]);
      expect(reg.registered.length, 1);
    });
  });

  group('health', () {
    test('has no outcome keys or values', () async {
      final source = FakeSource({
        'AKBNK|1m': result('AKBNK', '1m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod),
        'AKBNK|5m': result('AKBNK', '5m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod),
      });
      await service(source).run(mode: kModeManualSync, symbols: ['AKBNK', 'THYAO']);
      final h = await CollectorHealthService(t.repo, clock: () => eod).health();
      expect(h.keys.toList(), kHealthKeys);
      for (final key in h.keys) {
        for (final term in kForbiddenHealthTerms) {
          expect(key.toLowerCase().contains(term), isFalse, reason: '$key contains $term');
        }
      }
      final text = jsonEncode(h).toLowerCase();
      for (final term in ['precision', 'recall', 'event', 'lead', 'watch', 'strong', 'buy', 'sell']) {
        expect(text.contains(term), isFalse, reason: term);
      }
      expect(h['collection_role'], kCollectionRole);
      expect(h['primary_validation_eligible'], false);
      expect(h['database_integrity'], 'ok');
      expect(h['last_run_status'], 'PARTIAL');
      expect(h['days_with_data'], 1);
      expect(h['latest_session'], '2026-10-22');
      expect(h['missing_assets_last_run'], ['THYAO']);
      expect(h['identity_mismatches'], 0);
      expect(h['background_scheduler_status'], 'NOT_REGISTERED');
    });
  });

  group('export', () {
    test('export manifest deterministic fields', () {
      final a = buildExportManifest(exportedAt: DateTime.utc(2026, 10, 22, 17), dbSha256: 'abc', dbSizeBytes: 10);
      final b = buildExportManifest(exportedAt: DateTime.utc(2026, 10, 22, 17), dbSha256: 'abc', dbSizeBytes: 10);
      expect(jsonEncode(a), jsonEncode(b));
      expect(a['exported_at'], '2026-10-22T17:00:00+00:00');
      expect(a['app_version'], kAppVersion);
      expect(a['collector_version'], kCollectorVersion);
      expect(a['study_manifest_sha'], kStudyManifestSha256);
      expect(a['label_sha'], kLabelManifestSha256);
      expect(a['universe_sha'], kUniverseSha256);
      expect(a['db_sha256'], 'abc');
      expect(a['collection_role'], 'MOBILE_SHADOW');
      expect(a['primary_validation_eligible'], false);
    });

    test('ZIP contains the DB and a manifest whose db_sha256 matches', () async {
      await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 1, 2, 0.5, 1.5, 10)], retrievedAt: eod), 'run1');
      final out = await Directory.systemTemp.createTemp('shadow_export_');
      final r = await CollectorExportService(
              database: t.database, repo: t.repo, outputDir: () async => out, clock: () => eod)
          .export();
      final zip = ZipDecoder().decodeBytes(await File(r.zipPath).readAsBytes());
      expect(zip.files.map((f) => f.name).toSet(), {'momentum_shadow.db', 'export_manifest.json'});
      final dbBytes = zip.findFile('momentum_shadow.db')!.content;
      final manifest = jsonDecode(utf8.decode(zip.findFile('export_manifest.json')!.content)) as Map;
      expect(manifest['db_sha256'], sha256.convert(dbBytes).toString());
      expect(manifest['db_size_bytes'], dbBytes.length);
      expect(manifest['collection_role'], 'MOBILE_SHADOW');
      // The live DB reopens transparently after export.
      expect(await t.repo.countRows('bars'), 1);
      await out.delete(recursive: true);
    });

    test('export refused while a collection holds the lock', () async {
      await t.repo.acquireLock('run', eod);
      final out = await Directory.systemTemp.createTemp('shadow_export_');
      expect(
          () => CollectorExportService(database: t.database, repo: t.repo, outputDir: () async => out, clock: () => eod)
              .export(),
          throwsA(isA<ExportBusyException>()));
    });
  });
}
