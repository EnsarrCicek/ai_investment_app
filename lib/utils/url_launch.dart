import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Bir haber/makale bağlantısını cihazın tarayıcısında açar. Google News RSS
/// linkleri (news.google.com/rss/articles/...) gerçek makaleye istemci
/// tarafı JS ile yönlendiriyor — bu yüzden backend'de değil, burada (gerçek
/// bir tarayıcıda) açılması gerekiyor. Kullanıcı isteği: "haberlere
/// bastığımızda haberin detayı açılsın."
Future<void> openExternalUrl(BuildContext context, String url) async {
  final uri = Uri.tryParse(url);
  if (uri == null) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Geçersiz bağlantı: $url')));
    return;
  }
  final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
  if (!opened && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Bağlantı açılamadı: $url')));
  }
}
