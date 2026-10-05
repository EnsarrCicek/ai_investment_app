import 'package:flutter/material.dart';

import '../../models/portfolio_position.dart';
import '../../models/position_limits.dart';
import '../../services/position_limit_store.dart';

typedef LimitCheckFn = Future<LimitCheckResult> Function({
  required String asset,
  required String positionVersion,
  double? profitTargetPct,
  double? maxLossPct,
});

const limitsNoticeText =
    'Otomatik takip ve telefon bildirimi bu sürümde aktif değildir. Kontrol yalnızca "Sınırları kontrol et" '
    'butonuna bastığınızda, son tamamlanmış seans kapanışıyla yapılır. AL/SAT tavsiyesi değildir.';
const limitsStorageText = 'Sınırlar yalnızca bu cihazda, bu hesap için saklanır; cihazlar arasında eşitlenmez.';

/// Açık pozisyon için kullanıcı tanımlı kâr/zarar sınırları + elle kontrol.
class PositionLimitsSheet extends StatefulWidget {
  final PortfolioPosition position;
  final String? uid;
  final PositionLimitStore store;
  final LimitCheckFn check;

  const PositionLimitsSheet({
    super.key,
    required this.position,
    required this.uid,
    required this.store,
    required this.check,
  });

  @override
  State<PositionLimitsSheet> createState() => _PositionLimitsSheetState();
}

class _PositionLimitsSheetState extends State<PositionLimitsSheet> {
  final _profit = TextEditingController();
  final _loss = TextEditingController();
  PositionLimits? _saved;
  bool _loading = true;
  bool _checking = false;
  LimitCheckResult? _result;
  DateTime? _resultAt;
  String? _checkError;
  String? _formError;

