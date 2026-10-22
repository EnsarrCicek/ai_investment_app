import 'package:ai_investment_app/features/research_collector/data/collector_database.dart';
import 'package:ai_investment_app/features/research_collector/domain/collector_constants.dart';
import 'package:ai_investment_app/features/research_collector/domain/models.dart';
import 'package:ai_investment_app/features/research_collector/domain/study_anchors.g.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'helpers.dart';

void main() {
  late TestDb t;
  setUp(() async => t = await TestDb.create());
  tearDown(() async => t.dispose());

  Future<List<Map<String, Object?>>> rows(String sql, [List<Object?> args = const []]) async =>
      (await t.database.db).rawQuery(sql, args);

  final day = [ist(2026, 10, 22, 9, 55), ist(2026, 10, 22, 10, 0)];
  final eod = ist(2026, 10, 22, 19, 20);

  test('new completed bars carry all anchors, MOBILE_SHADOW and are not primary-eligible', () async {
    final c = await t.repo.ingest(
        result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100), bar(day[1], 10.5, 11, 10, 10.8, 50)],
            retrievedAt: eod),
        'run1');
    expect(c.newBars, 2);
    final b = (await rows('SELECT * FROM bars ORDER BY bar_start_ns')).first;
    expect(b['collection_role'], kCollectionRole);
    expect(b['primary_validation_eligible'], 0);
    expect(b['study_manifest_sha256'], kStudyManifestSha256);
    expect(b['label_manifest_sha256'], kLabelManifestSha256);
    expect(b['universe_sha256'], kUniverseSha256);
    expect(b['collector_version'], kCollectorVersion);
    expect(b['data_phase'], kPhaseProspective);
    expect(b['universe_role'], 'PRIMARY');
    expect(b['provider_symbol'], 'AKBNK.IS');
    expect(b['bar_start_utc'], '2026-10-22T06:55:00+00:00');
    expect(b['bar_start_local'], '2026-10-22T09:55:00+03:00');
    expect(b['bar_end_utc'], '2026-10-22T07:00:00+00:00');
    expect(b['session_date'], '2026-10-22');
    expect(b['identity_status'], 'MATCH');
    expect(b['exchange'], 'IST');
    expect(b['currency'], 'TRY');
    expect(b['is_partial'], 0);
    expect(b['source'], 'yahoo_finance');
    expect(b['collection_run_id'], 'run1');
    expect((b['bar_hash'] as String).length, 64);
    expect((b['response_hash'] as String).length, 64);
  });

  test('collection_role is enforced by the schema', () async {
    final db = await t.database.db;
    expect(
        () => db.insert('fetch_failures', {
              'run_id': 'r',
              'collection_role': 'PRIMARY',
              'symbol': 'AKBNK',
              'interval': '5m',
              'timestamp': 'x',
              'error_type': 'x',
              'message': 'x'
            }),
        throwsA(isA<DatabaseException>()));
  });

  test('duplicate ignored', () async {
    final r = result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100)], retrievedAt: eod);
    await t.repo.ingest(r, 'run1');
    final c = await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100)],
        retrievedAt: eod.add(const Duration(days: 1))), 'run2');
    expect(c.newBars, 0);
    expect(c.duplicates, 1);
    expect((await rows('SELECT COUNT(*) AS n FROM bars')).first['n'], 1);
  });

  test('first_seen immutable + revision log', () async {
    await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100)], retrievedAt: eod), 'run1');
    final later = eod.add(const Duration(days: 1));
    final c = await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.6, 120)], retrievedAt: later), 'run2');
    expect(c.revisions, 1);
    final b = (await rows('SELECT * FROM bars')).single;
    expect(b['close'], 10.5);
    expect(b['volume'], 100.0);
    expect(b['first_seen_at_utc'], '2026-10-22T16:20:00+00:00');
    expect(b['collection_run_id'], 'run1');
    final rev = (await rows('SELECT * FROM bar_revisions')).single;
    expect(rev['previous_hash'], b['bar_hash']);
    expect(rev['original_hash'], b['bar_hash']);
    expect(rev['changed_fields'], '["close","volume"]');
    expect(rev['observed_at'], '2026-10-23T16:20:00+00:00');
    expect(rev['bar_start'], '2026-10-22T06:55:00+00:00');
    // Same revised value again: not logged twice; a third value chains previous_hash.
    expect((await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.6, 120)], retrievedAt: later), 'run3'))
        .duplicates, 1);
    await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.7, 120)], retrievedAt: later), 'run4');
    final revs = await rows('SELECT * FROM bar_revisions ORDER BY id');
    expect(revs.length, 2);
    expect(revs[1]['previous_hash'], revs[0]['new_hash']);
    // Append-only: the original row cannot be overwritten or deleted.
    final db = await t.database.db;
    expect(() => db.update('bars', {'close': 1.0}), throwsA(isA<DatabaseException>()));
    expect(() => db.delete('bars'), throwsA(isA<DatabaseException>()));
  });

  test('partial not finalized, then partial -> finalized', () async {
    final during = ist(2026, 10, 22, 10, 3); // 10:00 bar ends 10:05 -> forming
    final c1 = await t.repo.ingest(
        result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100), bar(day[1], 10.5, 10.9, 10.4, 10.6, 20)],
            retrievedAt: during),
        'run1');
    expect(c1.newBars, 1);
    expect(c1.partialObservations, 1);
    expect((await rows('SELECT COUNT(*) AS n FROM bars WHERE bar_start_utc = ?', ['2026-10-22T07:00:00+00:00']))
        .first['n'], 0);
    final p = (await rows('SELECT * FROM partial_bars')).single;
    expect(p['is_partial'], 1);
    expect(p['collection_role'], kCollectionRole);

    final c2 = await t.repo.ingest(
        result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100), bar(day[1], 10.5, 11.2, 10.4, 11.0, 80)],
            retrievedAt: eod),
        'run2');
    expect(c2.newBars, 1);
    expect(c2.duplicates, 1);
    expect(c2.finalizations, 1);
    final f = (await rows('SELECT * FROM bar_finalizations')).single;
    expect(f['last_partial_hash'], p['bar_hash']);
    expect(f['finalized_first_seen_at'], '2026-10-22T16:20:00+00:00');
    final b = (await rows('SELECT * FROM bars WHERE bar_start_utc = ?', ['2026-10-22T07:00:00+00:00'])).single;
    expect(b['close'], 11.0);
    expect(b['is_partial'], 0);
  });

  test('recovered bar gets the recovery fetch time as first_seen', () async {
    final old = ist(2026, 10, 19, 14, 0);
    final recovery = ist(2026, 10, 22, 19, 31);
    await t.repo.ingest(result('THYAO', '1m', [bar(old, 300, 301, 299, 300.5, 10)], retrievedAt: recovery), 'run1');
    final b = (await rows('SELECT * FROM bars')).single;
    expect(b['session_date'], '2026-10-19');
    expect(b['first_seen_at_utc'], '2026-10-22T16:31:00+00:00');
    expect(b['retrieved_at_utc'], '2026-10-22T16:31:00+00:00');
    expect(b['data_phase'], kPhasePreStart);
  });

  test('consumed-final days are never written', () async {
    final c = await t.repo.ingest(
        result('AKBNK', '5m', [bar(ist(2026, 10, 15, 11, 0), 1, 1, 1, 1, 1), bar(ist(2026, 10, 16, 11, 0), 1, 1, 1, 1, 1)],
            retrievedAt: ist(2026, 10, 21, 19, 20)),
        'run1');
    expect(c.skippedConsumedFinal, 1);
    expect(c.newBars, 1);
    expect((await rows('SELECT session_date FROM bars')).single['session_date'], '2026-10-16');
  });

  test('rows without prices are not stored (no fabrication)', () async {
    final c = await t.repo.ingest(
        result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, null), RawBar(nsOf(day[1]), null, null, null, null, null)],
            retrievedAt: eod),
        'run1');
    expect(c.newBars, 1);
    expect(c.invalidRows, 1);
    expect((await rows('SELECT volume FROM bars')).single['volume'], isNull);
  });

  test('1m and 5m keys are independent', () async {
    await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100)], retrievedAt: eod), 'run1');
    final c = await t.repo.ingest(result('AKBNK', '1m', [bar(day[0], 10, 10.2, 9.9, 10.1, 7)], retrievedAt: eod), 'run1');
    expect(c.newBars, 1);
    expect(c.revisions, 0);
    expect((await rows('SELECT interval FROM bars ORDER BY interval')).map((r) => r['interval']), ['1m', '5m']);
  });

  test('benchmark stored with BENCHMARK role', () async {
    await t.repo.ingest(result('XU100', '5m', [bar(day[0], 1, 1, 1, 1, 0)], retrievedAt: eod), 'run1');
    expect((await rows('SELECT universe_role FROM bars')).single['universe_role'], 'BENCHMARK');
  });

  group('migration', () {
    test('fresh DB is created at the current schema version with anchors', () async {
      final db = await t.database.db;
      expect(await db.getVersion(), kSchemaVersion);
      final meta = {for (final r in await db.query('meta')) r['key']: r['value']};
      expect(meta['schema_version'], '$kSchemaVersion');
      expect(meta['collection_role'], kCollectionRole);
      expect(meta['study_manifest_sha256'], kStudyManifestSha256);
      final tables = (await db.rawQuery("SELECT name FROM sqlite_master WHERE type = 'table'"))
          .map((r) => r['name'])
          .toSet();
      expect(tables, containsAll(['bars', 'bar_revisions', 'partial_bars', 'bar_finalizations', 'collection_runs',
        'fetch_failures', 'requests', 'settings', 'meta', 'run_lock']));
    });

    test('reopen keeps data; newer on-disk schema is refused (no silent downgrade)', () async {
      await t.repo.ingest(result('AKBNK', '5m', [bar(day[0], 10, 11, 9, 10.5, 100)], retrievedAt: eod), 'run1');
      final path = await t.database.path;
      await t.database.close();
      expect((await rows('SELECT COUNT(*) AS n FROM bars')).first['n'], 1);
      await t.database.close();
      final raw = await testFactory().openDatabase(path);
      await raw.setVersion(kSchemaVersion + 1);
      await raw.close();
      expect(() => openCollectorDatabase(path, factory: testFactory()), throwsA(anything));
    });

    test('migrations apply in order from v0', () async {
      final db = await testFactory().openDatabase(inMemoryDatabasePath);
      await applyMigrations(db, 0, kSchemaVersion);
      expect((await db.query('meta')).single['value'], '$kSchemaVersion');
      expect(() => applyMigrations(db, kSchemaVersion, kSchemaVersion + 1), throwsStateError);
      await db.close();
    });
  });
}

