import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../services/api/notification_api.dart';
import '../analysts/analysts_hub_screen.dart';
import '../guide/guide_screen.dart';
import '../ipo/ipo_list_screen.dart';
import '../notifications/notification_history_screen.dart';
import '../strategy_lab/strategy_lab_screen.dart';
import '../usage/usage_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _sendingTest = false;

  Future<void> _sendTestNotification() async {
    setState(() => _sendingTest = true);
    try {
      await NotificationApi().sendTestNotification();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Test bildirimi gönderildi. Bildirimler ekranından kontrol edebilirsiniz.')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Gönderilemedi: $e')));
      }
    } finally {
      if (mounted) setState(() => _sendingTest = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser;
    return Scaffold(
      appBar: AppBar(title: const Text('Ayarlar')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: ListTile(
              leading: const Icon(Icons.person_outline),
              title: const Text('Hesap'),
              subtitle: Text(user?.email ?? 'Bilinmiyor'),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.menu_book_outlined),
              title: const Text('Gösterge Rehberi'),
              subtitle: const Text('Ekranlardaki skor ve terimler ne anlama geliyor'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const GuideScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.account_balance_wallet_outlined),
              title: const Text('API Kullanımı'),
              subtitle: const Text('OpenAI harcaması ve kalan bakiye'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const UsageScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.science_outlined),
              title: const Text('Strateji Laboratuvarı'),
              subtitle: const Text('Farklı AL/SAT stratejilerini geçmiş verilerle karşılaştırın'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const StrategyLabScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.rocket_launch_outlined),
              title: const Text('Halka Arzlar'),
              subtitle: const Text('Güncel halka arz takvimi, gerçek haberler ve kendi notlarınız'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const IpoListScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.groups_outlined),
              title: const Text('Analistler'),
              subtitle: const Text('Hisse ve fonlar için gerçek analist AL/SAT görüşleri — kim ne demiş'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const AnalystsHubScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.notifications_outlined),
              title: const Text('Bildirimler'),
              subtitle: const Text('Gönderilen AL/SAT ve test bildirimlerinin geçmişi'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const NotificationHistoryScreen()),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.notifications_active_outlined),
              title: const Text('Test Bildirimi Gönder'),
              subtitle: const Text('Bildirimlerin cihazınızda çalışıp çalışmadığını kontrol edin'),
              trailing: _sendingTest
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.chevron_right),
              onTap: _sendingTest ? null : _sendTestNotification,
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.info_outline),
              title: const Text('Uygulama Sürümü'),
              subtitle: const Text('1.0.0'),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              leading: const Icon(Icons.logout, color: Colors.red),
              title: const Text('Çıkış Yap', style: TextStyle(color: Colors.red)),
              onTap: () => FirebaseAuth.instance.signOut(),
            ),
          ),
        ],
      ),
    );
  }
}
