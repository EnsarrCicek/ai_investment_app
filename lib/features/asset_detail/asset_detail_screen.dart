import 'package:flutter/material.dart';

import '../../models/backtest_result.dart';
import '../../models/decision.dart';
import '../../models/news_item.dart';
import '../../models/technical_analysis.dart';
import '../../services/api/analysis_api.dart';
import '../../services/api/backtest_api.dart';
import '../../services/api/decision_api.dart';
import '../../services/api/news_api.dart';
import '../../utils/decision_style.dart';

const Map<String, String> _technicalLabels = {
  'rsi': 'RSI',
  'macd': 'MACD',
  'trend': 'EMA Trend (20/50)',
  'bollinger': 'Bollinger Bantları',
  'momentum': 'Momentum',
  'roc': 'ROC (Değişim Oranı)',
};

class AssetDetailScreen extends StatelessWidget {
  final String symbol;

  const AssetDetailScreen({super.key, required this.symbol});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: Text(symbol),
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Teknik'),
              Tab(text: 'Haberler'),
              Tab(text: 'Geçmiş'),
              Tab(text: 'Performans'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _TechnicalTab(symbol: symbol),
            _NewsTab(symbol: symbol),
            _HistoryTab(symbol: symbol),
            _PerformanceTab(symbol: symbol),
          ],
        ),
      ),
    );
  }
}

class _TechnicalTab extends StatefulWidget {
  final String symbol;
  const _TechnicalTab({required this.symbol});

  @override
  State<_TechnicalTab> createState() => _TechnicalTabState();
}

class _TechnicalTabState extends State<_TechnicalTab> {
  late Future<TechnicalAnalysisDetail> _future;

  @override
  void initState() {
    super.initState();
    _future = AnalysisApi().fetchTechnical(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<TechnicalAnalysisDetail>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final data = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Teknik Skor: ${data.technicalScore.toStringAsFixed(1)}',
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                        ),
                        Text('Güven: %${data.confidence.toStringAsFixed(0)}'),
                      ],
                    ),
                    Text(data.trend, style: const TextStyle(fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Gösterge Katkıları', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...data.components.entries.map(
              (e) => Card(
                child: ListTile(
                  title: Text(_technicalLabels[e.key] ?? e.key),
                  trailing: Text(
                    '${e.value >= 0 ? '+' : ''}${e.value.toStringAsFixed(1)}',
                    style: TextStyle(
                      color: e.value >= 0 ? Colors.green : Colors.red,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Ham Gösterge Değerleri', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: data.indicators.entries
                      .map((e) => Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Text('${e.key}: ${e.value}'),
                          ))
                      .toList(),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _NewsTab extends StatefulWidget {
  final String symbol;
  const _NewsTab({required this.symbol});

  @override
  State<_NewsTab> createState() => _NewsTabState();
}

class _NewsTabState extends State<_NewsTab> {
  late Future<List<NewsItem>> _future;

  @override
  void initState() {
    super.initState();
    _future = NewsApi().fetchNews(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<NewsItem>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final items = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            const Text(
              'Bu haberler ham (işlenmemiş) listelenir; AI duygu/etki analizi '
              '(EventIntelligenceEngine) henüz uygulanmadı.',
              style: TextStyle(color: Colors.orange, fontStyle: FontStyle.italic),
            ),
            const SizedBox(height: 12),
            if (items.isEmpty) const Text('Haber bulunamadı.'),
            ...items.map(
              (item) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: InkWell(
                  onTap: () => _openUrl(context, item.url),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(item.title, style: const TextStyle(fontWeight: FontWeight.bold)),
                        const SizedBox(height: 4),
                        Text(item.summary, maxLines: 3, overflow: TextOverflow.ellipsis),
                        const SizedBox(height: 8),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(item.publisher, style: const TextStyle(color: Colors.grey)),
                            Text('Güvenilirlik: %${(item.sourceReliability * 100).toStringAsFixed(0)}'),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  void _openUrl(BuildContext context, String url) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(url)));
  }
}

class _HistoryTab extends StatefulWidget {
  final String symbol;
  const _HistoryTab({required this.symbol});

  @override
  State<_HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends State<_HistoryTab> {
  late Future<List<Decision>> _future;

  @override
  void initState() {
    super.initState();
    _future = DecisionApi().fetchHistory(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Decision>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final decisions = snapshot.data!;
        if (decisions.isEmpty) {
          return const Center(child: Text('Henüz bir karar kaydı yok.'));
        }
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: decisions.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) {
            final d = decisions[index];
            final label = decisionLabel(d.decision);
            final color = decisionColor(d.decision);
            return Card(
              child: ListTile(
                title: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold)),
                subtitle: Text('Skor: ${d.finalScore.toStringAsFixed(1)}   Güven: %${d.confidence.toStringAsFixed(0)}'),
                trailing: Text(_fmtDate(d.createdAt)),
              ),
            );
          },
        );
      },
    );
  }

  String _fmtDate(DateTime? date) {
    if (date == null) return '-';
    final local = date.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month $hour:$minute';
  }
}

class _PerformanceTab extends StatefulWidget {
  final String symbol;
  const _PerformanceTab({required this.symbol});

  @override
  State<_PerformanceTab> createState() => _PerformanceTabState();
}

class _PerformanceTabState extends State<_PerformanceTab> {
  late Future<BacktestResult> _future;

  @override
  void initState() {
    super.initState();
    _future = BacktestApi().fetchBacktest(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<BacktestResult>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final r = snapshot.data!;
        final color = r.totalReturnPct >= 0 ? Colors.green : Colors.red;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${r.fromDate} — ${r.toDate}', style: const TextStyle(color: Colors.grey)),
                    const SizedBox(height: 8),
                    Text(
                      'Strateji Getirisi: ${r.totalReturnPct >= 0 ? '+' : ''}${r.totalReturnPct.toStringAsFixed(1)}%',
                      style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                    Text(
                      'Al-Tut Getirisi: ${r.buyAndHoldReturnPct >= 0 ? '+' : ''}${r.buyAndHoldReturnPct.toStringAsFixed(1)}%',
                    ),
                    Text('Maksimum Düşüş: ${r.maxDrawdownPct.toStringAsFixed(1)}%'),
                    Text('İşlem Sayısı: ${r.tradeCount}   Kazanma Oranı: %${r.winRatePct.toStringAsFixed(0)}'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('İşlemler', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            if (r.trades.isEmpty) const Text('Bu dönemde işlem yapılmadı.'),
            ...r.trades.reversed.map(
              (t) => Card(
                child: ListTile(
                  title: Text('${t.entryDate} → ${t.exitDate}'),
                  subtitle: Text('${t.entryPrice.toStringAsFixed(2)} → ${t.exitPrice.toStringAsFixed(2)} TL'),
                  trailing: Text(
                    '${t.returnPct >= 0 ? '+' : ''}${t.returnPct.toStringAsFixed(1)}%',
                    style: TextStyle(
                      color: t.returnPct >= 0 ? Colors.green : Colors.red,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
