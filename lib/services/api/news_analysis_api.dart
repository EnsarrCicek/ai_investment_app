import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/news_analysis.dart';
import 'api_config.dart';

class NewsAnalysisApi {
  static const String baseUrl = apiBaseUrl;

  Future<List<NewsAnalysis>> fetchAnalysis(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/news/$symbol/analysis'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için haber analizi alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsAnalysis.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<NewsAnalysis>> analyze(String symbol, {int limit = 5}) async {
    // Auth zorunlu (AŞAMA 46): backend artık herkese açık bir adreste
    // çalıştığından, gerçek OpenAI maliyeti oluşturan bu uç nokta oturum
    // açmış kullanıcı gerektiriyor.
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    final uri = Uri.parse('$baseUrl/news/$symbol/analyze?limit=$limit');
    final response = await http.post(
      uri,
      headers: {if (token != null) 'Authorization': 'Bearer $token'},
    );
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için haber analizi yapılamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsAnalysis.fromJson(e as Map<String, dynamic>)).toList();
  }
}
