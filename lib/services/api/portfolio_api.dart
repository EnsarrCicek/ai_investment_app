import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/portfolio_position.dart';
import '../../models/portfolio_transaction.dart';
import 'api_config.dart';

class PortfolioApi {
  static const String baseUrl = apiBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<(List<PortfolioPosition>, PortfolioSummary)> fetchPositions() async {
    final response = await http.get(
      Uri.parse('$baseUrl/portfolio/positions'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Portföy alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    final positions = (json['positions'] as List)
        .map((e) => PortfolioPosition.fromJson(e as Map<String, dynamic>))
        .toList();
    final summary = PortfolioSummary.fromJson(json['summary'] as Map<String, dynamic>);
    return (positions, summary);
  }

  Future<void> createPosition({
    required String asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions'),
      headers: await _authHeaders(),
      body: jsonEncode({
        'asset': asset,
        'buy_price': buyPrice,
        'quantity': quantity,
        'buy_date': buyDate.toIso8601String(),
      }),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon eklenemedi (HTTP ${response.statusCode})');
    }
  }

  Future<void> updatePosition({
    required String asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
  }) async {
    final response = await http.put(
      Uri.parse('$baseUrl/portfolio/positions/$asset'),
      headers: await _authHeaders(),
      body: jsonEncode({
        'buy_price': buyPrice,
        'quantity': quantity,
        'buy_date': buyDate.toIso8601String(),
      }),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon güncellenemedi (HTTP ${response.statusCode})');
    }
  }

  Future<void> deletePosition(String asset) async {
    final response = await http.delete(
      Uri.parse('$baseUrl/portfolio/positions/$asset'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon silinemedi (HTTP ${response.statusCode})');
    }
  }

  /// "Sattım" akışı (AŞAMA 47): pozisyonu silmek yerine satış fiyatını
  /// kaydedip gerçekleşen kâr/zararı geçmişe (Portföy Geçmişi) ekler.
  Future<void> closePosition({required String asset, required double sellPrice}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions/$asset/close'),
      headers: await _authHeaders(),
      body: jsonEncode({'sell_price': sellPrice}),
    );
    if (response.statusCode != 200) {
      throw Exception('Pozisyon kapatılamadı (HTTP ${response.statusCode})');
    }
  }

  Future<PortfolioHistorySummary> fetchHistory() async {
    final response = await http.get(
      Uri.parse('$baseUrl/portfolio/history'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Portföy geçmişi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return PortfolioHistorySummary.fromJson(json);
  }
}
