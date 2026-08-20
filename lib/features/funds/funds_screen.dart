import 'dart:async';

import 'package:flutter/material.dart';

import '../../models/fund_analysis.dart';
import '../../models/fund_position.dart';
import '../../services/api/fund_api.dart';
import 'fund_detail_screen.dart';
import 'fund_style.dart';

/// AŞAMA 58: "Fonlar" sayfası — TEFAS'tan (Türkiye Elektronik Fon Alım Satım
/// Platformu) çekilen gerçek fon verisiyle "hangi fon alınabilir, hangisi en
/// mantıklı" analizini, aylık bütçe önerisini ve tutulan fonlar için
/// değiştirme önerisi bildirimlerini bir araya getirir.
///
/// ÖNEMLİ SINIR: "Ekstra Para Yatır" butonu GERÇEK bir alım YAPMAZ — TEFAS'ta
/// genel kullanıcılar için açık bir işlem-emri API'si yok (bkz.
/// KURULUM_GUNLUGU.md AŞAMA 58). Buton yalnızca o an için en iyi fonlara göre
/// bir dağıtım önerisi hesaplayıp ekranda gösterir ve aynı içerikle bir
/// bildirim gönderir; gerçek alımı kullanıcı kendi banka/aracı kurum
/// uygulamasından yapar.
class FundsScreen extends StatelessWidget {
  const FundsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Fonlar'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Öneriler'),
              Tab(text: 'Fonlarım'),
              Tab(text: 'Ayarlar'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _RecommendationsTab(),
            _MyFundsTab(),
            _SettingsTab(),
          ],
        ),
      ),
    );
  }
}

class _RecommendationsTab extends StatefulWidget {
  const _RecommendationsTab();

  @override
  State<_RecommendationsTab> createState() => _RecommendationsTabState();
}

class _RecommendationsTabState extends State<_RecommendationsTab> {
  static const int _defaultLimit = 30;
  static const int _searchLimit = 200;

  late Future<List<FundAnalysis>> _future;
  bool _allocating = false;
  final _searchController = TextEditingController();
  Timer? _debounce;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _future = FundApi().fetchFunds(limit: _defaultLimit);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() => _future = FundApi().fetchFunds(limit: _defaultLimit, q: _query.isEmpty ? null : _query));
    await _future;
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () {
      setState(() {
        _query = value.trim();
        _future = FundApi().fetchFunds(
          limit: _query.isEmpty ? _defaultLimit : _searchLimit,
          q: _query.isEmpty ? null : _query,
        );
      });
    });
  }

  Future<void> _openAllocateDialog() async {
    final controller = TextEditingController();
    final amount = await showDialog<double>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Ekstra Para Yatır'),
        content: TextField(
          controller: controller,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(labelText: 'Tutar (TL)'),
          autofocus: true,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('İptal')),
          FilledButton(
            onPressed: () {
              final value = double.tryParse(controller.text.replaceAll(',', '.'));
              Navigator.pop(context, value);
            },
            child: const Text('Öneri Al'),
          ),
        ],
      ),
    );
    if (amount == null || amount <= 0 || !mounted) return;

    setState(() => _allocating = true);
    try {
      final allocation = await FundApi().allocate(amount);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Önerilen Dağıtım'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final a in allocation)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text('${a.fundCode} — ${fmtTl(a.amountTl)}\n${a.fundName}',
                      style: const TextStyle(fontSize: 13)),
                ),
              const SizedBox(height: 8),
              const Text(
                'Bu bilgi aynı zamanda bildirim olarak gönderildi. Gerçek alımı kendi '
                'banka/aracı kurum uygulamandan yapman gerekiyor.',
                style: TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ],
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Tamam'))],
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Hata: $e')));
      }
    } finally {
      if (mounted) setState(() => _allocating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<FundAnalysis>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [Padding(padding: const EdgeInsets.all(16), child: Text('Hata: ${snapshot.error}'))],
            );
          }
          final funds = snapshot.data!;
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(12),
            children: [
              TextField(
                controller: _searchController,
                textCapitalization: TextCapitalization.characters,
                onChanged: _onSearchChanged,
                decoration: InputDecoration(
                  hintText: 'Fon kodu veya adı ara (ör. hisse, para piyasası, AAK)...',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searchController.text.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _searchController.clear();
                            _onSearchChanged('');
                          },
                        ),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                  isDense: true,
                ),
              ),
              const SizedBox(height: 12),
              if (_query.isEmpty) ...[
                Card(
                  color: Colors.blue.withValues(alpha: 0.08),
                  child: const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text(
                      'Veri kaynağı: TEFAS. Sıralama, 1a/3a/6a/1y getirilerin ağırlıklı '
                      'ortalamasına dayanır. Bu yatırım tavsiyesi değildir — geçmiş '
                      'performans gelecekteki performansın garantisi değildir; serbest '
                      'fonlar yüksek volatilite taşıyabilir.',
                      style: TextStyle(fontSize: 12),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _allocating ? null : _openAllocateDialog,
                  icon: _allocating
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.savings_outlined),
                  label: Text(_allocating ? 'Hesaplanıyor...' : 'Ekstra Para Yatır'),
                ),
                const SizedBox(height: 16),
              ] else
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text('${funds.length} sonuç bulundu', style: const TextStyle(color: Colors.grey, fontSize: 12)),
                ),
              if (funds.isEmpty) const Text('Fon bulunamadı.'),
              ...funds.map((f) => _FundCard(fund: f)),
            ],
          );
        },
      ),
    );
  }
}

