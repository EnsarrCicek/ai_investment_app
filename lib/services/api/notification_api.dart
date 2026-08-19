import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import '../../models/notification_record.dart';
import 'api_config.dart';

class NotificationApi {
  static const String baseUrl = apiBaseUrl;

  Future<Map<String, String>> _authHeaders() async {
    final idToken = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (idToken != null) 'Authorization': 'Bearer $idToken',
    };
  }

  Future<void> registerToken(String token) async {
    final idToken = await FirebaseAuth.instance.currentUser?.getIdToken();
    if (idToken == null) return;

    final response = await http.post(
      Uri.parse('$baseUrl/notifications/register-token'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $idToken',
      },
      body: jsonEncode({'token': token}),
    );
    if (response.statusCode != 200) {
      throw Exception('Bildirim cihazı kaydedilemedi (HTTP ${response.statusCode})');
    }
  }

  /// AŞAMA 48/20: Ayarlar ekranındaki "Test Bildirimi Gönder" butonu —
  /// FCM'in gerçek bir cihazda uçtan uca çalışıp çalışmadığını doğrular.
  Future<void> sendTestNotification() async {
    final response = await http.post(
      Uri.parse('$baseUrl/notifications/test'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      final body = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      throw Exception(body['detail'] as String? ?? 'Test bildirimi gönderilemedi (HTTP ${response.statusCode})');
    }
  }

  Future<List<NotificationRecord>> fetchHistory() async {
    final response = await http.get(
      Uri.parse('$baseUrl/notifications/history'),
      headers: await _authHeaders(),
    );
    if (response.statusCode != 200) {
      throw Exception('Bildirim geçmişi alınamadı (HTTP ${response.statusCode})');
    }
    final json = jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
    return json.map((e) => NotificationRecord.fromJson(e as Map<String, dynamic>)).toList();
  }
}
