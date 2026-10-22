import 'dart:convert';

import '../data/collector_repository.dart';
import '../domain/collector_constants.dart';
import '../domain/market_time.dart';
import '../domain/study_anchors.g.dart';

/// Words that must never appear as a health key: the shadow collector reports collection health only, never
/// model/outcome information.
const List<String> kForbiddenHealthTerms = [
  'precision', 'recall', 'event', 'lead', 'watch', 'strong', 'buy', 'sell', 'hold', 'score', 'pass', 'fail_rate',
  'alert', 'signal', 'candidate', 'threshold', 'outcome',
];

/// Ordered key list of the health report (tests assert it contains no outcome terms).
const List<String> kHealthKeys = [
  'collection_role',
  'primary_validation_eligible',
  'database_integrity',
  'schema_version',
  'last_run_status',
  'last_run_mode',
  'last_run_started_at',
  'last_successful_run_at',
  'last_background_run_at',
  'days_with_data',
  'latest_session',
  'assets_with_data',
  'missing_assets_last_run',
  'identity_mismatches',
  'identity_mismatch_symbols',
  'background_scheduler_status',
  'next_background_slot',
  'study_manifest_sha256',
  'label_manifest_sha256',
  'universe_sha256',
];

class CollectorHealthService {
  final CollectorRepository repo;
  final DateTime Function() clock;

  CollectorHealthService(this.repo, {DateTime Function()? clock})
      : clock = clock ?? (() => DateTime.now().toUtc());

  Future<Map<String, Object?>> health() async {
    final last = await repo.lastRun();
    final lastOk = await repo.lastRun(successfulOnly: true);
    final lastBg = await repo.lastRun(mode: kModeBackgroundEod);
    final totals = await repo.totals();
    final failed = last?['failed_symbols'] as String?;
    final enabled = await repo.collectorEnabled();
    final schedulerError = await repo.setting(kSettingSchedulerError) ?? '';
    final registeredAt = await repo.setting(kSettingSchedulerRegisteredAt);
    final nextSlot = await repo.setting(kSettingSchedulerNextSlot) ?? '';
    final String scheduler;
    if (!enabled) {
      scheduler = 'DISABLED';
    } else if (schedulerError.isNotEmpty) {
      scheduler = 'ERROR: $schedulerError';
    } else if (registeredAt == null) {
      scheduler = 'NOT_REGISTERED';
    } else {
      scheduler = 'REGISTERED';
    }
    final integrity = await repo.integrityCheck();
    final out = <String, Object?>{
      'collection_role': kCollectionRole,
      'primary_validation_eligible': false,
      'database_integrity': integrity == 'ok' ? 'ok' : integrity,
      'schema_version': kSchemaVersion,
      'last_run_status': last?['status'],
      'last_run_mode': last?['mode'],
      'last_run_started_at': last?['started_at'],
      'last_successful_run_at': lastOk?['finished_at'],
      'last_background_run_at': lastBg?['started_at'],
      'days_with_data': totals['days_with_data'],
      'latest_session': totals['latest_session'],
      'assets_with_data': totals['assets'],
      'missing_assets_last_run': failed == null ? <String>[] : List<String>.from(jsonDecode(failed) as List),
      'identity_mismatches': await repo.identityMismatchesTotal(),
      'identity_mismatch_symbols': await repo.mismatchSymbols(),
      'background_scheduler_status': scheduler,
      'next_background_slot': nextSlot.isEmpty ? null : nextSlot,
      'study_manifest_sha256': kStudyManifestSha256,
      'label_manifest_sha256': kLabelManifestSha256,
      'universe_sha256': kUniverseSha256,
    };
    assert(out.keys.toList().join(',') == kHealthKeys.join(','));
    return out;
  }

  /// Approximate next background run for the UI (WorkManager may run later than the slot).
  Future<DateTime> approximateNextRun() async {
    final slot = await repo.setting(kSettingSchedulerNextSlot);
    if (slot != null && slot.isNotEmpty) {
      final t = DateTime.parse(slot);
      if (t.isAfter(clock())) return t;
    }
    return nextEodSlot(clock());
  }
}
