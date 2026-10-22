import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../domain/collector_constants.dart';
import '../domain/market_time.dart';
import '../domain/models.dart';
import '../domain/study_anchors.g.dart';
import 'collector_database.dart';

const kSettingCollectorEnabled = 'collector_enabled';
const kSettingCollectOnMobileData = 'collect_on_mobile_data';
const kSettingSetupCompletedAt = 'setup_completed_at';
const kSettingSchedulerRegisteredAt = 'scheduler_registered_at';
const kSettingSchedulerNextSlot = 'scheduler_next_slot';
const kSettingSchedulerNetworkType = 'scheduler_network_type';
const kSettingSchedulerError = 'scheduler_error';

/// A held run lock older than this is considered abandoned (process killed mid-run).
const Duration kStaleLockAfter = Duration(minutes: 20);

const _ohlcv = ['open', 'high', 'low', 'close', 'volume'];

/// All reads/writes of the shadow archive. Every response is ingested in ONE transaction, so killing the app
/// mid-run never leaves a half-written response.
class CollectorRepository {
  final CollectorDatabase database;

  CollectorRepository(this.database);

  Future<Database> get _db => database.db;

  // ------------------------------------------------------------------ settings
  Future<String?> setting(String key) async {
    final rows = await (await _db).query('settings', where: 'key = ?', whereArgs: [key]);
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  Future<void> setSetting(String key, String value, DateTime now) async {
    await (await _db).insert('settings', {'key': key, 'value': value, 'updated_at': utcIso(now)},
        conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<bool> collectorEnabled() async => (await setting(kSettingCollectorEnabled) ?? 'true') == 'true';

  Future<bool> collectOnMobileData() async => (await setting(kSettingCollectOnMobileData) ?? 'true') == 'true';

  // ------------------------------------------------------------------ lock
  /// Single writer across UI isolate and background worker.
  Future<bool> acquireLock(String owner, DateTime now) async {
    return (await _db).transaction((txn) async {
      final rows = await txn.query('run_lock');
      if (rows.isNotEmpty) {
        final heartbeat = rows.first['heartbeat_ns'] as int;
        final fresh = toNs(now) - heartbeat < kStaleLockAfter.inMicroseconds * 1000;
        if (fresh && rows.first['owner'] != owner) return false;
      }
      await txn.insert('run_lock', {'id': 1, 'owner': owner, 'acquired_at': utcIso(now), 'heartbeat_ns': toNs(now)},
          conflictAlgorithm: ConflictAlgorithm.replace);
      return true;
    });
  }

  Future<void> heartbeat(String owner, DateTime now) async {
    await (await _db).update('run_lock', {'heartbeat_ns': toNs(now)}, where: 'owner = ?', whereArgs: [owner]);
  }

  Future<void> releaseLock(String owner) async {
    await (await _db).delete('run_lock', where: 'owner = ?', whereArgs: [owner]);
  }

  Future<bool> isLocked(DateTime now) async {
    final rows = await (await _db).query('run_lock');
    return rows.isNotEmpty &&
        toNs(now) - (rows.first['heartbeat_ns'] as int) < kStaleLockAfter.inMicroseconds * 1000;
  }

  // ------------------------------------------------------------------ runs
  /// Runs left RUNNING by a killed process are closed as INTERRUPTED (their committed responses stay valid).
  Future<int> markInterruptedRuns(String exceptRunId, DateTime now) async {
    return (await _db).update('collection_runs', {'status': 'INTERRUPTED', 'finished_at': utcIso(now)},
        where: "status = 'RUNNING' AND run_id != ?", whereArgs: [exceptRunId]);
  }

  Future<void> beginRun(RunSummary s) async {
    await (await _db).insert('collection_runs', {
      'run_id': s.runId,
      'mode': s.mode,
      'collection_role': kCollectionRole,
      'study_manifest_sha256': kStudyManifestSha256,
      'label_manifest_sha256': kLabelManifestSha256,
      'universe_sha256': kUniverseSha256,
      'collector_version': kCollectorVersion,
      'scheduled_for': s.scheduledFor,
      'started_at': s.startedAt,
      'status': s.status,
      'symbols_requested': s.symbolsRequested,
      'network_type': s.networkType,
    });
  }

  Future<void> finishRun(RunSummary s) async {
    await (await _db).update(
      'collection_runs',
      {
        'finished_at': s.finishedAt,
        'status': s.status,
        'symbols_requested': s.symbolsRequested,
        'symbols_succeeded': s.symbolsSucceeded.length,
        'symbols_failed': s.symbolsFailed.length,
        'requests': s.requests,
        'new_bars_1m': s.newBars1m,
        'new_bars_5m': s.newBars5m,
        'duplicates': s.duplicates,
        'revisions': s.revisions,
        'partial_bars': s.partialBars,
        'finalizations': s.finalizations,
        'identity_matches': s.identityMatches,
        'identity_unverified': s.identityUnverified,
        'identity_mismatches': s.identityMismatches,
        'error_count': s.errorCount,
        'invalid_rows': s.invalidRows,
        'skipped_consumed_final': s.skippedConsumedFinal,
        'failed_symbols': jsonEncode(s.symbolsFailed),
        'network_type': s.networkType,
        'note': s.note,
      },
      where: 'run_id = ?',
      whereArgs: [s.runId],
    );
  }

  Future<void> logFailure(String runId, String symbol, String interval, DateTime now, String errorType,
      String message, {int? httpStatus}) async {
    await (await _db).insert('fetch_failures', {
      'run_id': runId,
      'collection_role': kCollectionRole,
      'symbol': symbol,
      'interval': interval,
      'timestamp': utcIso(now),
      'error_type': errorType,
      'message': message.length > 300 ? message.substring(0, 300) : message,
      'http_status': httpStatus,
    });
  }

  // ------------------------------------------------------------------ ingestion
  /// First-seen policy: the first completed observation of (symbol, interval, bar_start_utc) is immutable;
  /// a later different value goes to `bar_revisions`. Forming bars go to `partial_bars` only.
  /// `first_seen_at_utc` is always THIS response's retrieval time (recovered bars are not back-dated).
  Future<IngestCounts> ingest(FetchResult res, String runId) async {
    final c = IngestCounts();
    final stepNs = kIntervalSeconds[res.interval]! * 1000000000;
    final starts = [for (final b in res.bars) b.startNs];
    final partial = partialFlags(starts, res.interval, res.retrievedAt);
    final seenIso = utcIso(res.retrievedAt);
    final seenNs = toNs(res.retrievedAt);
    final rhash = res.responseHash;
    final anchors = {
      'study_manifest_sha256': kStudyManifestSha256,
      'label_manifest_sha256': kLabelManifestSha256,
      'universe_sha256': kUniverseSha256,
      'collector_version': kCollectorVersion,
      'collection_role': kCollectionRole,
      'primary_validation_eligible': 0,
    };
    await (await _db).transaction((txn) async {
      await txn.insert('requests', {
        'run_id': runId,
        'collection_role': kCollectionRole,
        'symbol': res.symbol,
        'provider_symbol_requested': res.providerSymbolRequested,
        'interval': res.interval,
        'range': res.range,
        'requested_at_utc': utcIso(res.requestedAt),
        'retrieved_at_utc': seenIso,
        'http_status': res.httpStatus,
        'provider_symbol': res.providerSymbol,
        'exchange': res.exchange,
        'currency': res.currency,
        'identity_status': res.identity,
        'response_hash': rhash,
        'n_rows': res.bars.length,
      });
      for (var i = 0; i < res.bars.length; i++) {
        final b = res.bars[i];
        final session = sessionDateOfNs(b.startNs);
        if (isConsumedFinalDay(session)) {
          c.skippedConsumedFinal++;
          continue;
        }
        if (!b.hasPrices) {
          c.invalidRows++;
          continue;
        }
        final startIso = utcIsoFromNs(b.startNs);
        final h = b.hash;
        final common = {
          ...anchors,
          'data_phase': dataPhaseOf(session),
          'symbol': res.symbol,
          'provider_symbol': res.providerSymbol,
          'interval': res.interval,
          'bar_start_utc': startIso,
          'bar_start_ns': b.startNs,
          'bar_end_utc': utcIsoFromNs(b.startNs + stepNs),
          'open': b.open,
          'high': b.high,
          'low': b.low,
          'close': b.close,
          'volume': b.volume,
          'identity_status': res.identity,
          'bar_hash': h,
          'response_hash': rhash,
          'session_date': session,
          'collection_run_id': runId,
        };
        if (partial[i]) {
          final id = await txn.insert('partial_bars', {...common, 'observed_at_utc': seenIso, 'is_partial': 1},
              conflictAlgorithm: ConflictAlgorithm.ignore);
          if (id > 0) c.partialObservations++;
          continue;
        }
        final key = [res.symbol, res.interval, startIso];
        final existing = await txn.query('bars',
            columns: ['bar_hash', ..._ohlcv],
            where: 'symbol = ? AND interval = ? AND bar_start_utc = ?',
            whereArgs: key);
        if (existing.isEmpty) {
          await txn.insert('bars', {
            ...common,
            'universe_role': universeRoleOf(res.symbol),
            'bar_start_local': istanbulIso(DateTime.fromMicrosecondsSinceEpoch(b.startNs ~/ 1000, isUtc: true)),
            'retrieved_at_utc': seenIso,
            'first_seen_at_utc': seenIso,
            'first_seen_ns': seenNs,
            'source': kSource,
            'exchange': res.exchange,
            'currency': res.currency,
            'is_partial': 0,
          });
          c.newBars++;
          final p = await txn.rawQuery(
              'SELECT MIN(observed_at_utc) AS first_at, COUNT(*) AS n, '
              '(SELECT bar_hash FROM partial_bars WHERE symbol = ? AND interval = ? AND bar_start_utc = ? '
              'ORDER BY id DESC LIMIT 1) AS last_hash '
              'FROM partial_bars WHERE symbol = ? AND interval = ? AND bar_start_utc = ?',
              [...key, ...key]);
          if ((p.first['n'] as int) > 0) {
            await txn.insert('bar_finalizations', {
              'symbol': res.symbol,
              'interval': res.interval,
              'bar_start_utc': startIso,
              'collection_role': kCollectionRole,
              'partial_first_seen_at': p.first['first_at'],
              'partial_observations': p.first['n'],
              'last_partial_hash': p.first['last_hash'],
              'final_hash': h,
              'finalized_first_seen_at': seenIso,
              'collection_run_id': runId,
            });
            c.finalizations++;
          }
          continue;
        }
        final original = existing.first;
        final originalHash = original['bar_hash'] as String;
        final last = await txn.query('bar_revisions',
            columns: ['new_hash', ..._ohlcv],
            where: 'symbol = ? AND interval = ? AND bar_start = ?',
            whereArgs: key,
            orderBy: 'id DESC',
            limit: 1);
        final previous = last.isEmpty ? original : last.first;
        final previousHash = last.isEmpty ? originalHash : last.first['new_hash'] as String;
        if (h == previousHash) {
          c.duplicates++;
          continue;
        }
        final values = {'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close, 'volume': b.volume};
        final changed = [for (final f in _ohlcv) if (previous[f] != values[f]) f];
        await txn.insert('bar_revisions', {
          'collection_role': kCollectionRole,
          'symbol': res.symbol,
          'interval': res.interval,
          'bar_start': startIso,
          'bar_start_ns': b.startNs,
          'original_hash': originalHash,
          'previous_hash': previousHash,
          'new_hash': h,
          'observed_at': seenIso,
          'changed_fields': jsonEncode(changed),
          ...values,
          'response_hash': rhash,
          'collection_run_id': runId,
        });
        c.revisions++;
      }
    });
    return c;
  }

  // ------------------------------------------------------------------ queries (collection only)
  Future<int> _count(String sql, [List<Object?> args = const []]) async =>
      Sqflite.firstIntValue(await (await _db).rawQuery(sql, args)) ?? 0;

  Future<Map<String, Object?>?> lastRun({String? mode, bool successfulOnly = false}) async {
    final where = <String>[];
    final args = <Object?>[];
    if (mode != null) {
      where.add('mode = ?');
      args.add(mode);
    }
    if (successfulOnly) where.add("status IN ('COMPLETED','PARTIAL')");
    final rows = await (await _db).query('collection_runs',
        where: where.isEmpty ? null : where.join(' AND '),
        whereArgs: args,
        orderBy: 'started_at DESC',
        limit: 1);
    return rows.isEmpty ? null : rows.first;
  }

  Future<List<Map<String, Object?>>> runs({int limit = 20}) async =>
      (await _db).query('collection_runs', orderBy: 'started_at DESC', limit: limit);

  Future<Map<String, Object?>> totals() async {
    return {
      'days_with_data': await _count('SELECT COUNT(DISTINCT session_date) FROM bars'),
      'assets': await _count('SELECT COUNT(DISTINCT symbol) FROM bars'),
      'bars_1m': await _count("SELECT COUNT(*) FROM bars WHERE interval = '1m'"),
      'bars_5m': await _count("SELECT COUNT(*) FROM bars WHERE interval = '5m'"),
      'latest_session': (await (await _db).rawQuery('SELECT MAX(session_date) AS d FROM bars')).first['d'],
    };
  }

  /// Today's collection status (local session date [day]).
  Future<Map<String, Object?>> dayStatus(String day) async {
    final bounds = [utcIso(fromIstanbulWallClock(_y(day), _m(day), _d(day))),
      utcIso(fromIstanbulWallClock(_y(day), _m(day), _d(day)).add(const Duration(days: 1)))];
    final run = (await (await _db).query('collection_runs',
            where: 'started_at >= ? AND started_at < ?', whereArgs: bounds, orderBy: 'started_at DESC', limit: 1))
        .firstOrNull;
    return {
      'last_run_today': run?['run_id'],
      'symbols_succeeded': run?['symbols_succeeded'] ?? 0,
      'symbols_failed': run?['symbols_failed'] ?? 0,
      'bars_1m': await _count("SELECT COUNT(*) FROM bars WHERE session_date = ? AND interval = '1m'", [day]),
      'bars_5m': await _count("SELECT COUNT(*) FROM bars WHERE session_date = ? AND interval = '5m'", [day]),
      'partial_bars': await _count('SELECT COUNT(*) FROM partial_bars WHERE session_date = ?', [day]),
      'revisions': await _count('SELECT COUNT(*) FROM bar_revisions WHERE observed_at >= ? AND observed_at < ?', bounds),
      'identity_mismatches': await _count(
          "SELECT COUNT(*) FROM requests WHERE identity_status = 'MISMATCH' AND retrieved_at_utc >= ? "
          'AND retrieved_at_utc < ?',
          bounds),
    };
  }

  Future<int> identityMismatchesTotal() =>
      _count("SELECT COUNT(*) FROM requests WHERE identity_status = 'MISMATCH'");

  Future<List<String>> mismatchSymbols() async => [
        for (final r in await (await _db).rawQuery(
            "SELECT DISTINCT symbol FROM requests WHERE identity_status = 'MISMATCH' ORDER BY symbol"))
          r['symbol'] as String
      ];

  Future<String> integrityCheck() async {
    final rows = await (await _db).rawQuery('PRAGMA integrity_check');
    return rows.map((r) => r.values.first.toString()).join('; ');
  }

  Future<int> countRows(String table) => _count('SELECT COUNT(*) FROM $table');

  static int _y(String d) => int.parse(d.substring(0, 4));
  static int _m(String d) => int.parse(d.substring(5, 7));
  static int _d(String d) => int.parse(d.substring(8, 10));
}
