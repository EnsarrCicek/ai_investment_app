import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/fund_analysis.dart';
import '../../models/fund_position.dart';
import 'api_config.dart';

class FundApi {
  static const String baseUrl = apiBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final idToken = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (idToken != null) 'Authorization': 'Bearer $idToken',
    };
  }

  Future<List<FundAnalysis>> fetchFunds({int limit = 50}) async {
    final response = await http.get(
      Uri.parse('$baseUrl/funds?limit=$limit'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Fon listesi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => FundAnalysis.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<FundInvestmentSettings> fetchSettings() async {
    final response = await http.get(Uri.parse('$baseUrl/funds/settings'), headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Fon ayarları alınamadı (HTTP ${response.statusCode})');
    }
    return FundInvestmentSettings.fromJson(jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<void> updateSettings({double? monthlyIncome, required double monthlyBudget}) async {
    final response = await http.put(
      Uri.parse('$baseUrl/funds/settings'),
      headers: await _authHeaders(),
      body: jsonEncode({'monthly_income': monthlyIncome, 'monthly_budget': monthlyBudget}),
    );
    if (response.statusCode != 200) {
      throw Exception('Fon ayarları kaydedilemedi (HTTP ${response.statusCode})');
    }
  }

  Future<List<FundPosition>> fetchPositions() async {
    final response = await http.get(Uri.parse('$baseUrl/funds/positions'), headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Fonlarım alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => FundPosition.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> addPosition({required String fundCode, required double units, required double avgCost}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/funds/positions'),
      headers: await _authHeaders(),
      body: jsonEncode({'fund_code': fundCode, 'units': units, 'avg_cost': avgCost}),
    );
    if (response.statusCode != 200) {
      throw Exception('Fon eklenemedi (HTTP ${response.statusCode})');
    }
  }

  Future<void> deletePosition(String fundCode) async {
    final response = await http.delete(Uri.parse('$baseUrl/funds/positions/$fundCode'), headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Fon silinemedi (HTTP ${response.statusCode})');
    }
  }

  Future<List<FundAllocationItem>> allocate(double amountTl) async {
    final response = await http.post(
      Uri.parse('$baseUrl/funds/allocate'),
      headers: await _authHeaders(),
      body: jsonEncode({'amount_tl': amountTl}),
    );
    if (response.statusCode != 200) {
      throw Exception('Dağıtım önerisi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    final allocation = json['allocation'] as List;
    return allocation.map((e) => FundAllocationItem.fromJson(e as Map<String, dynamic>)).toList();
  }
}
