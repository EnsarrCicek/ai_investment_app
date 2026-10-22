import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../domain/collector_constants.dart';

/// Versioned schema of `momentum_shadow.db`. Each entry migrates from (index) to (index + 1); never edit an
/// entry once released, append a new one and bump [kSchemaVersion].
final List<List<String>> kMigrations = [_v1];

const _role = "collection_role TEXT NOT NULL CHECK (collection_role = 'MOBILE_SHADOW')";
const _anchors = 'study_manifest_sha256 TEXT NOT NULL, label_manifest_sha256 TEXT NOT NULL, '
    'universe_sha256 TEXT NOT NULL, collector_version TEXT NOT NULL';

const _appendOnly = ['bars', 'partial_bars', 'bar_revisions', 'bar_finalizations', 'fetch_failures', 'requests'];

final List<String> _v1 = [
  'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)',
  'CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)',
  'CREATE TABLE run_lock(id INTEGER PRIMARY KEY CHECK (id = 1), owner TEXT NOT NULL, acquired_at TEXT NOT NULL, '
      'heartbeat_ns INTEGER NOT NULL)',
  'CREATE TABLE collection_runs(run_id TEXT PRIMARY KEY, '
      "mode TEXT NOT NULL CHECK (mode IN ('BACKGROUND_EOD','MANUAL_SYNC')), $_role, $_anchors, "
      'scheduled_for TEXT, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, '
      'symbols_requested INTEGER NOT NULL DEFAULT 0, symbols_succeeded INTEGER NOT NULL DEFAULT 0, '
      'symbols_failed INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, '
      'new_bars_1m INTEGER NOT NULL DEFAULT 0, new_bars_5m INTEGER NOT NULL DEFAULT 0, '
      'duplicates INTEGER NOT NULL DEFAULT 0, revisions INTEGER NOT NULL DEFAULT 0, '
      'partial_bars INTEGER NOT NULL DEFAULT 0, finalizations INTEGER NOT NULL DEFAULT 0, '
      'identity_matches INTEGER NOT NULL DEFAULT 0, identity_unverified INTEGER NOT NULL DEFAULT 0, '
      'identity_mismatches INTEGER NOT NULL DEFAULT 0, error_count INTEGER NOT NULL DEFAULT 0, '
      'invalid_rows INTEGER NOT NULL DEFAULT 0, skipped_consumed_final INTEGER NOT NULL DEFAULT 0, '
      'failed_symbols TEXT, network_type TEXT, note TEXT)',
  'CREATE TABLE requests(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, $_role, symbol TEXT NOT NULL, '
      'provider_symbol_requested TEXT NOT NULL, interval TEXT NOT NULL, range TEXT NOT NULL, '
      'requested_at_utc TEXT NOT NULL, retrieved_at_utc TEXT NOT NULL, http_status INTEGER NOT NULL, '
      'provider_symbol TEXT, exchange TEXT, currency TEXT, identity_status TEXT NOT NULL, '
      'response_hash TEXT NOT NULL, n_rows INTEGER NOT NULL)',
  'CREATE TABLE bars(id INTEGER PRIMARY KEY AUTOINCREMENT, $_anchors, $_role, '
      'primary_validation_eligible INTEGER NOT NULL DEFAULT 0 CHECK (primary_validation_eligible = 0), '
      "data_phase TEXT NOT NULL CHECK (data_phase IN ('PRE_START_SHADOW','PROSPECTIVE_SHADOW')), "
      "universe_role TEXT NOT NULL CHECK (universe_role IN ('PRIMARY','BENCHMARK')), "
      "symbol TEXT NOT NULL, provider_symbol TEXT, interval TEXT NOT NULL CHECK (interval IN ('1m','5m')), "
      'bar_start_utc TEXT NOT NULL, bar_start_ns INTEGER NOT NULL, bar_start_local TEXT NOT NULL, '
      'bar_end_utc TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, '
      'volume REAL, retrieved_at_utc TEXT NOT NULL, first_seen_at_utc TEXT NOT NULL, first_seen_ns INTEGER NOT NULL, '
      'source TEXT NOT NULL, exchange TEXT, currency TEXT, '
      "identity_status TEXT NOT NULL CHECK (identity_status IN ('MATCH','UNVERIFIED','MISMATCH')), "
      'is_partial INTEGER NOT NULL CHECK (is_partial = 0), bar_hash TEXT NOT NULL, response_hash TEXT NOT NULL, '
      'session_date TEXT NOT NULL, collection_run_id TEXT NOT NULL, '
      'UNIQUE (symbol, interval, bar_start_utc))',
  'CREATE INDEX bars_session ON bars(session_date, interval)',
  'CREATE INDEX bars_run ON bars(collection_run_id)',
  'CREATE TABLE partial_bars(id INTEGER PRIMARY KEY AUTOINCREMENT, $_anchors, $_role, '
      'primary_validation_eligible INTEGER NOT NULL DEFAULT 0 CHECK (primary_validation_eligible = 0), '
      'data_phase TEXT NOT NULL, symbol TEXT NOT NULL, provider_symbol TEXT, interval TEXT NOT NULL, '
      'bar_start_utc TEXT NOT NULL, bar_start_ns INTEGER NOT NULL, bar_end_utc TEXT NOT NULL, '
      'open REAL, high REAL, low REAL, close REAL, volume REAL, observed_at_utc TEXT NOT NULL, '
      'identity_status TEXT NOT NULL, is_partial INTEGER NOT NULL CHECK (is_partial = 1), bar_hash TEXT NOT NULL, '
      'response_hash TEXT NOT NULL, session_date TEXT NOT NULL, collection_run_id TEXT NOT NULL, '
      'UNIQUE (symbol, interval, bar_start_utc, bar_hash))',
  'CREATE TABLE bar_finalizations(symbol TEXT NOT NULL, interval TEXT NOT NULL, bar_start_utc TEXT NOT NULL, '
      '$_role, partial_first_seen_at TEXT NOT NULL, partial_observations INTEGER NOT NULL, '
      'last_partial_hash TEXT NOT NULL, final_hash TEXT NOT NULL, finalized_first_seen_at TEXT NOT NULL, '
      'collection_run_id TEXT NOT NULL, PRIMARY KEY (symbol, interval, bar_start_utc))',
  'CREATE TABLE bar_revisions(id INTEGER PRIMARY KEY AUTOINCREMENT, $_role, symbol TEXT NOT NULL, '
      'interval TEXT NOT NULL, bar_start TEXT NOT NULL, bar_start_ns INTEGER NOT NULL, original_hash TEXT NOT NULL, '
      'previous_hash TEXT NOT NULL, new_hash TEXT NOT NULL, observed_at TEXT NOT NULL, changed_fields TEXT NOT NULL, '
      'open REAL, high REAL, low REAL, close REAL, volume REAL, response_hash TEXT NOT NULL, '
      'collection_run_id TEXT NOT NULL)',
  'CREATE TABLE fetch_failures(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, $_role, '
      'symbol TEXT NOT NULL, interval TEXT NOT NULL, timestamp TEXT NOT NULL, error_type TEXT NOT NULL, '
      'message TEXT NOT NULL, http_status INTEGER)',
  for (final t in _appendOnly) ...[
    "CREATE TRIGGER ${t}_no_update BEFORE UPDATE ON $t BEGIN SELECT RAISE(ABORT, '$t is append-only'); END",
    "CREATE TRIGGER ${t}_no_delete BEFORE DELETE ON $t BEGIN SELECT RAISE(ABORT, '$t is append-only'); END",
  ],
];

