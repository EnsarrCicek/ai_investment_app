import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/analyst_consensus.dart';
import 'api_config.dart';

class AnalystApi {
  static const String baseUrl = apiBaseUrl;

  Future<AnalystConsensus> fetchConsensus(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/analysts/$symbol'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için analist konsensüsü alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes));
    return AnalystConsensus.fromJson(json as Map<String, dynamic>);
  }
}
