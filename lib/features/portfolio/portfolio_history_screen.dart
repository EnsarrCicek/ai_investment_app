import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';

import '../../models/portfolio_position.dart';
import '../../models/portfolio_transaction.dart';
import '../../services/api/portfolio_api.dart';
import '../../utils/currency_label.dart';

class PortfolioHistoryScreen extends StatefulWidget {
  const PortfolioHistoryScreen({super.key});

  @override
  State<PortfolioHistoryScreen> createState() => _PortfolioHistoryScreenState();
}

class _PortfolioHistoryScreenState extends State<PortfolioHistoryScreen> {
  late Future<(PortfolioHistorySummary, double, List<PortfolioPosition>?)> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  /// Açık pozisyonlar alınamazsa liste null döner: açık K/Z bilinmiyor (0 sayılmaz, doğrulanmamış gösterilir).
  Future<(PortfolioHistorySummary, double, List<PortfolioPosition>?)> _load() async {
    final api = PortfolioApi();
    final history = await api.fetchHistory();
    var unrealized = 0.0;
    List<PortfolioPosition>? positions;
    try {
      final (list, summary) = await api.fetchPositions();
      unrealized = summary.totalProfitLoss;
      positions = list;
    } catch (_) {
      positions = null;
    }
    return (history, unrealized, positions);
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
        child: FutureBuilder<(PortfolioHistorySummary, double, List<PortfolioPosition>?)>(
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
            final (history, unrealized, positions) = snapshot.data!;
            final total = history.totalRealizedPnl + unrealized;
            final units = historyUnits(history.transactions, positions ?? const []);
            // Gerçekleşen K/Z kullanıcının kayıtlı alış/satış fiyatlarından; açık K/Z piyasa fiyatına dayanır.
            final openVerified = openPnlVerified(positions);

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
                        _SummaryRow(
                          label: 'Gerçekleşen K/Z (satılanlar)',
                          value: history.totalRealizedPnl,
                          unit: units.realized,
                        ),
                        const SizedBox(height: 4),
                        _SummaryRow(
                          label: 'Açık Pozisyon K/Z (elde tutulanlar)',
                          value: unrealized,
                          unit: units.unrealized,
                          unverified: !openVerified,
                        ),
                        const Divider(height: 20),
                        _SummaryRow(
                          label: 'Toplam K/Z (geçmişten bugüne)',
                          value: total,
                          unit: units.total,
                          big: true,
                          unverified: !openVerified,
                        ),
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
  final String? unit;
  final bool unverified;

  const _SummaryRow({required this.label, required this.value, this.unit, this.big = false, this.unverified = false});

  @override
  Widget build(BuildContext context) {
    final color = value >= 0 ? Colors.green : Colors.red;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: big ? const TextStyle(fontWeight: FontWeight.bold) : null),
        if (unverified)
          Text(
            'Doğrulanmadı',
            style: TextStyle(fontWeight: FontWeight.bold, fontSize: big ? 18 : 14),
          )
        else
          Text(
            '${value >= 0 ? '+' : ''}${withUnit(value.toStringAsFixed(0), unit)}',
            style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: big ? 18 : 14),
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
    final unit = currencyUnit(t.currency);
    String amount(double v) => withUnit(v.toStringAsFixed(2), unit);

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
                  '${t.realizedPnl >= 0 ? '+' : ''}${withUnit(t.realizedPnl.toStringAsFixed(0), unit)} '
                  '(${t.realizedPnlPercent >= 0 ? '+' : ''}${t.realizedPnlPercent.toStringAsFixed(1)}%)',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${_fmtDate(t.buyDate)} tarihinde ${amount(t.buyPrice)} fiyatla ${t.quantity.toStringAsFixed(0)} adet alındı, '
              '${_fmtDate(t.sellDate)} tarihinde ${amount(t.sellPrice)} fiyatla satıldı. '
              'Fiyat %${t.realizedPnlPercent.abs().toStringAsFixed(1)} $direction, $result.',
              style: const TextStyle(fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}

/// Geçmiş özetinin birimleri: gerçekleşen = tüm işlemlerin ortak birimi; açık = portföy özetiyle aynı kural;
/// toplam = iki tarafın (var olanların) ortak birimi. Bilinmeyen/karışıkta null (birim yazılmaz).
({String? realized, String? unrealized, String? total}) historyUnits(
  List<PortfolioTransaction> transactions,
  List<PortfolioPosition> positions,
) {
  final realized = transactions.isEmpty ? null : commonUnit(transactions.map((t) => currencyUnit(t.currency)));
  final hasOpen = positions.any((p) => p.error == null);
  final unrealized = hasOpen ? summaryUnits(positions).pnl : null;
  final String? total;
  if (transactions.isEmpty) {
    total = unrealized;
  } else if (!hasOpen) {
    total = realized;
  } else {
    total = realized != null && realized == unrealized ? realized : null;
  }
  return (realized: realized, unrealized: unrealized, total: total);
}

/// Açık pozisyon K/Z'si doğrulanmış mı: pozisyonlar alınamadıysa (null) hayır; açık pozisyon yoksa (boş liste) değer
/// gerçekten 0'dır; varsa tümü doğrulanmış olmalı (bkz. `summaryPnlVerified`).
bool openPnlVerified(List<PortfolioPosition>? positions) =>
    positions != null && (positions.isEmpty || summaryPnlVerified(positions));
