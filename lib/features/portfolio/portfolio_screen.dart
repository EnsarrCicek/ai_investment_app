import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';

import '../../models/portfolio_position.dart';
import '../../services/api/asset_api.dart';
import '../../services/api/portfolio_api.dart';
import '../../services/position_limit_store.dart';
import '../../utils/currency_label.dart';
import 'portfolio_history_screen.dart';
import 'position_limits_sheet.dart';

class PortfolioScreen extends StatefulWidget {
  const PortfolioScreen({super.key});

  @override
  State<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends State<PortfolioScreen> {
  final _api = PortfolioApi();
  final _limitStore = PositionLimitStore();
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
                  // Elle eklenen pozisyonda birim kaydedilmez (TRY varsayılmaz); düzenlemede kayıtlı birim korunur.
                  labelText: isEdit ? _labelWithUnit('Ort. Alış Fiyatı', existing.buyPriceUnit) : 'Alış Fiyatı',
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
                    currency: existing.currency,
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

  Future<void> _showLimitsSheet(PortfolioPosition position) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => PositionLimitsSheet(
        position: position,
        uid: FirebaseAuth.instance.currentUser?.uid,
        store: _limitStore,
        check: _api.checkLimits,
      ),
    );
  }

  Future<void> _showClosePositionDialog(PortfolioPosition position) async {
    final priceController = TextEditingController(text: position.currentPrice?.toStringAsFixed(2));
    bool saving = false;

    final closed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (dialogContext, setDialogState) {
            return AlertDialog(
              title: Text('${position.asset} — Sattım'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${position.quantity.toStringAsFixed(0)} adet, ort. alış '
                      '${withUnit(position.buyPrice.toStringAsFixed(2), position.buyPriceUnit)}'),
                  const SizedBox(height: 12),
                  TextField(
                    controller: priceController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(labelText: _labelWithUnit('Satış Fiyatı', position.buyPriceUnit)),
                    autofocus: true,
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: saving ? null : () => Navigator.pop(dialogContext, false),
                  child: const Text('İptal'),
                ),
                FilledButton(
                  onPressed: saving
                      ? null
                      : () async {
                          final sellPrice = double.tryParse(priceController.text);
                          if (sellPrice == null) return;
                          setDialogState(() => saving = true);
                          try {
                            await _api.closePosition(asset: position.asset, sellPrice: sellPrice);
                            if (dialogContext.mounted) Navigator.pop(dialogContext, true);
                          } catch (e) {
                            setDialogState(() => saving = false);
                            if (dialogContext.mounted) {
                              ScaffoldMessenger.of(dialogContext).showSnackBar(
                                SnackBar(content: Text('Kapatılamadı: $e')),
                              );
                            }
                          }
                        },
                  child: saving
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Sattım'),
                ),
              ],
            );
          },
        );
      },
    );

    if (closed == true) {
      _reload();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${position.asset} kapatıldı — Geçmiş\'te görebilirsiniz.')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: GradientAppBar(
        title: const Text('Portföy'),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'Geçmiş',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => const PortfolioHistoryScreen()),
            ),
          ),
        ],
      ),
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
              PortfolioSummaryCard(summary: summary, positions: positions),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: positions.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final p = positions[index];
                    return PortfolioPositionTile(
                      position: p,
                      onEdit: () => _showPositionDialog(existing: p),
                      onClose: () => _showClosePositionDialog(p),
                      onLimits: () => _showLimitsSheet(p),
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

/// Özet: toplamın birimi yalnız toplamı oluşturan tüm pozisyonlarda bilinen ve aynı ise gösterilir
/// (bkz. `summaryUnits`); karışık/bilinmeyen birimde yalnız sayı.
class PortfolioSummaryCard extends StatelessWidget {
  final PortfolioSummary summary;
  final List<PortfolioPosition> positions;

  const PortfolioSummaryCard({super.key, required this.summary, required this.positions});

  @override
  Widget build(BuildContext context) {
    final color = summary.totalProfitLoss >= 0 ? Colors.green : Colors.red;
    final units = summaryUnits(positions);
    final pnlVerified = summaryPnlVerified(positions);
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
                Text('Toplam Yatırım: ${withUnit(summary.totalInvested.toStringAsFixed(0), units.invested)}'),
                Text('Güncel Değer: ${withUnit(summary.totalCurrentValue.toStringAsFixed(0), units.current)}'),
              ],
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (pnlVerified) ...[
                  Text(
                    '${summary.totalProfitLoss >= 0 ? '+' : ''}${withUnit(summary.totalProfitLoss.toStringAsFixed(0), units.pnl)}',
                    style: TextStyle(color: color, fontWeight: FontWeight.bold),
                  ),
                  Text(
                    '%${summary.totalReturnPercent.toStringAsFixed(1)}',
                    style: TextStyle(color: color),
                  ),
                ] else
                  const Text(pnlUnverifiedTotalText, style: TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class PortfolioPositionTile extends StatelessWidget {
  final PortfolioPosition position;
  final VoidCallback onEdit;
  final VoidCallback onClose;
  final VoidCallback onLimits;

  const PortfolioPositionTile(
      {super.key, required this.position, required this.onEdit, required this.onClose, required this.onLimits});

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
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Ort. Alış: ${withUnit(position.buyPrice.toStringAsFixed(2), position.buyPriceUnit)}   '
                    'Güncel: ${position.currentPrice == null ? '-' : withUnit(position.currentPrice!.toStringAsFixed(2), position.currentPriceUnit)}',
                  ),
                  if (pnl != null && !position.pnlVerified) ...[
                    const Text(pnlUnverifiedText),
                    Text(pnlUnverifiedNote, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ],
              ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (pnl != null && position.pnlVerified)
              Text(
                '${pnl >= 0 ? '+' : ''}${withUnit(pnl.toStringAsFixed(0), position.pnlUnit)}',
                style: TextStyle(color: color, fontWeight: FontWeight.bold),
              ),
            IconButton(
              icon: const Icon(Icons.rule),
              tooltip: 'Kâr/zarar sınırları',
              onPressed: onLimits,
            ),
            IconButton(
              icon: const Icon(Icons.edit_outlined),
              onPressed: onEdit,
            ),
            IconButton(
              icon: const Icon(Icons.sell_outlined),
              tooltip: 'Sattım',
              onPressed: onClose,
            ),
          ],
        ),
      ),
    );
  }
}

String _labelWithUnit(String label, String? unit) => unit == null ? label : '$label ($unit)';

const pnlUnverifiedText = 'Kâr/Zarar: Doğrulanmadı';
const pnlUnverifiedTotalText = 'Toplam Kâr/Zarar: Doğrulanmadı';
const pnlUnverifiedNote = 'Fiyat temeli ve kurumsal işlem etkileri doğrulanmadı.';
