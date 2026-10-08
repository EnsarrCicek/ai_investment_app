import 'package:flutter/material.dart';

import '../../models/portfolio_position.dart';
import '../../models/portfolio_transaction.dart';
import '../../models/position_limits.dart';
import '../../services/api/portfolio_api.dart';

typedef SellPositionFn = Future<PortfolioTransaction> Function({
  required String asset,
  required double quantity,
  required double sellPrice,
  required String positionVersion,
  String? currency,
  DateTime? sellDate,
});

/// Satış dialogunun sonucu. Her iki durumda da çağıran portföyü backend'den YENİDEN yükler
/// (kalan pozisyon istemcide hesaplanmaz).
sealed class SellDialogResult {
  const SellDialogResult();
}

class SellCompleted extends SellDialogResult {
  final PortfolioTransaction transaction;

  const SellCompleted(this.transaction);
}

/// Sunucu 409 POSITION_CHANGED döndürdü: dialogdaki adet/sürüm bayat; otomatik yeniden deneme YOK.
class SellPositionChanged extends SellDialogResult {
  final String message;

  const SellPositionChanged(this.message);
}

const sellVersionUnavailableText = 'Satış şu an doğrulanamıyor: pozisyon sürümü alınamadı. Portföyü yenileyip tekrar deneyin.';
const sellExceedsText = 'Satılacak adet mevcut adetten fazla olamaz.';

String _fmtQty(double q) => q == q.roundToDouble() ? q.toStringAsFixed(0) : q.toString();

/// Kısmi veya tam satış. Adet `0 < adet <= mevcut` olmalı; tamamı girilirse tam satış olur (aynı `/sell` yolu).
/// Gönderilen `position_version`, dialog açıldığı anda görülen pozisyonun sürümüdür.
class PositionSellDialog extends StatefulWidget {
  final PortfolioPosition position;
  final SellPositionFn sell;

  const PositionSellDialog({super.key, required this.position, required this.sell});

  @override
  State<PositionSellDialog> createState() => _PositionSellDialogState();
}

class _PositionSellDialogState extends State<PositionSellDialog> {
  late final TextEditingController _qty;
  late final TextEditingController _price;
  late final String? _version = widget.position.positionVersion;
  bool _saving = false;
  String? _error;

  PortfolioPosition get _p => widget.position;

  @override
  void initState() {
    super.initState();
    _qty = TextEditingController();
    _price = TextEditingController(text: _p.currentPrice?.toStringAsFixed(2) ?? '');
  }

  @override
  void dispose() {
    _qty.dispose();
    _price.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final version = _version;
    if (version == null) return; // sürüm bilinmiyorsa istek gönderilmez
    final q = parseManualDecimal(_qty.text);
    final p = parseManualDecimal(_price.text);
    String? err = q.error != null
        ? 'Satılacak adet: ${q.error}'
        : p.error != null
            ? 'Satış fiyatı: ${p.error}'
            : (q.value! > _p.quantity ? sellExceedsText : null);
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final tx = await widget.sell(
        asset: _p.asset,
        quantity: q.value!,
        sellPrice: p.value!,
        positionVersion: version,
        currency: _p.currency,
      );
      if (mounted) Navigator.pop(context, SellCompleted(tx));
    } on SellPositionException catch (e) {
      if (!mounted) return;
      if (e.positionChanged) {
        Navigator.pop(context, SellPositionChanged(e.message)); // bayat durum: kapat, çağıran yeniler
        return;
      }
      setState(() {
        _saving = false;
        _error = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = 'Satış kaydedilemedi: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final unit = _p.buyPriceUnit;
    final versionMissing = _version == null;
    return AlertDialog(
      title: Text('${_p.asset} — Satış'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Mevcut adet: ${_fmtQty(_p.quantity)}', key: const Key('sell_available')),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('sell_quantity'),
                    controller: _qty,
                    enabled: !versionMissing,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Satılacak Adet'),
                  ),
                ),
                TextButton(
                  key: const Key('sell_all'),
                  onPressed: versionMissing ? null : () => setState(() => _qty.text = _fmtQty(_p.quantity)),
                  child: const Text('Tümü'),
                ),
              ],
            ),
            TextField(
              key: const Key('sell_price'),
              controller: _price,
              enabled: !versionMissing,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: unit == null ? 'Satış Fiyatı' : 'Satış Fiyatı ($unit)'),
            ),
            if (versionMissing)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(sellVersionUnavailableText,
                    key: const Key('sell_version_missing'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error!, key: const Key('sell_error'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _saving ? null : () => Navigator.pop(context), child: const Text('İptal')),
        FilledButton(
          key: const Key('sell_submit'),
          onPressed: _saving || versionMissing ? null : _submit,
          child: _saving
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Sat'),
        ),
      ],
    );
  }
}
