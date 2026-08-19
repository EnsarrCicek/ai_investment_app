import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

import 'api_config.dart';

class NotificationApi {
  static const String baseUrl = apiBaseUrl;

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
}
