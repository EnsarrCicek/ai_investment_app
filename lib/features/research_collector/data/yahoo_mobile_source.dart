import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../domain/models.dart';

/// Typed fetch failure; [errorType] is stored in `fetch_failures.error_type`.
class SourceException implements Exception {
  final String errorType;
  final String message;
  final int? httpStatus;

  SourceException(this.errorType, this.message, {this.httpStatus});

  @override
  String toString() => '$errorType: $message';
}

abstract class MarketSource {
  Future<FetchResult> fetch(String symbol, String interval, String range);
}

/// Parses a Yahoo v8 chart response. Rows are taken as-is: no forward fill, no zero volume, no defaults.
FetchResult parseChartResponse({
  required String symbol,
  required String interval,
  required String range,
  required String body,
  required int httpStatus,
  required DateTime requestedAt,
  required DateTime retrievedAt,
}) {
  final Object? decoded;
  try {
    decoded = jsonDecode(body);
  } on FormatException catch (e) {
    throw SourceException('ParseError', 'invalid JSON: ${e.message}', httpStatus: httpStatus);
  }
  final chart = decoded is Map ? decoded['chart'] : null;
  if (chart is! Map) throw SourceException('ParseError', 'missing chart object', httpStatus: httpStatus);
  final error = chart['error'];
  if (error != null) {
    final code = error is Map ? '${error['code']}' : '$error';
    throw SourceException('ProviderError', code, httpStatus: httpStatus);
  }
  final results = chart['result'];
  if (results is! List || results.isEmpty || results.first is! Map) {
    throw SourceException('EmptyResponse', "'$symbol' $interval empty result", httpStatus: httpStatus);
  }
  final result = results.first as Map;
  final meta = result['meta'] is Map ? result['meta'] as Map : const {};
  final timestamps = result['timestamp'];
  final indicators = result['indicators'];
  final quotes = indicators is Map ? indicators['quote'] : null;
  if (timestamps is! List || timestamps.isEmpty || quotes is! List || quotes.isEmpty || quotes.first is! Map) {
    throw SourceException('EmptyResponse', "'$symbol' $interval no bars", httpStatus: httpStatus);
  }
  final q = quotes.first as Map;
  double? at(String key, int i) {
    final col = q[key];
    if (col is! List || i >= col.length) return null;
    final v = col[i];
    return v is num && v.isFinite ? v.toDouble() : null;
  }

  final bars = <RawBar>[];
  for (var i = 0; i < timestamps.length; i++) {
    final ts = timestamps[i];
    if (ts is! int) continue;
    bars.add(RawBar(ts * 1000000000, at('open', i), at('high', i), at('low', i), at('close', i), at('volume', i)));
  }
  bars.sort((a, b) => a.startNs.compareTo(b.startNs));
  String? str(Object? v) => v is String && v.isNotEmpty ? v : null;
  return FetchResult(
    symbol: symbol,
    interval: interval,
    range: range,
    providerSymbolRequested: '$symbol.IS',
    providerSymbol: str(meta['symbol']),
    exchange: str(meta['exchangeName']),
    currency: str(meta['currency']),
    requestedAt: requestedAt,
    retrievedAt: retrievedAt,
    httpStatus: httpStatus,
    bars: bars,
  );
}

/// Yahoo intraday chart endpoint over plain HTTPS (no API key, no cookies stored, nothing personal sent).
class YahooMobileSource implements MarketSource {
  static const _host = 'query1.finance.yahoo.com';
  static const _userAgent = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36';

  final http.Client client;
  final Duration timeout;
  final int maxAttempts;
  final Duration retryDelay;
  final DateTime Function() clock;

  YahooMobileSource({
    http.Client? client,
    this.timeout = const Duration(seconds: 20),
    this.maxAttempts = 3,
    this.retryDelay = const Duration(seconds: 2),
    DateTime Function()? clock,
  })  : client = client ?? http.Client(),
        clock = clock ?? (() => DateTime.now().toUtc());

  static Uri chartUri(String symbol, String interval, String range) => Uri.https(_host, '/v8/finance/chart/$symbol.IS', {
        'interval': interval,
        'range': range,
        'includePrePost': 'false',
      });

  @override
  Future<FetchResult> fetch(String symbol, String interval, String range) async {
    final uri = chartUri(symbol, interval, range);
    SourceException? last;
    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      final requestedAt = clock();
      try {
        final resp = await client.get(uri, headers: {'User-Agent': _userAgent, 'Accept': 'application/json'}).timeout(timeout);
        final retrievedAt = clock();
        if (resp.statusCode == 429 || resp.statusCode >= 500) {
          last = SourceException('HttpError', 'HTTP ${resp.statusCode}', httpStatus: resp.statusCode);
        } else if (resp.statusCode != 200) {
          // 404 etc.: Yahoo still sends a chart.error body; parse it for a typed error, never retry.
          try {
            parseChartResponse(
                symbol: symbol,
                interval: interval,
                range: range,
                body: resp.body,
                httpStatus: resp.statusCode,
                requestedAt: requestedAt,
                retrievedAt: retrievedAt);
          } on SourceException catch (e) {
            throw SourceException(e.errorType, '${e.message} (HTTP ${resp.statusCode})', httpStatus: resp.statusCode);
          }
          throw SourceException('HttpError', 'HTTP ${resp.statusCode}', httpStatus: resp.statusCode);
        } else {
          return parseChartResponse(
              symbol: symbol,
              interval: interval,
              range: range,
              body: resp.body,
              httpStatus: resp.statusCode,
              requestedAt: requestedAt,
              retrievedAt: retrievedAt);
        }
      } on TimeoutException {
        last = SourceException('Timeout', 'no response within ${timeout.inSeconds}s');
      } on http.ClientException catch (e) {
        last = SourceException('NetworkError', e.message);
      }
      if (attempt < maxAttempts) await Future<void>.delayed(retryDelay * attempt);
    }
    throw last!;
  }
}
