import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/backtest_result.dart';
import '../../models/strategy_comparison.dart';
import '../../models/strategy_lab_run.dart';
import 'api_config.dart';

class BacktestApi {
  static const String baseUrl = apiBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final idToken = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (idToken != null) 'Authorization': 'Bearer $idToken',
    };
  }

  Future<BacktestResult> fetchBacktest(String symbol, {String period = '2y'}) async {
    final response = await http.get(Uri.parse('$baseUrl/backtest/$symbol?period=$period'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için backtest alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return BacktestResult.fromJson(json);
  }

  Future<StrategyComparisonResult> fetchStrategyComparison(String symbol, {String period = '2y'}) async {
    final response = await http.get(Uri.parse('$baseUrl/backtest/$symbol/compare-strategies?period=$period'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için strateji karşılaştırması alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return StrategyComparisonResult.fromJson(json);
  }

  /// AŞAMA 62: kullanıcı isteği "her test yaptığımızda veri tutsun" —
  /// Strateji Laboratuvarı taraması bitince sonucu kalıcı olarak kaydeder.
  Future<void> saveLabRun({
    required String period,
    required String universe,
    required int testedCount,
    required int failedCount,
    required List<StrategyPresetAggregate> results,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/backtest/lab-runs'),
      headers: await _authHeaders(),
      body: jsonEncode({
        'period': period,
        'universe': universe,
        'tested_count': testedCount,
        'failed_count': failedCount,
        'results': results.map((r) => r.toJson()).toList(),
      }),
    );
    if (response.statusCode != 200) {
      throw Exception('Test kaydedilemedi (HTTP ${response.statusCode})');
    }
  }

  Future<List<StrategyLabRun>> fetchLabRuns() async {
    final response = await http.get(Uri.parse('$baseUrl/backtest/lab-runs'), headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Test geçmişi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => StrategyLabRun.fromJson(e as Map<String, dynamic>)).toList();
  }
}