  String get _asset => widget.position.asset;
  bool get _active => _saved != null && _saved!.isActiveFor(widget.position.positionVersion);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _profit.dispose();
    _loss.dispose();
    super.dispose();
  }

  void _clearResult() {
    _result = null;
    _resultAt = null;
    _checkError = null;
  }

  Future<void> _load() async {
    final uid = widget.uid;
    final saved = uid == null ? null : await widget.store.load(uid, _asset);
    if (!mounted) return;
    setState(() {
      _saved = saved;
      _profit.text = saved?.profitTargetPct?.toString() ?? '';
      _loss.text = saved?.maxLossPct?.toString() ?? '';
      _loading = false;
    });
  }

  Future<void> _save() async {
    final uid = widget.uid;
    if (uid == null) return;
    final e1 = validateLimitInput(_profit.text, max: 1000);
    final e2 = validateLimitInput(_loss.text, max: 100);
    if (e1 != null || e2 != null) {
      setState(() => _formError = e1 != null ? 'Kâr hedefi: $e1' : 'Zarar sınırı: $e2');
      return;
    }
    final limits = PositionLimits(
      profitTargetPct: parseLimitInput(_profit.text),
      maxLossPct: parseLimitInput(_loss.text),
      positionVersion: widget.position.positionVersion,
      savedAt: DateTime.now(),
    );
    if (limits.isEmpty) {
      setState(() => _formError = 'En az bir sınır girin veya "Kaldır"ı kullanın.');
      return;
    }
    await widget.store.save(uid, _asset, limits);
    if (!mounted) return;
    setState(() {
      _saved = limits;
      _formError = null;
      _clearResult();
    });
  }

  Future<void> _remove() async {
    final uid = widget.uid;
    if (uid == null) return;
    await widget.store.remove(uid, _asset);
    if (!mounted) return;
    setState(() {
      _saved = null;
      _profit.clear();
      _loss.clear();
      _formError = null;
      _clearResult();
    });
  }

  Future<void> _runCheck() async {
    final saved = _saved;
    if (saved == null || !_active) return;
    setState(() {
      _checking = true;
      _clearResult(); // eski sonuç yeni kontrolün sonucu gibi gösterilmez
    });
    try {
      final r = await widget.check(
        asset: _asset,
        positionVersion: saved.positionVersion!,
        profitTargetPct: saved.profitTargetPct,
        maxLossPct: saved.maxLossPct,
      );
      if (!mounted) return;
      setState(() {
        _result = r;
        _resultAt = DateTime.now();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _checkError = 'Kontrol yapılamadı: $e');
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$_asset — Kâr/zarar sınırları', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            const Text(limitsNoticeText, key: Key('limits_notice')),
            const SizedBox(height: 4),
            Text(limitsStorageText, style: theme.textTheme.bodySmall),
            const SizedBox(height: 12),
            if (_loading)
              const Center(child: CircularProgressIndicator())
            else if (widget.uid == null)
              const Text('Sınır kaydetmek için oturum açmalısınız.')
            else ..._form(theme),
            const Divider(height: 32),
            const ManualLimitCalcSection(key: Key('manual_section')),
          ],
        ),
      ),
    );
  }

  List<Widget> _form(ThemeData theme) {
    final passive = _saved != null && !_active;
    return [
      if (passive)
        Card(
          key: const Key('limits_passive'),
          color: theme.colorScheme.surfaceContainerHighest,
          child: const Padding(
            padding: EdgeInsets.all(8),
            child: Text('Bu sınırlar pozisyon değişmeden önce kaydedildi veya pozisyon kimliği doğrulanamadı; '
                'pasif durumda. Uygulanması için değerleri kontrol edip yeniden kaydedin.'),
          ),
        ),
      TextField(
        key: const Key('profit_field'),
        controller: _profit,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: const InputDecoration(labelText: 'Kâr hedefi (%) — isteğe bağlı', hintText: 'boş = tanımsız'),
      ),
      TextField(
        key: const Key('loss_field'),
        controller: _loss,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: const InputDecoration(labelText: 'Zarar sınırı (%) — isteğe bağlı', hintText: 'boş = tanımsız'),
      ),
      if (_formError != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_formError!, style: TextStyle(color: theme.colorScheme.error)),
        ),
      const SizedBox(height: 8),
      Row(
        children: [
          FilledButton(key: const Key('limits_save'), onPressed: _save, child: const Text('Kaydet')),
          const SizedBox(width: 8),
          if (_saved != null)
            TextButton(key: const Key('limits_remove'), onPressed: _remove, child: const Text('Kaldır')),
        ],
      ),
      const Divider(height: 24),
      OutlinedButton.icon(
        key: const Key('limits_check'),
        onPressed: _active && !_checking ? _runCheck : null,
        icon: const Icon(Icons.fact_check_outlined),
        label: const Text('Sınırları kontrol et'),
      ),
      if (_saved == null)
        const Padding(padding: EdgeInsets.only(top: 8), child: Text('Sınır tanımlı değil.', key: Key('limits_none'))),
      if (_checking) const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator()),
      if (_checkError != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_checkError!, style: TextStyle(color: theme.colorScheme.error)),
        ),
      if (_result != null) LimitCheckResultView(result: _result!, checkedAt: _resultAt!),
    ];
  }
}

String limitStateLabel(String state) => switch (state) {
      LimitCheckResult.noLimits => 'Sınır tanımlı değil',
      LimitCheckResult.within => 'Sınır içinde',
      LimitCheckResult.exceeded => 'Sınır aşıldı',
      _ => 'Değerlendirilemedi',
    };

String _itemStatus(String s) => switch (s) {
      'SINIR_ICINDE' => 'sınır içinde',
      'SINIR_ASILDI' => 'aşıldı',
      'SINIR_TANIMLI_DEGIL' => 'tanımsız',
      _ => 'değerlendirilemedi',
    };

class LimitCheckResultView extends StatelessWidget {
  final LimitCheckResult result;
  final DateTime checkedAt;

  const LimitCheckResultView({super.key, required this.result, required this.checkedAt});

