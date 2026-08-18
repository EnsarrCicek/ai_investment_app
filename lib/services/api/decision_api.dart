import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/decision.dart';
import '../../models/explanation.dart';

class DecisionApi {
  // Android emulator'de host makinenin localhost'una 10.0.2.2 üzerinden erişilir.
  // Fiziksel cihaz/prod ortamında bu değer gerçek backend URL'i ile değiştirilmelidir.
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<Decision> fetchDecision(String symbol) async {
    // Auth token buraya bilerek eklendi: backend GET /decisions/{symbol}
    // yalnızca kullanıcı kimliği çözülebiliyorsa (bu header ile) portföy
    // bildirimi (AŞAMA 45) tetikleyebiliyor. Token yoksa (misafir/oturum
    // yok) backend zaten opsiyonel kabul ediyor, normal çalışmaya devam eder.
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    final response = await http.get(
      Uri.parse('$baseUrl/decisions/$symbol'),
      headers: {if (token != null) 'Authorization': 'Bearer $token'},
    );
    if (response.statusCode != 200) {
      throw Exception(
        "'$symbol' için karar alınamadı (HTTP ${response.statusCode})",
      );
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes));
    return Decision.fromJson(json as Map<String, dynamic>);
  }

  Future<List<Decision>> fetchHistory(String symbol, {int limit = 20}) async {
    final response = await http.get(Uri.parse('$baseUrl/decisions/$symbol/history?limit=$limit'));
    if (response.statusCode != 200) {
      throw Exception("'$symbol' için karar geçmişi alınamadı (HTTP ${response.statusCode})");
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => Decision.fromJson(e as Map<String, dynamic>)).toList();
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
