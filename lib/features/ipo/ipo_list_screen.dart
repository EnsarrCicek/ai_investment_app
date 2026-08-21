import 'package:flutter/material.dart';

import '../../models/ipo.dart';
import '../../services/api/ipo_api.dart';
import 'ipo_detail_screen.dart';

/// AŞAMA 67: kullanıcı isteği — "halka arz sayfası oluştur, hangisine
/// girmeliyim, ne kadar bütçeyle... internette araştırma yapıp bana girmem
/// gereken fiyatı gir." Kullanıcı onayladı: kesin bir "AL/GİRME" tavsiyesi
/// ÜRETİLMEZ — halkarz.com'dan (statik HTML, canlı test edildi) çekilen
/// GERÇEK halka arz takvimi/fiyat/tarih bilgisi olduğu gibi gösterilir,
/// karar kullanıcıya bırakılır.
class IpoListScreen extends StatefulWidget {
  const IpoListScreen({super.key});

  @override
  State<IpoListScreen> createState() => _IpoListScreenState();
}

class _IpoListScreenState extends State<IpoListScreen> {
  late Future<List<IpoListing>> _future;

  @override
  void initState() {
    super.initState();
    _future = IpoApi().fetchListings();
  }

  Future<void> _refresh() async {
    setState(() => _future = IpoApi().fetchListings());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Halka Arzlar')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<List<IpoListing>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  Padding(padding: const EdgeInsets.all(24), child: Center(child: Text('Hata: ${snapshot.error}'))),
                ],
              );
            }
            final listings = snapshot.data!;
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              children: [
                const Text(
                  'Veriler halkarz.com üzerinden gerçek zamanlı çekilir. Bu sayfa bir yatırım '
                  'tavsiyesi değildir — hangisine, ne kadar bütçeyle gireceğinize kendi '
                  'araştırmanızla karar vermeniz gerekir.',
                  style: TextStyle(fontSize: 11, color: Colors.grey),
                ),
                const SizedBox(height: 10),
                if (listings.isEmpty) const Text('Şu an listelenen bir halka arz yok.'),
                ...listings.map((l) => _IpoCard(listing: l)),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _IpoCard extends StatelessWidget {
  final IpoListing listing;
  const _IpoCard({required this.listing});

  Color _badgeColor(String badge) {
    if (badge.contains('Gong')) return Colors.green;
    if (badge.contains('Yeni')) return Colors.indigo;
    if (badge.contains('Ertelendi')) return Colors.red;
    return Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    final badge = listing.badgeText;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text(listing.companyName, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(listing.dateText, style: const TextStyle(fontSize: 12)),
              if (listing.bistCode != null)
                Text('Kod: ${listing.bistCode}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
            ],
          ),
        ),
        trailing: badge != null
            ? Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: _badgeColor(badge).withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  badge,
                  style: TextStyle(color: _badgeColor(badge), fontWeight: FontWeight.bold, fontSize: 11),
                ),
              )
            : const Icon(Icons.chevron_right),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (context) => IpoDetailScreen(listing: listing)),
        ),
      ),
    );
  }
}
