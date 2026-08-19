import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/backtest_result.dart';
import 'api_config.dart';

class BacktestApi {
  static const String baseUrl = apiBaseUrl;

  Future<BacktestResult> fetchBacktest(String symbol, {String period = '2y'}) async {
    final response = await http.get(Uri.parse('$baseUrl/backtest/$symbol?period=$period'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için backtest alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return BacktestResult.fromJson(json);
  }
}
