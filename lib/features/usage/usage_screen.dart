import 'package:flutter/material.dart';

import '../../models/usage_summary.dart';
import '../../services/api/usage_api.dart';

String _fmtUsd(double v) => '\$${v.toStringAsFixed(4)}';

class UsageScreen extends StatefulWidget {
  const UsageScreen({super.key});

  @override
  State<UsageScreen> createState() => _UsageScreenState();
}

class _UsageScreenState extends State<UsageScreen> {
  late Future<UsageSummary> _future;

  @override
  void initState() {
    super.initState();
    _future = UsageApi().fetchUsage();
  }

  Future<void> _refresh() async {
    setState(() {
      _future = UsageApi().fetchUsage();
    });
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('API Kullanımı')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<UsageSummary>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [Center(child: Text('Hata: ${snapshot.error}'))],
              );
            }
            final data = snapshot.data!;
            final ratio = data.budgetUsd > 0 ? (data.spentTotalUsd / data.budgetUsd).clamp(0.0, 1.0) : 0.0;
            final barColor = ratio < 0.7 ? Colors.green : (ratio < 0.9 ? Colors.orange : Colors.red);

            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Kalan Bakiye', style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 4),
                        Text(
                          _fmtUsd(data.remainingUsd),
                          style: TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: barColor),
                        ),
                        const SizedBox(height: 12),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: LinearProgressIndicator(
                            value: ratio,
                            minHeight: 10,
                            backgroundColor: Colors.grey.shade300,
                            valueColor: AlwaysStoppedAnimation<Color>(barColor),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          '${_fmtUsd(data.spentTotalUsd)} / ${_fmtUsd(data.budgetUsd)} harcandı '
                          '(%${(ratio * 100).toStringAsFixed(1)})',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: _StatCard(
                        title: 'Bugün Harcanan',
                        value: _fmtUsd(data.spentTodayUsd),
                        subtitle: '${data.callsToday} çağrı · ${data.tokensToday} token',
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _StatCard(
                        title: 'Toplam',
                        value: '${data.callsTotal} çağrı',
                        subtitle: '${data.tokensTotal} token',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Son 7 Gün', style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        if (data.dailyBreakdown.isEmpty)
                          const Text('Henüz haber analizi yapılmadı.')
                        else
                          ..._dailyRows(data.dailyBreakdown),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'Fiyatlandırma OpenAI GPT-5.6 Luna tarifesinden hesaplanır '
                  '(gerçek billing API\'sinden anlık çekilmez).',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  List<Widget> _dailyRows(List<DailyUsage> days) {
    final maxSpent = days.map((d) => d.spentUsd).fold<double>(0, (a, b) => a > b ? a : b);
    return days.map((d) {
      final widthRatio = maxSpent > 0 ? (d.spentUsd / maxSpent).clamp(0.05, 1.0) : 0.0;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            SizedBox(width: 90, child: Text(d.date, style: const TextStyle(fontSize: 12))),
            Expanded(
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: widthRatio,
                child: Container(
                  height: 10,
                  decoration: BoxDecoration(
                    color: Colors.blue.shade300,
                    borderRadius: BorderRadius.circular(4),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(_fmtUsd(d.spentUsd), style: const TextStyle(fontSize: 12)),
          ],
        ),
      );
    }).toList();
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final String subtitle;

  const _StatCard({required this.title, required this.value, required this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 2),
            Text(subtitle, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}
