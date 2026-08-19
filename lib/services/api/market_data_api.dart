import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/price_quote.dart';
import 'api_config.dart';

class MarketDataApi {
  static const String baseUrl = apiBaseUrl;

  Future<PriceQuote> fetchQuote(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/market-data/$symbol/quote'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için güncel fiyat alınamadı (HTTP ${response.statusCode})");
    }
    return PriceQuote.fromJson(jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<List<PriceBar>> fetchHistory(String symbol, {required String period, required String interval}) async {
    final uri = Uri.parse('$baseUrl/market-data/$symbol/history?period=$period&interval=$interval');
    final response = await http.get(uri);
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için fiyat geçmişi alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => PriceBar.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Map<String, double?>> fetchChanges(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/market-data/$symbol/changes'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için yüzde değişimler alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return json.map((key, value) => MapEntry(key, (value as num?)?.toDouble()));
  }
}
