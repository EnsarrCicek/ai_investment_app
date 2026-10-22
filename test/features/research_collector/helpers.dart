import 'dart:io';

import 'package:ai_investment_app/features/research_collector/data/collector_database.dart';
import 'package:ai_investment_app/features/research_collector/data/collector_repository.dart';
import 'package:ai_investment_app/features/research_collector/data/yahoo_mobile_source.dart';
import 'package:ai_investment_app/features/research_collector/domain/market_time.dart';
import 'package:ai_investment_app/features/research_collector/domain/models.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

DatabaseFactory testFactory() {
  sqfliteFfiInit();
  return databaseFactoryFfi;
}

class TestDb {
  final Directory dir;
  final CollectorDatabase database;
  final CollectorRepository repo;

  TestDb._(this.dir, this.database) : repo = CollectorRepository(database);

  static Future<TestDb> create() async {
    final dir = await Directory.systemTemp.createTemp('shadow_test_');
    final database = CollectorDatabase(pathProvider: () async => '${dir.path}/momentum_shadow.db', factory: testFactory());
    return TestDb._(dir, database);
  }

  Future<void> dispose() async {
    await database.close();
    try {
      await dir.delete(recursive: true);
    } catch (_) {}
  }
}

/// Istanbul wall clock -> UTC instant.
DateTime ist(int y, int m, int d, int hh, int mm) => fromIstanbulWallClock(y, m, d, hh, mm);

int nsOf(DateTime t) => toNs(t);

RawBar bar(DateTime start, double o, double h, double l, double c, double? v) => RawBar(nsOf(start), o, h, l, c, v);

FetchResult result(
  String symbol,
  String interval,
  List<RawBar> bars, {
  required DateTime retrievedAt,
  String? providerSymbol,
  String? exchange = 'IST',
  String? currency = 'TRY',
}) =>
    FetchResult(
      symbol: symbol,
      interval: interval,
      range: '5d',
      providerSymbolRequested: '$symbol.IS',
      providerSymbol: providerSymbol ?? '$symbol.IS',
      exchange: exchange,
      currency: currency,
      requestedAt: retrievedAt.subtract(const Duration(milliseconds: 300)),
      retrievedAt: retrievedAt,
      httpStatus: 200,
      bars: bars,
    );

/// Fake source: (symbol|interval) -> result or exception; unknown keys fail.
class FakeSource implements MarketSource {
  final Map<String, Object> responses;
  final List<String> calls = [];

  FakeSource(this.responses);

  @override
  Future<FetchResult> fetch(String symbol, String interval, String range) async {
    calls.add('$symbol|$interval|$range');
    final r = responses['$symbol|$interval'];
    if (r is FetchResult) return r;
    if (r is Exception) throw r;
    throw SourceException('HttpError', 'HTTP 404', httpStatus: 404);
  }
}
