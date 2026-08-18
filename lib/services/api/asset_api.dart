import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/asset.dart';

class AssetApi {
  static const String baseUrl = 'http://10.0.2.2:8000';

  Future<List<Asset>> fetchAssets() async {
    final response = await http.get(Uri.parse('$baseUrl/assets'));
    if (response.statusCode != 200) {
      throw Exception('Varlık listesi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => Asset.fromJson(e as Map<String, dynamic>)).toList();
  }
}
