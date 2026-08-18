import 'package:flutter/material.dart';

import '../../models/portfolio_position.dart';
import '../../services/api/asset_api.dart';
import '../../services/api/portfolio_api.dart';

class PortfolioScreen extends StatefulWidget {
  const PortfolioScreen({super.key});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  final _api = PortfolioApi();
  late Future<(List<PortfolioPosition>, PortfolioSummary)> _future;
  List<String> _availableSymbols = [];

  @override
  void initState() {
    super.initState();
    _future = _api.fetchPositions();
    AssetApi().fetchAssets().then((assets) {
      if (mounted) setState(() => _availableSymbols = assets.map((a) => a.symbol).toList());
    });
  }

  void _reload() {
    setState(() {
      _future = _api.fetchPositions();
    });
  }

  Future<void> _showPositionDialog({PortfolioPosition? existing}) async {
    final isEdit = existing != null;
    String asset = existing?.asset ?? '';
    final priceController = TextEditingController(text: existing?.buyPrice.toString());
    final quantityController = TextEditingController(text: existing?.quantity.toStringAsFixed(0));

    final saved = await showDialog<bool>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text(isEdit ? 'Pozisyonu Düzenle' : 'Pozisyon Ekle'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (isEdit)
                Align(
                  alignment: Alignment.centerLeft,
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text(asset, style: Theme.of(context).textTheme.titleMedium),
                  ),
                )
              else
                Autocomplete<String>(
                  optionsBuilder: (textEditingValue) {
                    if (textEditingValue.text.isEmpty) return const Iterable<String>.empty();
                    final query = textEditingValue.text.toUpperCase();
                    return _availableSymbols.where((s) => s.contains(query));
                  },
                  onSelected: (selected) => asset = selected,
                  fieldViewBuilder: (context, controller, focusNode, onSubmitted) {
                    return TextField(
                      controller: controller,
                      focusNode: focusNode,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(
                        labelText: 'Varlık (BIST100 sembolü yazın)',
                        hintText: 'ör. THYAO',
                      ),
                      onChanged: (v) => asset = v.toUpperCase(),
                    );
                  },
                ),
              TextField(
                controller: priceController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                  labelText: isEdit ? 'Ort. Alış Fiyatı (TL)' : 'Alış Fiyatı (TL)',
                ),
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
                if (price == null || quantity == null || asset.isEmpty) return;
                if (isEdit) {
                  await _api.updatePosition(
                    asset: asset,
                    buyPrice: price,
                    quantity: quantity,
                    buyDate: DateTime.now(),
                  );
                } else {
                  await _api.createPosition(
                    asset: asset,
                    buyPrice: price,
                    quantity: quantity,
                    buyDate: DateTime.now(),
                  );
                }
                if (context.mounted) Navigator.pop(context, true);
              },
              child: Text(isEdit ? 'Kaydet' : 'Ekle'),
            ),
          ],
        );
      },
    );

    if (saved == true) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Portföy')),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showPositionDialog(),
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
                      onEdit: () => _showPositionDialog(existing: p),
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
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  const _PositionTile({required this.position, required this.onEdit, required this.onDelete});

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
              icon: const Icon(Icons.edit_outlined),
              onPressed: onEdit,
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
