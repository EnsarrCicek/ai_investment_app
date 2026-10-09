import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';
import '../../widgets/explanation_content.dart';

import '../../models/decision_dashboard.dart';
import '../../models/explanation.dart';
import '../../services/api/decision_api.dart';
import '../../utils/decision_style.dart';
import '../../utils/percent_format.dart';
import '../asset_detail/asset_detail_screen.dart';

class DashboardScreen extends StatefulWidget {
  /// Testler için enjekte edilebilir; varsayılan tek `GET /decisions/dashboard` isteği.
  final Future<DecisionDashboard> Function()? loadDashboard;

  const DashboardScreen({super.key, this.loadDashboard});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<DecisionDashboard> _future;
  final _searchController = TextEditingController();
  bool _searching = false;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _future = _loadAll();
    _searchController.addListener(() {
      setState(() => _query = _searchController.text.trim().toUpperCase());
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _startSearch() {
    setState(() => _searching = true);
  }

  void _stopSearch() {
    setState(() {
      _searching = false;
      _query = '';
      _searchController.clear();
    });
  }

  // Tek istek: backend BIST100'ün tamamı için kararları toplu ve salt-okunur üretir (eskiden `/assets` + 100 ayrı
  // `/decisions/{symbol}` isteği, her biri ortak Firestore verisini yeniden okuyup kayıt yazıyordu). Sıralama
  // (en güçlü AL üstte, karar üretilemeyenler en altta) backend'de yapılır.
  Future<DecisionDashboard> _loadAll() => (widget.loadDashboard ?? DecisionApi().fetchDashboard)();

  Future<void> _refresh() async {
    setState(() {
      _future = _loadAll();
    });
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: GradientAppBar(
        title: _searching
            ? TextField(
                controller: _searchController,
                autofocus: true,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(
                  hintText: 'Hisse ara (ör. THYAO)',
                  border: InputBorder.none,
                ),
              )
            : const Text('Piyasa Analizi'),
        actions: [
          IconButton(
            icon: Icon(_searching ? Icons.close : Icons.search),
            onPressed: _searching ? _stopSearch : _startSearch,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<DecisionDashboard>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(24),
                    child: Center(child: Text('${snapshot.error}'.replaceFirst('Exception: ', ''))),
                  ),
                ],
              );
            }
            final dashboard = snapshot.data!;
            final allResults = dashboard.items;
            final results = _query.isEmpty
                ? allResults
                : allResults.where((r) => r.asset.contains(_query)).toList();
            final header = _DashboardHeader(dashboard: dashboard);

            if (results.isEmpty) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  header,
                  Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: Center(
                      child: Text(_query.isEmpty ? 'Gösterilecek varlık yok.' : '"$_query" için sonuç bulunamadı.'),
                    ),
                  ),
                ],
              );
            }

            return ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              itemCount: results.length + 1,
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemBuilder: (context, index) => index == 0 ? header : _AssetCard(item: results[index - 1]),
            );
          },
        ),
      ),
    );
  }
}

const quotaUnavailableText = 'Veri şu an alınamıyor (veri tabanı kotası doldu). Skor gösterilmiyor.';

class _DashboardHeader extends StatelessWidget {
  final DecisionDashboard dashboard;

  const _DashboardHeader({required this.dashboard});

  @override
  Widget build(BuildContext context) {
    final t = dashboard.generatedAt.toLocal();
    final hh = t.hour.toString().padLeft(2, '0');
    final mm = t.minute.toString().padLeft(2, '0');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Güncellendi: $hh:$mm', style: Theme.of(context).textTheme.bodySmall),
        if (dashboard.degraded)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              'Yerel geliştirme modu: bazı veriler eksik ve açıkça işaretlendi.',
              style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold),
            ),
          ),
      ],
    );
  }
}

class _AssetCard extends StatelessWidget {
  final DashboardItem item;

  const _AssetCard({required this.item});

  @override
  Widget build(BuildContext context) {
    if (!item.hasDecision) {
      final text = item.status == 'UNAVAILABLE'
          ? quotaUnavailableText
          : 'Veri alınamadı: ${item.reason ?? 'bilinmeyen hata'}';
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(item.asset, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(text, style: const TextStyle(color: Colors.orange)),
            ],
          ),
        ),
      );
    }

    final label = decisionLabel(item.decision!);
    final color = decisionColor(item.decision!);

    return Card(
      child: InkWell(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (context) => AssetDetailScreen(symbol: item.asset)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(item.asset, style: Theme.of(context).textTheme.titleLarge),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      label,
                      style: TextStyle(color: color, fontWeight: FontWeight.bold),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              // HATA 5C-UI2 (31.08.2026): "Confidence" → "Sinyal Mutabakatı"
              // (final kararla yönsel uyum) + ayrı "Veri Kapsamı" (kaç kanal
              // mevcuttu) -- ikisi ASLA tek sayıya birleştirilmez, karışıklığı
              // önlemek için birlikte gösterilir (bkz. only-one-channel case).
              Text('Sinyal Mutabakatı: ${formatDecisionConfidencePercent(item.confidence!)}'),
              Text('Veri Kapsamı: ${formatCoveragePercent(item.channelCompleteness)}'),
              const SizedBox(height: 4),
              Text('Technical: ${_fmtScore(item.technicalScore)}'),
              Text('News: ${_fmtScore(item.newsScore)}'),
              Text('Macro: ${_fmtScore(item.macroScore)}'),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => _showExplanationDialog(context, item.asset),
                  child: Text('Neden $label?'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _fmtScore(double? score) {
    if (score == null) return 'Veri yok';
    final sign = score >= 0 ? '+' : '';
    return '$sign${score.toStringAsFixed(0)}';
  }
}

void _showExplanationDialog(BuildContext context, String symbol) {
  showDialog(
    context: context,
    builder: (context) {
      return AlertDialog(
        title: Text('$symbol — Karar Gerekçesi'),
        content: SizedBox(
          width: double.maxFinite,
          child: FutureBuilder<Explanation>(
            future: DecisionApi().fetchExplanation(symbol),
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return Text('Hata: ${snapshot.error}');
              }
              return ExplanationContent(explanation: snapshot.data!);
            },
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Kapat'),
          ),
        ],
      );
    },
  );
}

