import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/macro_snapshot.dart';
import '../../models/technical_analysis.dart';

class AnalysisApi {
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<TechnicalAnalysisDetail> fetchTechnical(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/analysis/$symbol/technical'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için teknik analiz alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return TechnicalAnalysisDetail.fromJson(json);
  }

  Future<MacroSnapshotDetail> fetchMacro() async {
    final response = await http.get(Uri.parse('$baseUrl/analysis/macro'));
    if (response.statusCode != 200) {
      throw Exception('Makro analiz alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return MacroSnapshotDetail.fromJson(json);
  }
}
