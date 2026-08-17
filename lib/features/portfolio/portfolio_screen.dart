import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../models/portfolio_position.dart';
import '../../services/api/portfolio_api.dart';

const List<String> _availableAssets = [
  'THYAO',
  'ASELS',
  'GARAN',
  'AKBNK',
  'EREGL',
  'TUPRS',
];

class PortfolioScreen extends StatefulWidget {
  const PortfolioScreen({super.key});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  final _api = PortfolioApi();
  late Future<(List<PortfolioPosition>, PortfolioSummary)> _future;

  @override
  void initState() {
    super.initState();
    _future = _api.fetchPositions();
  }

  void _reload() {
    setState(() {
      _future = _api.fetchPositions();
    });
  }

  Future<void> _showAddDialog() async {
    String asset = _availableAssets.first;
    final priceController = TextEditingController();
    final quantityController = TextEditingController();

    final added = await showDialog<bool>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Pozisyon Ekle'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: asset,
                items: _availableAssets
                    .map((a) => DropdownMenuItem(value: a, child: Text(a)))
                    .toList(),
                onChanged: (v) => asset = v ?? asset,
                decoration: const InputDecoration(labelText: 'Varlık'),
              ),
              TextField(
                controller: priceController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Alış Fiyatı (TL)'),
              ),
              TextField(
                controller: quantityController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Adet'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('İptal'),
            ),
            FilledButton(
              onPressed: () async {
                final price = double.tryParse(priceController.text);
                final quantity = double.tryParse(quantityController.text);
                if (price == null || quantity == null) return;
                await _api.createPosition(
                  asset: asset,
                  buyPrice: price,
                  quantity: quantity,
                  buyDate: DateTime.now(),
                );
                if (context.mounted) Navigator.pop(context, true);
              },
              child: const Text('Ekle'),
            ),
          ],
        );
      },
    );

    if (added == true) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Portföy'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Çıkış Yap',
            onPressed: () => FirebaseAuth.instance.signOut(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddDialog,
        child: const Icon(Icons.add),
      ),
      body: FutureBuilder<(List<PortfolioPosition>, PortfolioSummary)>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Center(child: Text('Hata: ${snapshot.error}'));
          }
          final (positions, summary) = snapshot.data!;

          if (positions.isEmpty) {
            return const Center(child: Text('Henüz pozisyon eklenmedi.'));
          }

          return Column(
            children: [
              _SummaryCard(summary: summary),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: positions.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final p = positions[index];
                    return _PositionTile(
                      position: p,
                      onDelete: () async {
                        await _api.deletePosition(p.asset);
                        _reload();
                      },
                    );
                  },
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  final PortfolioSummary summary;

  const _SummaryCard({required this.summary});

  @override
  Widget build(BuildContext context) {
    final color = summary.totalProfitLoss >= 0 ? Colors.green : Colors.red;
    return Card(
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Toplam Yatırım: ${summary.totalInvested.toStringAsFixed(0)} TL'),
                Text('Güncel Değer: ${summary.totalCurrentValue.toStringAsFixed(0)} TL'),
              ],
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '${summary.totalProfitLoss >= 0 ? '+' : ''}${summary.totalProfitLoss.toStringAsFixed(0)} TL',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold),
                ),
                Text(
                  '%${summary.totalReturnPercent.toStringAsFixed(1)}',
                  style: TextStyle(color: color),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _PositionTile extends StatelessWidget {
  final PortfolioPosition position;
  final VoidCallback onDelete;

  const _PositionTile({required this.position, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    final pnl = position.profitLoss;
    final color = (pnl ?? 0) >= 0 ? Colors.green : Colors.red;

    return Card(
      child: ListTile(
        title: Text(
          '${position.asset}  •  ${position.quantity.toStringAsFixed(0)} adet'
          '${position.lotCount > 1 ? '  (${position.lotCount} alım)' : ''}',
        ),
        subtitle: position.error != null
            ? Text('Veri alınamadı: ${position.error}')
            : Text(
                'Ort. Alış: ${position.buyPrice.toStringAsFixed(2)} TL   Güncel: ${position.currentPrice?.toStringAsFixed(2) ?? '-'} TL',
              ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (pnl != null)
              Text(
                '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(0)} TL',
                style: TextStyle(color: color, fontWeight: FontWeight.bold),
              ),
            IconButton(
              icon: const Icon(Icons.delete_outline),
              onPressed: onDelete,
            ),
          ],
        ),
      ),
    );
  }
}
