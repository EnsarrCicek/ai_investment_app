import 'canonical.dart';
import 'collector_constants.dart';

/// One provider row exactly as received (null = provider sent no value; nothing is filled in).
class RawBar {
  final int startNs;
  final double? open;
  final double? high;
  final double? low;
  final double? close;
  final double? volume;

  const RawBar(this.startNs, this.open, this.high, this.low, this.close, this.volume);

  /// A completed/partial bar needs real OHLC values; volume may be missing (stored as null, never 0).
  bool get hasPrices => open != null && high != null && low != null && close != null;

  String get hash => barHash(open, high, low, close, volume);
}

/// Identity from provider metadata only. Missing field -> UNVERIFIED (TRY/IST is never assumed);
/// a reported value that differs from `<SYMBOL>.IS` / IST / TRY -> MISMATCH.
String identityStatus(String symbol, {String? reportedSymbol, String? exchange, String? currency}) {
  final reported = {'symbol': reportedSymbol, 'exchange': exchange, 'currency': currency};
  final expected = {'symbol': '$symbol.IS', 'exchange': kExpectedExchange, 'currency': kExpectedCurrency};
  final wrong = reported.entries.any((e) => e.value != null && e.value != expected[e.key]);
  if (wrong) return kIdentityMismatch;
  return reported.values.every((v) => v != null) ? kIdentityMatch : kIdentityUnverified;
}

class FetchResult {
  final String symbol;
  final String interval;
  final String range;
  final String providerSymbolRequested;
  final String? providerSymbol;
  final String? exchange;
  final String? currency;
  final String identity;
  final DateTime requestedAt;
  final DateTime retrievedAt;
  final int httpStatus;
  final List<RawBar> bars;

  FetchResult({
    required this.symbol,
    required this.interval,
    required this.range,
    required this.providerSymbolRequested,
    required this.providerSymbol,
    required this.exchange,
    required this.currency,
    required this.requestedAt,
    required this.retrievedAt,
    required this.httpStatus,
    required this.bars,
  }) : identity = identityStatus(symbol, reportedSymbol: providerSymbol, exchange: exchange, currency: currency);

  /// Same structure as the Windows `storage.response_hash`.
  String get responseHash => canonicalSha256({
        'symbol': symbol,
        'provider_symbol': providerSymbol,
        'interval': interval,
        'currency': currency,
        'exchange': exchange,
        'identity_check': identity,
        'source': kSource,
        'bars': [
          for (final b in bars) [b.startNs, b.open, b.high, b.low, b.close, b.volume]
        ],
      });
}

/// Per-response ingestion counters.
class IngestCounts {
  int newBars = 0;
  int duplicates = 0;
  int revisions = 0;
  int partialObservations = 0;
  int finalizations = 0;
  int invalidRows = 0;
  int skippedConsumedFinal = 0;
}

/// Collection-run summary (no model output of any kind).
class RunSummary {
  final String runId;
  final String mode;
  String? scheduledFor;
  final String startedAt;
  String? finishedAt;
  String status = 'RUNNING';
  int symbolsRequested = 0;
  final Set<String> succeeded = {};
  final Set<String> failed = {};
  int requests = 0;
  int newBars1m = 0;
  int newBars5m = 0;
  int duplicates = 0;
  int revisions = 0;
  int partialBars = 0;
  int finalizations = 0;
  int invalidRows = 0;
  int skippedConsumedFinal = 0;
  int identityMatches = 0;
  int identityUnverified = 0;
  int identityMismatches = 0;
  int errorCount = 0;
  String? networkType;
  String? note;

  RunSummary({required this.runId, required this.mode, required this.startedAt, this.scheduledFor});

  void addIngest(String interval, IngestCounts c) {
    if (interval == '1m') {
      newBars1m += c.newBars;
    } else {
      newBars5m += c.newBars;
    }
    duplicates += c.duplicates;
    revisions += c.revisions;
    partialBars += c.partialObservations;
    finalizations += c.finalizations;
    invalidRows += c.invalidRows;
    skippedConsumedFinal += c.skippedConsumedFinal;
  }

  void addIdentity(String identity) {
    if (identity == kIdentityMatch) {
      identityMatches++;
    } else if (identity == kIdentityMismatch) {
      identityMismatches++;
    } else {
      identityUnverified++;
    }
  }

  List<String> get symbolsSucceeded => (succeeded.difference(failed).toList()..sort());
  List<String> get symbolsFailed => (failed.toList()..sort());
}