class _FundCard extends StatelessWidget {
  final FundAnalysis fund;
  const _FundCard({required this.fund});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (context) => FundDetailScreen(fundCode: fund.fundCode)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${fund.fundCode} — ${fund.fundName}',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Text(
                    fund.compositeScore.toStringAsFixed(1),
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                      color: fund.compositeScore >= 0 ? Colors.green : Colors.red,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _ReturnBadge(label: '1A', value: fund.return1mPct),
                  _ReturnBadge(label: '3A', value: fund.return3mPct),
                  _ReturnBadge(label: '6A', value: fund.return6mPct),
                  _ReturnBadge(label: '1Y', value: fund.return1yPct),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  if (fund.riskLevel != null)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: riskColor(fund.riskLevel).withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        'Risk: ${fundRiskLabelsTr[fund.riskLevel] ?? fund.riskLevel}',
                        style: TextStyle(
                          color: riskColor(fund.riskLevel),
                          fontWeight: FontWeight.bold,
                          fontSize: 11,
                        ),
                      ),
                    ),
                  const Spacer(),
                  Text('Fiyat: ${fund.price.toStringAsFixed(4)} TL', style: const TextStyle(fontSize: 11, color: Colors.grey)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReturnBadge extends StatelessWidget {
  final String label;
  final double? value;
  const _ReturnBadge({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 10, color: Colors.grey)),
        Text(fmtPct(value), style: TextStyle(fontWeight: FontWeight.bold, color: pctColor(value), fontSize: 12)),
      ],
    );
  }
}

class _MyFundsTab extends StatefulWidget {
  const _MyFundsTab();

  @override
  State<_MyFundsTab> createState() => _MyFundsTabState();
}

class _MyFundsTabState extends State<_MyFundsTab> {
  late Future<List<FundPosition>> _future;

  @override
  void initState() {
    super.initState();
    _future = FundApi().fetchPositions();
  }

  Future<void> _refresh() async {
    setState(() => _future = FundApi().fetchPositions());
    await _future;
  }

