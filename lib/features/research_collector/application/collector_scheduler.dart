import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:workmanager/workmanager.dart';

import '../data/collector_database.dart';
import '../data/collector_repository.dart';
import '../data/yahoo_mobile_source.dart';
import '../domain/collector_constants.dart';
import '../domain/market_time.dart';
import 'mobile_collector_service.dart';

const String kEodTaskName = 'momentumShadowEod';
const String kEodTaskTag = 'momentum_shadow_eod';
const String kInputSlot = 'slot_utc';

/// One registration request handed to WorkManager (kept platform-free so it can be tested).
class EodRegistration {
  final String uniqueName;
  final String taskName;
  final String tag;
  final Duration initialDelay;
  final DateTime slot;
  final bool unmeteredOnly;

  const EodRegistration({
    required this.uniqueName,
    required this.taskName,
    required this.tag,
    required this.initialDelay,
    required this.slot,
    required this.unmeteredOnly,
  });
}

abstract class BackgroundRegistrar {
  Future<void> registerOneOff(EodRegistration r);
  Future<void> cancelAll(String tag);
}

class WorkmanagerRegistrar implements BackgroundRegistrar {
  @override
  Future<void> registerOneOff(EodRegistration r) => Workmanager().registerOneOffTask(
        r.uniqueName,
        r.taskName,
        tag: r.tag,
        initialDelay: r.initialDelay,
        inputData: {kInputSlot: utcIso(r.slot)},
        constraints: Constraints(networkType: r.unmeteredOnly ? NetworkType.unmetered : NetworkType.connected),
        existingWorkPolicy: ExistingWorkPolicy.keep,
        backoffPolicy: BackoffPolicy.exponential,
        backoffPolicyDelay: const Duration(minutes: 15),
      );

  @override
  Future<void> cancelAll(String tag) => Workmanager().cancelByTag(tag);
}

/// Daily EOD shadow archive scheduling.
///
/// Android WorkManager gives no exact-time guarantee, so the plan is a chain of one-off works, one per weekday
/// slot (19:15 Istanbul), each with a unique name per slot (`momentum_shadow_eod_YYYY-MM-DD`, policy KEEP). The
/// next slot is enqueued from app start and again at the start of every background run, so the delay is always
/// recomputed from the real clock (no drift) and a killed run cannot break the chain. Each run stores
/// `scheduled_for` / `started_at` / `finished_at`. No 5-minute probing is attempted in this version.
class CollectorScheduler {
  final CollectorRepository repo;
  final BackgroundRegistrar registrar;
  final DateTime Function() clock;

  CollectorScheduler({required this.repo, required this.registrar, DateTime Function()? clock})
      : clock = clock ?? (() => DateTime.now().toUtc());

  static String uniqueNameFor(DateTime slot) => '${kEodTaskTag}_${sessionDateOf(slot)}';

  EodRegistration planAfter(DateTime now, {required bool unmeteredOnly}) {
    final slot = nextEodSlot(now);
    return EodRegistration(
      uniqueName: uniqueNameFor(slot),
      taskName: kEodTaskName,
      tag: kEodTaskTag,
      initialDelay: slot.difference(now.toUtc()),
      slot: slot,
      unmeteredOnly: unmeteredOnly,
    );
  }

  /// Registers the next slot when the collector is enabled; cancels everything when disabled.
  Future<EodRegistration?> ensureScheduled({bool reset = false}) async {
    final now = clock();
    if (!await repo.collectorEnabled()) {
      await registrar.cancelAll(kEodTaskTag);
      await repo.setSetting(kSettingSchedulerNextSlot, '', now);
      return null;
    }
    final unmetered = !await repo.collectOnMobileData();
    if (reset) await registrar.cancelAll(kEodTaskTag);
    final plan = planAfter(now, unmeteredOnly: unmetered);
    await registrar.registerOneOff(plan);
    await repo.setSetting(kSettingSchedulerRegisteredAt, utcIso(now), now);
    await repo.setSetting(kSettingSchedulerNextSlot, utcIso(plan.slot), now);
    await repo.setSetting(kSettingSchedulerNetworkType, unmetered ? 'unmetered' : 'connected', now);
    await repo.setSetting(kSettingSchedulerError, '', now);
    if (await repo.setting(kSettingSetupCompletedAt) == null) {
      await repo.setSetting(kSettingSetupCompletedAt, utcIso(now), now);
    }
    return plan;
  }
}

Future<NetworkKind> currentNetworkKind() async {
  final results = await Connectivity().checkConnectivity();
  if (results.contains(ConnectivityResult.wifi) || results.contains(ConnectivityResult.ethernet)) {
    return NetworkKind.wifi;
  }
  if (results.contains(ConnectivityResult.mobile)) return NetworkKind.mobile;
  if (results.isEmpty || results.every((r) => r == ConnectivityResult.none)) return NetworkKind.none;
  return NetworkKind.other;
}

/// Background entry point (separate isolate / engine). Touches only the local shadow DB and Yahoo — never
/// Firebase/Firestore.
@pragma('vm:entry-point')
void collectorCallbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    if (task != kEodTaskName) return true;
    final repo = CollectorRepository(CollectorDatabase.instance());
    if (!await repo.collectorEnabled()) return true;
    // Chain first: even if this run is killed, the next weekday slot is already enqueued.
    await CollectorScheduler(repo: repo, registrar: WorkmanagerRegistrar()).ensureScheduled();
    final slotIso = inputData?[kInputSlot] as String?;
    final summary = await MobileCollectorService(repo: repo, source: YahooMobileSource(), network: currentNetworkKind)
        .run(mode: kModeBackgroundEod, scheduledFor: slotIso == null ? null : DateTime.parse(slotIso));
    // Retry later only when nothing could be collected because of the network.
    return summary.status != 'FAILED' && summary.status != 'SKIPPED_NO_NETWORK';
  });
}

/// App start: initialize WorkManager and make sure the next slot is registered (first launch = setup).
Future<void> initializeCollectorBackground() async {
  if (kIsWeb || !Platform.isAndroid) return;
  final repo = CollectorRepository(CollectorDatabase.instance());
  try {
    await Workmanager().initialize(collectorCallbackDispatcher);
    await CollectorScheduler(repo: repo, registrar: WorkmanagerRegistrar()).ensureScheduled();
  } catch (e) {
    final msg = e.toString();
    try {
      await repo.setSetting(kSettingSchedulerError, msg.length > 300 ? msg.substring(0, 300) : msg, DateTime.now().toUtc());
    } catch (_) {
      // DB unavailable: the collector page shows the scheduler as NOT_REGISTERED.
    }
  }
}
