import 'dart:math';

import '../data/collector_repository.dart';
import '../data/yahoo_mobile_source.dart';
import '../domain/collector_constants.dart';
import '../domain/market_time.dart';
import '../domain/models.dart';

enum NetworkKind { none, wifi, mobile, other }

class CancelToken {
  bool _cancelled = false;
  bool get isCancelled => _cancelled;
  void cancel() => _cancelled = true;
}

typedef ProgressCallback = void Function(int done, int total, String symbol);

/// EOD/recovery collection of the shadow universe (87 primary assets + XU100) for 1m and 5m, range=5d.
/// One failing symbol never stops the run and never produces bars.
class MobileCollectorService {
  final CollectorRepository repo;
  final MarketSource source;
  final DateTime Function() clock;
  final Future<NetworkKind> Function() network;
  final Duration pauseBetweenRequests;

  MobileCollectorService({
    required this.repo,
    required this.source,
    required this.network,
    DateTime Function()? clock,
    this.pauseBetweenRequests = const Duration(milliseconds: 250),
  }) : clock = clock ?? (() => DateTime.now().toUtc());

  static String newRunId(String mode, DateTime now) {
    final r = Random.secure().nextInt(1 << 32).toRadixString(16).padLeft(8, '0');
    return '${mode.toLowerCase()}_${utcIso(now).replaceAll(RegExp(r'[^0-9T]'), '').substring(0, 15)}_$r';
  }

  Future<RunSummary> run({
    required String mode,
    DateTime? scheduledFor,
    CancelToken? cancel,
    ProgressCallback? onProgress,
    List<String>? symbols,
  }) async {
    final start = clock();
    final summary = RunSummary(
      runId: newRunId(mode, start),
      mode: mode,
      startedAt: utcIso(start),
      scheduledFor: scheduledFor == null ? null : utcIso(scheduledFor),
    );
    final plan = symbols ?? shadowSymbols();
    summary.symbolsRequested = plan.length;
    final net = await network();
    summary.networkType = net.name;

    if (!await repo.acquireLock(summary.runId, start)) {
      summary
        ..status = 'SKIPPED_ALREADY_RUNNING'
        ..finishedAt = utcIso(clock());
      await repo.beginRun(summary);
      await repo.finishRun(summary);
      return summary;
    }
    try {
      await repo.markInterruptedRuns(summary.runId, start);
      await repo.beginRun(summary);
      String? skip;
      if (net == NetworkKind.none) skip = 'SKIPPED_NO_NETWORK';
      if (net == NetworkKind.mobile && !await repo.collectOnMobileData()) skip = 'SKIPPED_MOBILE_DATA_DISABLED';
      if (skip != null) {
        summary
          ..status = skip
          ..finishedAt = utcIso(clock());
        await repo.finishRun(summary);
        return summary;
      }
      var done = 0;
      for (final symbol in plan) {
        if (cancel?.isCancelled ?? false) break;
        for (final interval in kIntervals) {
          if (cancel?.isCancelled ?? false) break;
          summary.requests++;
          try {
            final res = await source.fetch(symbol, interval, kRecoveryRange);
            if (res.bars.isEmpty) throw SourceException('EmptyResponse', "'$symbol' $interval no bars");
            summary.addIdentity(res.identity);
            summary.addIngest(interval, await repo.ingest(res, summary.runId));
            summary.succeeded.add(symbol);
          } catch (e) {
            final typed = e is SourceException ? e : SourceException(e.runtimeType.toString(), e.toString());
            summary.failed.add(symbol);
            summary.errorCount++;
            await repo.logFailure(summary.runId, symbol, interval, clock(), typed.errorType, typed.message,
                httpStatus: typed.httpStatus);
          }
          await repo.heartbeat(summary.runId, clock());
          if (pauseBetweenRequests > Duration.zero) await Future<void>.delayed(pauseBetweenRequests);
        }
        done++;
        onProgress?.call(done, plan.length, symbol);
      }
      final cancelled = cancel?.isCancelled ?? false;
      final ok = summary.symbolsSucceeded.length;
      summary.status = cancelled
          ? 'CANCELLED'
          : ok == 0
              ? 'FAILED'
              : summary.failed.isEmpty
                  ? 'COMPLETED'
                  : 'PARTIAL';
      summary.finishedAt = utcIso(clock());
      await repo.finishRun(summary);
      return summary;
    } catch (e) {
      summary
        ..status = 'ERROR'
        ..note = e.toString().length > 300 ? e.toString().substring(0, 300) : e.toString()
        ..finishedAt = utcIso(clock());
      await repo.finishRun(summary);
      return summary;
    } finally {
      await repo.releaseLock(summary.runId);
    }
  }
}