  Future<void> _openAddDialog() async {
    final codeController = TextEditingController();
    final unitsController = TextEditingController();
    final costController = TextEditingController();

    final added = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Fon Ekle'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: codeController,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(labelText: 'Fon Kodu (ör. AAK)'),
            ),
            TextField(
              controller: unitsController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Pay Adedi'),
            ),
            TextField(
              controller: costController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Ortalama Maliyet (TL/pay)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('İptal')),
          FilledButton(
            onPressed: () async {
              final code = codeController.text.trim().toUpperCase();
              final units = double.tryParse(unitsController.text.replaceAll(',', '.'));
              final cost = double.tryParse(costController.text.replaceAll(',', '.'));
              if (code.isEmpty || units == null || cost == null) return;
              try {
                await FundApi().addPosition(fundCode: code, units: units, avgCost: cost);
                if (context.mounted) Navigator.pop(context, true);
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Hata: $e')));
                }
              }
            },
            child: const Text('Ekle'),
          ),
        ],
      ),
    );
    if (added == true) await _refresh();
  }

  Future<void> _delete(String fundCode) async {
    try {
      await FundApi().deletePosition(fundCode);
      await _refresh();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Hata: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton(onPressed: _openAddDialog, child: const Icon(Icons.add)),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<List<FundPosition>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [Padding(padding: const EdgeInsets.all(16), child: Text('Hata: ${snapshot.error}'))],
              );
            }
            final positions = snapshot.data!;
            if (positions.isEmpty) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: const [
                  Padding(
                    padding: EdgeInsets.only(top: 80),
                    child: Center(
                      child: Text(
                        'Henüz fon eklemediniz.\nSağ alttaki + butonuyla ekleyebilirsiniz.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ],
              );
            }
            return ListView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(12),
              itemCount: positions.length,
              itemBuilder: (context, index) {
                final p = positions[index];
                return Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    onTap: () => Navigator.push(
                      context,
                      MaterialPageRoute(builder: (context) => FundDetailScreen(fundCode: p.fundCode)),
                    ),
                    title: Text(p.fundCode, style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text(
                      '${p.units.toStringAsFixed(2)} pay · Maliyet: ${p.avgCost.toStringAsFixed(2)} TL\n'
                      '${p.currentValue == null ? 'Güncel fiyat alınamadı' : 'Değer: ${fmtTl(p.currentValue!)} · '
                          'Kâr/Zarar: ${fmtPct(p.profitLossPct)}'}',
                    ),
                    isThreeLine: true,
                    trailing: IconButton(
                      icon: const Icon(Icons.delete_outline, color: Colors.red),
                      onPressed: () => _delete(p.fundCode),
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

class _SettingsTab extends StatefulWidget {
  const _SettingsTab();

  @override
  State<_SettingsTab> createState() => _SettingsTabState();
}

class _SettingsTabState extends State<_SettingsTab> {
  late Future<FundInvestmentSettings> _future;
  final _incomeController = TextEditingController();
  final _budgetController = TextEditingController();
  bool _saving = false;
  bool _loadingPreview = false;
  List<FundAllocationItem>? _preview;
  String? _previewError;

  @override
  void initState() {
    super.initState();
    _future = FundApi().fetchSettings().then((settings) {
      _incomeController.text = settings.monthlyIncome?.toStringAsFixed(0) ?? '';
      _budgetController.text = settings.monthlyBudget.toStringAsFixed(0);
      if (settings.monthlyBudget > 0) _loadPreview(settings.monthlyBudget);
      return settings;
    });
  }

  @override
  void dispose() {
    _incomeController.dispose();
    _budgetController.dispose();
    super.dispose();
  }

  Future<void> _loadPreview(double budget) async {
    setState(() {
      _loadingPreview = true;
      _previewError = null;
    });
    try {
      final preview = await FundApi().previewAllocation(budget);
      if (mounted) setState(() => _preview = preview);
    } catch (e) {
      if (mounted) setState(() => _previewError = e.toString());
    } finally {
      if (mounted) setState(() => _loadingPreview = false);
    }
  }

  Future<void> _save() async {
    final income = double.tryParse(_incomeController.text.replaceAll(',', '.'));
    final budget = double.tryParse(_budgetController.text.replaceAll(',', '.')) ?? 0.0;
    setState(() => _saving = true);
    try {
      await FundApi().updateSettings(monthlyIncome: income, monthlyBudget: budget);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Kaydedildi')));
      }
      if (budget > 0) {
        await _loadPreview(budget);
      } else if (mounted) {
        setState(() => _preview = null);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Hata: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<FundInvestmentSettings>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'Aylık gelirini ve fonlara ayırmak istediğin tutarı gir. Her ay bu bütçeyi '
              'o anki en iyi fonlara dağıtan bir bildirim gönderilir — uygulamayı o ay '
              'içinde ilk açtığında (bu projede arka plan zamanlayıcısı yok).',
              style: TextStyle(fontSize: 13, color: Colors.grey),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _incomeController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Aylık Gelir (opsiyonel, TL)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _budgetController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                labelText: 'Aylık Yatırım Bütçesi (TL)',
                border: OutlineInputBorder(),
                helperText: 'Aylık bildirim için kullanılan tutar budur.',
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Kaydet'),
            ),
            const SizedBox(height: 20),
            if (_loadingPreview) const Center(child: CircularProgressIndicator())
            else if (_previewError != null)
              Text('Önizleme alınamadı: $_previewError', style: const TextStyle(color: Colors.red))
            else if (_preview != null && _preview!.isNotEmpty) ...[
              Text('Bu bütçe şöyle dağıtılır', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 4),
              const Text(
                'Dağıtım, her fonun güven/kâr potansiyeli skoruna orantılıdır — skoru '
                'yüksek olan fon daha büyük pay alır.',
                style: TextStyle(fontSize: 12, color: Colors.grey),
              ),
              const SizedBox(height: 8),
              for (final a in _preview!)
                Card(
                  margin: const EdgeInsets.only(bottom: 6),
                  child: ListTile(
                    dense: true,
                    title: Text('${a.fundCode} — ${fmtTl(a.amountTl)}',
                        style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text(a.fundName, maxLines: 1, overflow: TextOverflow.ellipsis),
                    trailing: Text(
                      a.compositeScore.toStringAsFixed(1),
                      style: TextStyle(color: a.compositeScore >= 0 ? Colors.green : Colors.red),
                    ),
                  ),
                ),
            ],
          ],
        );
      },
    );
  }
}
