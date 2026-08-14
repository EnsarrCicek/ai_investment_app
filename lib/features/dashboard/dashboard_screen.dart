import 'package:flutter/material.dart';

import '../../models/decision.dart';
import '../../services/api/decision_api.dart';

// AŞAMA 14: Ana doküman bölüm 85'teki "Ana Ekran Taslağı" hedef görünümüne göre.
const List<String> _testAssets = [
  'THYAO',
  'ASELS',
  'GARAN',
  'AKBNK',
  'EREGL',
  'TUPRS',
];

const Map<String, String> _decisionLabels = {
  'BUY': 'AL',
  'WEAK_BUY': 'ZAYIF AL',
  'HOLD': 'TUT',
  'WEAK_SELL': 'ZAYIF SAT',
  'SELL': 'SAT',
};

Color _decisionColor(String decision) {
  switch (decision) {
    case 'BUY':
    case 'WEAK_BUY':
      return Colors.green;
    case 'SELL':
    case 'WEAK_SELL':
      return Colors.red;
    default:
      return Colors.grey;
  }
}

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _api = DecisionApi();
  late Future<List<_AssetResult>> _future;

  @override
  void initState() {
    super.initState();
    _future = _loadAll();
  }

  Future<List<_AssetResult>> _loadAll() async {
    return Future.wait(
      _testAssets.map((symbol) async {
        try {
          final decision = await _api.fetchDecision(symbol);
          return _AssetResult(symbol: symbol, decision: decision);
        } catch (e) {
          return _AssetResult(symbol: symbol, error: e.toString());
        }
      }),
    );
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
      appBar: AppBar(title: const Text('Piyasa Analizi')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<List<_AssetResult>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            final results = snapshot.data ?? [];
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
    final label = _decisionLabels[decision.decision] ?? decision.decision;
    final color = _decisionColor(decision.decision);

    return Card(
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
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('AIExplanationEngine henüz uygulanmadı (bkz. AŞAMA 24).'),
                    ),
                  );
                },
                child: Text('Neden $label?'),
              ),
            ),
          ],
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
