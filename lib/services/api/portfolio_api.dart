import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/portfolio_position.dart';

class PortfolioApi {
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<(List<PortfolioPosition>, PortfolioSummary)> fetchPositions(String userId) async {
    final response = await http.get(Uri.parse('$baseUrl/portfolio/positions?user_id=$userId'));
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
    required String userId,
    required String asset,
    required double buyPrice,
    required double quantity,
    required DateTime buyDate,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/portfolio/positions'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'user_id': userId,
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

  Future<void> deletePosition(String id) async {
    final response = await http.delete(Uri.parse('$baseUrl/portfolio/positions/$id'));
    if (response.statusCode != 200) {
      throw Exception('Pozisyon silinemedi (HTTP ${response.statusCode})');
    }
  }
}
