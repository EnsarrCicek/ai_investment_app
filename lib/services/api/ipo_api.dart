import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/ipo.dart';
import '../../models/news_item.dart';
import 'api_config.dart';

class IpoApi {
  static const String baseUrl = apiBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final idToken = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (idToken != null) 'Authorization': 'Bearer $idToken',
    };
  }

  Future<List<IpoListing>> fetchListings() async {
    final response = await http.get(Uri.parse('$baseUrl/ipo'));
    if (response.statusCode != 200) {
      throw Exception('Halka arz listesi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => IpoListing.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<IpoDetail> fetchDetail(String detailUrl) async {
    final uri = Uri.parse('$baseUrl/ipo/detail').replace(queryParameters: {'url': detailUrl});
    final response = await http.get(uri);
    if (response.statusCode != 200) {
      throw Exception('Halka arz detayı alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return IpoDetail.fromJson(json);
  }

  Future<List<NewsItem>> fetchNews(String companyName) async {
    final uri = Uri.parse('$baseUrl/ipo/news').replace(queryParameters: {'company': companyName});
    final response = await http.get(uri);
    if (response.statusCode != 200) {
      throw Exception('Halka arz haberleri alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => NewsItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<IpoNote> createNote({required String companyName, String? bistCode, required String noteText}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/ipo/notes'),
      headers: await _authHeaders(),
      body: jsonEncode({'company_name': companyName, 'bist_code': bistCode, 'note_text': noteText}),
    );
    if (response.statusCode != 200) {
      throw Exception('Not kaydedilemedi (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return IpoNote.fromJson(json);
  }

  Future<List<IpoNote>> fetchNotes({String? companyName}) async {
    final uri = Uri.parse(
      '$baseUrl/ipo/notes',
    ).replace(queryParameters: companyName != null ? {'company_name': companyName} : null);
    final response = await http.get(uri, headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Notlar alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List;
    return json.map((e) => IpoNote.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> deleteNote(String noteId) async {
    final response = await http.delete(Uri.parse('$baseUrl/ipo/notes/$noteId'), headers: await _authHeaders());
    if (response.statusCode != 200) {
      throw Exception('Not silinemedi (HTTP ${response.statusCode})');
    }
  }
}