  String _pct(double? v) => v == null ? '-' : '%${v.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final r = result;
    final t = checkedAt;
    final at = '${t.day.toString().padLeft(2, '0')}.${t.month.toString().padLeft(2, '0')}.${t.year} '
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        key: const Key('limits_result'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Durum: ${limitStateLabel(r.state)}', style: Theme.of(context).textTheme.titleSmall),
          Text('Kontrol zamanı: $at', style: Theme.of(context).textTheme.bodySmall),
          if (r.state == LimitCheckResult.notEvaluated) Text('Neden: ${r.blockMessage ?? r.blockCode ?? '-'}'),
          if (r.expectedSession != null) Text('Beklenen son tamamlanmış seans: ${r.expectedSession}'),
          if (r.priceSession != null)
            // limit-check yanıtı fiyatın para birimini taşımıyor; birim yazılmaz.
            Text('Kullanılan kapanış: ${r.priceSession} • ${r.priceClose?.toStringAsFixed(2)} • '
                'kaynak: ${r.priceSource ?? '-'} (${r.priceBasis ?? '-'})'),
          if (r.priceSession == null && r.lastKnownSession != null)
            Text('Son bilinen fiyat (kullanılmadı): ${r.lastKnownSession} • kaynak: ${r.lastKnownSource ?? '-'}'),
          if (r.profitTarget != null)
            Text('Kâr hedefi ${_pct(r.profitTarget!.limitPct)}: maliyete göre fiyat farkı '
                '${_pct(r.profitTarget!.valuePct)} — ${_itemStatus(r.profitTarget!.status)}'),
          if (r.maxLoss != null)
            Text('Zarar sınırı ${_pct(r.maxLoss!.limitPct)}: maliyete göre kayıp '
                '${_pct(r.maxLoss!.valuePct)} — ${_itemStatus(r.maxLoss!.status)}'),
          if (r.state == LimitCheckResult.within || r.state == LimitCheckResult.exceeded)
            Text('Komisyon, vergi ve temettü dahil değildir; net kazanç değildir.',
                style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

const manualNoticeText = 'Manuel girilen değerlere göre hesap. Canlı fiyat ve aracı kurum doğrulaması yapılmaz; '
    'otomatik takip veya bildirim oluşturmaz.';

/// Türkçe gösterim: binlik nokta, ondalık virgül (yalnız gösterimde yuvarlanır).
String formatTr(double v, {int digits = 2}) {
  final neg = v < 0;
  final parts = v.abs().toStringAsFixed(digits).split('.');
  final intPart = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');
  return '${neg ? '-' : ''}$intPart${parts.length > 1 ? ',${parts[1]}' : ''}';
}

String _signed(double v, {int digits = 2}) => '${v > 0 ? '+' : ''}${formatTr(v, digits: digits)}';

/// "Manuel hesap": kullanıcının kurum ekranından girdiği adet/maliyet/fiyatla aritmetik kontrol.
/// Kalıcı kaydedilmez; gerçek pozisyonu, kayıtlı sınırları veya canlı kontrol sonucunu değiştirmez.
class ManualLimitCalcSection extends StatefulWidget {
  const ManualLimitCalcSection({super.key});

  @override
  State<ManualLimitCalcSection> createState() => _ManualLimitCalcSectionState();
}

class _ManualLimitCalcSectionState extends State<ManualLimitCalcSection> {
  final _qty = TextEditingController();
  final _cost = TextEditingController();
  final _price = TextEditingController();
  final _profit = TextEditingController();
  final _loss = TextEditingController();
  String? _currency;
  ManualLimitCalc? _result;
  String? _error;

  @override
  void initState() {
    super.initState();
    for (final c in [_qty, _cost, _price, _profit, _loss]) {
      c.addListener(_invalidate);
    }
  }

  @override
  void dispose() {
    for (final c in [_qty, _cost, _price, _profit, _loss]) {
      c.dispose();
    }
    super.dispose();
  }

  void _invalidate() {
    if (_result != null || _error != null) setState(() => _clear());
  }

  void _clear() {
    _result = null;
    _error = null;
  }

  void _calculate() {
    final q = parseManualDecimal(_qty.text);
    final c = parseManualDecimal(_cost.text);
    final p = parseManualDecimal(_price.text);
    final t = parseManualDecimal(_profit.text, required: false);
    final l = parseManualDecimal(_loss.text, required: false);
    String? err = q.error != null
        ? 'Adet: ${q.error}'
        : c.error != null
            ? 'Ortalama maliyet: ${c.error}'
            : p.error != null
                ? 'Karşılaştırma fiyatı: ${p.error}'
                : _currency == null
                    ? 'Para birimi seçin'
                    : t.error != null
                        ? 'Kâr hedefi: ${t.error}'
                        : l.error != null
                            ? 'Zarar sınırı: ${l.error}'
                            : null;
    if (err == null && (t.value ?? 0) > 1000) err = 'Kâr hedefi: en fazla %1000';
    if (err == null && (l.value ?? 0) > 100) err = 'Zarar sınırı: en fazla %100';
    setState(() {
      _clear();
      if (err != null) {
        _error = err;
        return;
      }
      _result = ManualLimitCalc(
        quantity: q.value!,
        avgCost: c.value!,
        price: p.value!,
        currency: _currency!,
        profitTargetPct: t.value,
        maxLossPct: l.value,
      );
    });
  }

  Widget _field(Key key, TextEditingController c, String label) => TextField(
        key: key,
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label),
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Manuel hesap', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        const Text(manualNoticeText, key: Key('manual_notice')),
        _field(const Key('manual_qty'), _qty, 'Adet'),
        _field(const Key('manual_cost'), _cost, 'Ortalama birim maliyet'),
        _field(const Key('manual_price'), _price, 'Karşılaştırma fiyatı'),
        DropdownButtonFormField<String>(
          key: const Key('manual_currency'),
          initialValue: _currency,
          decoration: const InputDecoration(labelText: 'Para birimi (maliyet ve fiyat için ortak)'),
          items: [for (final c in manualCurrencies) DropdownMenuItem(value: c, child: Text(c))],
          onChanged: (v) => setState(() {
            _currency = v;
            _clear();
          }),
        ),
        _field(const Key('manual_profit'), _profit, 'Kâr hedefi (%) — isteğe bağlı'),
        _field(const Key('manual_loss'), _loss, 'Zarar sınırı (%) — isteğe bağlı'),
        const SizedBox(height: 8),
        FilledButton.tonal(key: const Key('manual_calc'), onPressed: _calculate, child: const Text('Manuel hesapla')),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_error!, key: const Key('manual_error'), style: TextStyle(color: theme.colorScheme.error)),
          ),
        if (_result != null) _ManualResultView(r: _result!),
      ],
    );
  }
}

