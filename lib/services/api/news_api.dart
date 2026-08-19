import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/news_item.dart';
import 'api_config.dart';

class NewsApi {
  static const String baseUrl = apiBaseUrl;

  Future<List<NewsItem>> fetchNews(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/news/$symbol'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için haberler alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsItem.fromJson(e as Map<String, dynamic>)).toList();
  }
}
