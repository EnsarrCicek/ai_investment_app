import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/usage_summary.dart';
import 'api_config.dart';

class UsageApi {
  static const String baseUrl = apiBaseUrl;

  Future<UsageSummary> fetchUsage() async {
    final response = await http.get(Uri.parse('$baseUrl/usage'));
    if (response.statusCode != 200) {
      throw Exception('API kullanım bilgisi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return UsageSummary.fromJson(json);
  }
}