class _ManualResultView extends StatelessWidget {
  final ManualLimitCalc r;

  const _ManualResultView({required this.r});

  String _status(String? s) => s == LimitCheckResult.exceeded ? 'aşıldı' : 'sınır içinde';

  @override
  Widget build(BuildContext context) {
    final cur = r.currency;
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        key: const Key('manual_result'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Toplam maliyet: ${formatTr(r.totalCost)} $cur'),
          Text('Karşılaştırma değeri: ${formatTr(r.comparisonValue)} $cur'),
          Text('Fark: ${_signed(r.difference)} $cur'),
          Text('Fark yüzdesi: %${_signed(r.differencePct)}'),
          if (r.targetLevel != null)
            Text('Kâr hedefi %${formatTr(r.profitTargetPct!)} → hedef seviyesi ${formatTr(r.targetLevel!)} $cur — '
                '${_status(r.profitStatus)}'),
          if (r.lossLevel != null)
            Text('Zarar sınırı %${formatTr(r.maxLossPct!)} → sınır seviyesi ${formatTr(r.lossLevel!)} $cur — '
                '${_status(r.lossStatus)}'),
          if (r.targetLevel == null && r.lossLevel == null) const Text('Sınır girilmedi; yalnız fark hesaplandı.'),
          Text('Masraf, vergi ve kurumsal işlemler doğrulanmadı; net satış geliri veya net getiri değildir.',
              style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
