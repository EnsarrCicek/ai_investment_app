import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';

import '../../models/portfolio_transaction.dart';
import '../../services/api/portfolio_api.dart';

class PortfolioHistoryScreen extends StatefulWidget {
  const PortfolioHistoryScreen({super.key});

  @override
  State<PortfolioHistoryScreen> createState() => _PortfolioHistoryScreenState();
}

class _PortfolioHistoryScreenState extends State<PortfolioHistoryScreen> {
  late Future<(PortfolioHistorySummary, double)> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<(PortfolioHistorySummary, double)> _load() async {
    final api = PortfolioApi();
    final history = await api.fetchHistory();
    var unrealized = 0.0;
    try {
      final (_, summary) = await api.fetchPositions();
      unrealized = summary.totalProfitLoss;
    } catch (_) {
      // Açık pozisyon yok/alınamadı — toplam yalnızca gerçekleşen K/Z'yi yansıtır.
    }
    return (history, unrealized);
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: GradientAppBar(title: const Text('Portföy Geçmişi')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<(PortfolioHistorySummary, double)>(
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
            final (history, unrealized) = snapshot.data!;
            final total = history.totalRealizedPnl + unrealized;

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
                        _SummaryRow(label: 'Gerçekleşen K/Z (satılanlar)', value: history.totalRealizedPnl),
                        const SizedBox(height: 4),
                        _SummaryRow(label: 'Açık Pozisyon K/Z (elde tutulanlar)', value: unrealized),
                        const Divider(height: 20),
                        _SummaryRow(label: 'Toplam K/Z (geçmişten bugüne)', value: total, big: true),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                const Text('Satış Geçmişi', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                if (history.transactions.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(child: Text('Henüz kapatılmış (satılmış) bir pozisyon yok.')),
                  )
                else
                  ...history.transactions.map((t) => _TransactionCard(transaction: t)),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _SummaryRow extends StatelessWidget {
  final String label;
  final double value;
  final bool big;

  const _SummaryRow({required this.label, required this.value, this.big = false});

  @override
  Widget build(BuildContext context) {
    final color = value >= 0 ? Colors.green : Colors.red;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: big ? const TextStyle(fontWeight: FontWeight.bold) : null),
        Text(
          '${value >= 0 ? '+' : ''}${value.toStringAsFixed(0)} TL',
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.bold,
            fontSize: big ? 18 : 14,
          ),
        ),
      ],
    );
  }
}

String _fmtDate(DateTime d) {
  final local = d.toLocal();
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  return '$day.$month.${local.year}';
}

class _TransactionCard extends StatelessWidget {
  final PortfolioTransaction transaction;
  const _TransactionCard({required this.transaction});

  @override
  Widget build(BuildContext context) {
    final t = transaction;
    final isProfit = t.realizedPnl >= 0;
    final color = isProfit ? Colors.green : Colors.red;
    final direction = isProfit ? 'yükseldi' : 'düştü';
    final result = isProfit ? 'kâr edildi' : 'zarar edildi';

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withValues(alpha: 0.25)),
        ),
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(isProfit ? Icons.trending_up : Icons.trending_down, color: color, size: 20),
                const SizedBox(width: 6),
                Text(t.asset, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                const Spacer(),
                Text(
                  '${t.realizedPnl >= 0 ? '+' : ''}${t.realizedPnl.toStringAsFixed(0)} TL '
                  '(${t.realizedPnlPercent >= 0 ? '+' : ''}${t.realizedPnlPercent.toStringAsFixed(1)}%)',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${_fmtDate(t.buyDate)}\'de ${t.buyPrice.toStringAsFixed(2)} TL\'den ${t.quantity.toStringAsFixed(0)} adet alındı, '
              '${_fmtDate(t.sellDate)}\'de ${t.sellPrice.toStringAsFixed(2)} TL\'den satıldı. '
              'Fiyat %${t.realizedPnlPercent.abs().toStringAsFixed(1)} $direction, $result.',
              style: const TextStyle(fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}
