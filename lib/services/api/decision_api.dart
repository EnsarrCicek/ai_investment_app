import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/decision.dart';
import '../../models/explanation.dart';

class DecisionApi {
  // Android emulator'de host makinenin localhost'una 10.0.2.2 üzerinden erişilir.
  // Fiziksel cihaz/prod ortamında bu değer gerçek backend URL'i ile değiştirilmelidir.
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<Decision> fetchDecision(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/decisions/$symbol'));
    if (response.statusCode != 200) {
      throw Exception(
        "'$symbol' için karar alınamadı (HTTP ${response.statusCode})",
      );
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes));
    return Decision.fromJson(json as Map<String, dynamic>);
  }

  Future<Explanation> fetchExplanation(String symbol) async {
    final response = await http.get(Uri.parse('$baseUrl/decisions/$symbol/explanation'));
    if (response.statusCode != 200) {
      throw Exception(
        "'$symbol' için açıklama alınamadı (HTTP ${response.statusCode})",
      );
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes));
    return Explanation.fromJson(json as Map<String, dynamic>);
  }
}
