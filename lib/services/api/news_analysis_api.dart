import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/news_analysis.dart';

class NewsAnalysisApi {
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<List<NewsAnalysis>> fetchAnalysis(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/news/$symbol/analysis'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için haber analizi alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsAnalysis.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<NewsAnalysis>> analyze(String symbol, {int limit = 5}) async {
    final uri = Uri.parse('$baseUrl/news/$symbol/analyze?limit=$limit');
    final response = await http.post(uri);
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için haber analizi yapılamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsAnalysis.fromJson(e as Map<String, dynamic>)).toList();
  }
}
