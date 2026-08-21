import 'dart:async';

import 'package:flutter/material.dart';

import '../../models/asset.dart';
import '../../models/fund_analysis.dart';
import '../../services/api/asset_api.dart';
import '../../services/api/fund_api.dart';
import '../asset_detail/asset_detail_screen.dart';
import '../funds/fund_detail_screen.dart';

/// AŞAMA 64: kullanıcı isteği — "ayarlar sayfasında butonu olsun basınca
/// analistler kısmını açsın, fon ve hisselere dair neler demişler." Hisse
/// başına zaten var olan "Analistler" sekmesine (bkz. asset_detail_screen.dart)
/// ve fon detayındaki haber bölümüne buradan doğrudan, arama üzerinden
/// ulaşılır — tekrar bir analiz motoru YAZILMAZ, mevcut (ve zaten test
/// edilmiş) ekranlara tek bir merkezi giriş noktası sağlanır.
class AnalystsHubScreen extends StatelessWidget {
  const AnalystsHubScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Analistler'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Hisseler'),
              Tab(text: 'Fonlar'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _StockAnalystSearchTab(),
            _FundAnalystSearchTab(),
          ],
        ),
      ),
    );
  }
}

class _StockAnalystSearchTab extends StatefulWidget {
  const _StockAnalystSearchTab();

  @override
  State<_StockAnalystSearchTab> createState() => _StockAnalystSearchTabState();
}

class _StockAnalystSearchTabState extends State<_StockAnalystSearchTab> {
  late Future<List<Asset>> _future;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _future = AssetApi().fetchAssets();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            decoration: const InputDecoration(
              labelText: 'Hisse ara (kod veya isim)',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            onChanged: (value) => setState(() => _query = value.trim().toUpperCase()),
          ),
        ),
        Expanded(
          child: FutureBuilder<List<Asset>>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return Center(child: Text('Hata: ${snapshot.error}'));
              }
              final assets = snapshot.data!.where((a) {
                if (_query.isEmpty) return true;
                return a.symbol.toUpperCase().contains(_query) || a.name.toUpperCase().contains(_query);
              }).toList();
              if (assets.isEmpty) {
                return const Center(child: Text('Sonuç bulunamadı.'));
              }
              return ListView.builder(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: assets.length,
                itemBuilder: (context, index) {
                  final asset = assets[index];
                  return Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: const Icon(Icons.query_stats),
                      title: Text(asset.symbol, style: const TextStyle(fontWeight: FontWeight.bold)),
                      subtitle: Text(asset.name),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (context) => AssetDetailScreen(
                            symbol: asset.symbol,
                            initialTabIndex: assetDetailAnalystsTabIndex,
                          ),
                        ),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}

class _FundAnalystSearchTab extends StatefulWidget {
  const _FundAnalystSearchTab();

  @override
  State<_FundAnalystSearchTab> createState() => _FundAnalystSearchTabState();
}

class _FundAnalystSearchTabState extends State<_FundAnalystSearchTab> {
  static const int _defaultLimit = 30;
  static const int _searchLimit = 200;

  late Future<List<FundAnalysis>> _future;
  Timer? _debounce;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _future = FundApi().fetchFunds(limit: _defaultLimit);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () {
      setState(() {
        _query = value.trim();
        _future = FundApi().fetchFunds(
          limit: _query.isEmpty ? _defaultLimit : _searchLimit,
          q: _query.isEmpty ? null : _query,
        );
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            decoration: const InputDecoration(
              labelText: 'Fon ara (kod veya isim)',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            onChanged: _onSearchChanged,
          ),
        ),
        Expanded(
          child: FutureBuilder<List<FundAnalysis>>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return Center(child: Text('Hata: ${snapshot.error}'));
              }
              final funds = snapshot.data!;
              if (funds.isEmpty) {
                return const Center(child: Text('Sonuç bulunamadı.'));
              }
              return ListView.builder(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: funds.length,
                itemBuilder: (context, index) {
                  final fund = funds[index];
                  return Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: const Icon(Icons.savings_outlined),
                      title: Text(fund.fundCode, style: const TextStyle(fontWeight: FontWeight.bold)),
                      subtitle: Text(fund.fundName, maxLines: 2, overflow: TextOverflow.ellipsis),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(builder: (context) => FundDetailScreen(fundCode: fund.fundCode)),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}