Future<void> applyMigrations(DatabaseExecutor db, int from, int to) async {
  if (to > kMigrations.length) throw StateError('no migration to schema v$to');
  for (var v = from; v < to; v++) {
    for (final stmt in kMigrations[v]) {
      await db.execute(stmt);
    }
  }
  await db.insert('meta', {'key': 'schema_version', 'value': '$to'}, conflictAlgorithm: ConflictAlgorithm.replace);
}

/// Opens (creating/migrating) the shadow database. A database newer than this app is refused instead of being
/// silently downgraded.
Future<Database> openCollectorDatabase(String path, {DatabaseFactory? factory, int version = kSchemaVersion}) {
  final f = factory ?? databaseFactory;
  return f.openDatabase(
    path,
    options: OpenDatabaseOptions(
      version: version,
      onConfigure: (db) async {
        await db.execute('PRAGMA foreign_keys = ON');
        // Rollback journal (not WAL): a closed database is one self-contained file, so export copies it whole.
        await db.rawQuery('PRAGMA journal_mode = DELETE');
      },
      onCreate: (db, v) async {
        await applyMigrations(db, 0, v);
        for (final e in studyAnchors().entries) {
          await db.insert('meta', {'key': e.key, 'value': e.value});
        }
        await db.insert('meta', {'key': 'created_with_app_version', 'value': kAppVersion});
      },
      onUpgrade: (db, from, to) => applyMigrations(db, from, to),
      onDowngrade: (db, from, to) =>
          throw StateError('momentum_shadow.db schema v$from is newer than this app (v$to); refusing to downgrade'),
    ),
  );
}

/// Lazily (re)opened database shared by the UI, manual sync and the background worker of this isolate.
class CollectorDatabase {
  final Future<String> Function() pathProvider;
  final DatabaseFactory? factory;
  Database? _db;
  Future<Database>? _opening;

  CollectorDatabase({required this.pathProvider, this.factory});

  static CollectorDatabase? _instance;

  /// Default on-device location: the app's private databases directory (no storage permission).
  static CollectorDatabase instance() => _instance ??= CollectorDatabase(
        pathProvider: () async => p.join(await getDatabasesPath(), kDatabaseName),
      );

  Future<String> get path => pathProvider();

  Future<Database> get db async {
    final current = _db;
    if (current != null && current.isOpen) return current;
    return _opening ??= () async {
      try {
        final opened = await openCollectorDatabase(await path, factory: factory);
        _db = opened;
        return opened;
      } finally {
        _opening = null;
      }
    }();
  }

  Future<void> close() async {
    final current = _db;
    _db = null;
    if (current != null && current.isOpen) await current.close();
  }
}
