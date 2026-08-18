import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import 'api/notification_api.dart';

/// FCM bildirimleri — AŞAMA 32. Bu projede bir zamanlayıcı (scheduler) yok;
/// backend, kullanıcı bir kararı sorguladığında (Dashboard her açıldığında
/// zaten oluyor) güçlü bir AL/SAT sinyali varsa bildirim gönderir (bkz.
/// backend/app/services/notifications/fcm_sender.py). Bu servis yalnızca
/// cihazı bildirime kaydeder ve uygulama ön plandayken gelen bildirimi
/// gösterir — arka planda/uygulama kapalıyken gelen bildirimleri işletim
/// sistemi zaten otomatik gösterir.
class NotificationService {
  static Future<void> initialize(BuildContext context) async {
    final messaging = FirebaseMessaging.instance;

    final settings = await messaging.requestPermission();
    if (settings.authorizationStatus == AuthorizationStatus.denied) {
      return;
    }

    final token = await messaging.getToken();
    if (token != null) {
      await _registerToken(token);
    }

    messaging.onTokenRefresh.listen(_registerToken);

    if (!context.mounted) return;
    FirebaseMessaging.onMessage.listen((message) {
      final notification = message.notification;
      if (notification == null || !context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${notification.title}: ${notification.body}')),
      );
    });
  }

  static Future<void> _registerToken(String token) async {
    try {
      await NotificationApi().registerToken(token);
    } catch (_) {
      // Kayıt başarısız olsa da uygulama akışını bozmamalı — sessizce yut.
    }
  }
}
