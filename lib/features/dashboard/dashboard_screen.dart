import 'package:flutter/material.dart';

import '../../models/decision.dart';
import '../../models/explanation.dart';
import '../../services/api/asset_api.dart';
import '../../services/api/decision_api.dart';
import '../../utils/decision_style.dart';
import '../asset_detail/asset_detail_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _api = DecisionApi();
  late Future<List<_AssetResult>> _future;
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

  // Gerçek bulut backend'ine (Cloud Run) karşı 100 sembolü TAMAMEN eşzamanlı
  // istemek bağlantı katmanında kopmalara yol açıyordu (SocketException:
  // connection abort — 100 eşzamanlı yeni TLS bağlantısı açılmaya çalışılınca).
  // Bu yüzden istekler küçük gruplar hâlinde, art arda gönderiliyor.
  static const int _batchSize = 10;

  Future<List<_AssetResult>> _loadAll() async {
    // BIST100'ün tamamı — backend'deki assets koleksiyonundan dinamik çekilir,
    // sabit bir test listesi değil (bkz. KURULUM_GUNLUGU AŞAMA 43).
    final assets = await AssetApi().fetchAssets();
    final symbols = assets.map((a) => a.symbol).toList();

    final results = <_AssetResult>[];
    for (var i = 0; i < symbols.length; i += _batchSize) {
      final batch = symbols.skip(i).take(_batchSize);
      final batchResults = await Future.wait(
        batch.map((symbol) async {
          try {
            final decision = await _api.fetchDecision(symbol);
            return _AssetResult(symbol: symbol, decision: decision);
          } catch (e) {
            return _AssetResult(symbol: symbol, error: e.toString());
          }
        }),
      );
      results.addAll(batchResults);
    }

    // En güçlü AL sinyali üstte, en güçlü SAT sinyali altta — final_score'a göre
    // azalan sıralama. Veri alınamayan (hata) varlıklar sıralanamaz, en altta kalır.
    results.sort((a, b) {
      if (a.decision == null && b.decision == null) return 0;
      if (a.decision == null) return 1;
      if (b.decision == null) return -1;
      return b.decision!.finalScore.compareTo(a.decision!.finalScore);
    });
    return results;
  }

  Future<void> _refresh() async {
    setState(() {
      _future = _loadAll();
    });
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
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
        child: FutureBuilder<List<_AssetResult>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            final allResults = snapshot.data ?? [];
            final results = _query.isEmpty
                ? allResults
                : allResults.where((r) => r.symbol.contains(_query)).toList();

            if (results.isEmpty) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: Center(child: Text('"$_query" için sonuç bulunamadı.')),
                  ),
                ],
              );
            }

            return ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              itemCount: results.length,
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemBuilder: (context, index) => _AssetCard(result: results[index]),
            );
          },
        ),
      ),
    );
  }
}

class _AssetResult {
  final String symbol;
  final Decision? decision;
  final String? error;

  _AssetResult({required this.symbol, this.decision, this.error});
}

class _AssetCard extends StatelessWidget {
  final _AssetResult result;

  const _AssetCard({required this.result});

  @override
  Widget build(BuildContext context) {
    if (result.error != null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(result.symbol, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text('Veri alınamadı: ${result.error}', style: const TextStyle(color: Colors.orange)),
            ],
          ),
        ),
      );
    }

    final decision = result.decision!;
    final label = decisionLabel(decision.decision);
    final color = decisionColor(decision.decision);

    return Card(
      child: InkWell(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (context) => AssetDetailScreen(symbol: result.symbol)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(result.symbol, style: Theme.of(context).textTheme.titleLarge),
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
              Text('Confidence: %${decision.confidence.toStringAsFixed(0)}'),
              const SizedBox(height: 4),
              Text('Technical: ${_fmtScore(decision.technicalScore)}'),
              Text('News: ${_fmtScore(decision.newsScore)}'),
              Text('Macro: ${_fmtScore(decision.macroScore)}'),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => _showExplanationDialog(context, result.symbol),
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
              return _ExplanationContent(explanation: snapshot.data!);
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

class _ExplanationContent extends StatelessWidget {
  final Explanation explanation;

  const _ExplanationContent({required this.explanation});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(explanation.summary),
          if (explanation.technicalReasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Teknik Analiz:', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final reason in explanation.technicalReasons) Text('•  $reason'),
          ],
          if (explanation.macroReasons.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Makro Etkenler:', style: TextStyle(fontWeight: FontWeight.bold)),
            for (final reason in explanation.macroReasons) Text('•  $reason'),
          ],
          if (explanation.missing.isNotEmpty) ...[
            const SizedBox(height: 12),
            for (final note in explanation.missing)
              Text(note, style: const TextStyle(color: Colors.orange, fontStyle: FontStyle.italic)),
          ],
        ],
      ),
    );
  }
}
