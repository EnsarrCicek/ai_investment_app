import 'package:flutter/material.dart';

import '../../models/strategy_comparison.dart';
import '../../models/strategy_lab_run.dart';
import '../../services/api/asset_api.dart';
import '../../services/api/backtest_api.dart';
import '../../services/api/portfolio_api.dart';

enum _Universe { portfolio, allBist100 }

class _AggregatePresetResult {
  final String preset;
  final double avgReturnPct;
  final double avgWinRatePct;
  final double avgMaxDrawdownPct;
  final int bestCount;
  final int symbolCount;

  _AggregatePresetResult({
    required this.preset,
    required this.avgReturnPct,
    required this.avgWinRatePct,
    required this.avgMaxDrawdownPct,
    required this.bestCount,
    required this.symbolCount,
  });
}

const Map<String, String> _periodLabels = {
  '6mo': '6 Ay',
  '1y': '1 Yıl',
  '2y': '2 Yıl',
  '3y': '3 Yıl',
  '5y': '5 Yıl',
};

/// AŞAMA 57: "Strateji Laboratuvarı" — kullanıcının isteği: "eski tarihe gidip
/// yapay zeka ne kadar doğru AL/SAT diyor test edelim, her yolu deneyip
/// hangisi daha iyi sonuç veriyor diye eğitim yapalım." Yalnızca TEKNİK
/// sinyali kapsar — haber/makro için gerçek bir geçmiş arşivi yok (bkz.
/// KURULUM_GUNLUGU.md AŞAMA 57), bu yüzden bu ekranda test edilemiyor.
/// Beş adlandırılmış ağırlık ön ayarı (backend: strategy_presets.py), seçilen
/// sembol evreninin (Portföy ya da BIST100'ün tamamı) her biri üzerinde
/// çalıştırılır; Dashboard'daki 10'arlı batch deseniyle aynı yöntemle toplu
/// istek atılır (bkz. dashboard_screen.dart) — tüm bağlantıları aynı anda
/// açmak Cloud Run'a karşı bağlantı kopmalarına yol açıyordu.
class StrategyLabScreen extends StatelessWidget {
  const StrategyLabScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Strateji Laboratuvarı'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Yeni Test'),
              Tab(text: 'Geçmiş Testler'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _NewTestTab(),
            _TestHistoryTab(),
          ],
        ),
      ),
    );
  }
}

class _NewTestTab extends StatefulWidget {
  const _NewTestTab();

  @override
  State<_NewTestTab> createState() => _NewTestTabState();
}

class _NewTestTabState extends State<_NewTestTab> {
  static const int _batchSize = 10;

  String _period = '2y';
  _Universe _universe = _Universe.portfolio;
  bool _running = false;
  int _tested = 0;
  int _failed = 0;
  int _totalSymbols = 0;
  List<_AggregatePresetResult>? _aggregateResults;
  String? _error;

  Future<void> _runTest() async {
    setState(() {
      _running = true;
      _aggregateResults = null;
      _error = null;
      _tested = 0;
      _failed = 0;
      _totalSymbols = 0;
    });

    try {
      List<String> symbols;
      if (_universe == _Universe.portfolio) {
        final (positions, _) = await PortfolioApi().fetchPositions();
        symbols = positions.map((p) => p.asset).toSet().toList();
        if (symbols.isEmpty) {
          throw Exception('Portföyünüzde hiç pozisyon yok — önce Portföy ekranından ekleyin ya da "BIST100 (Tümü)" seçin.');
        }
      } else {
        final assets = await AssetApi().fetchAssets();
        symbols = assets.map((a) => a.symbol).toList();
      }

      if (!mounted) return;
      setState(() => _totalSymbols = symbols.length);

      final byPreset = <String, List<StrategyPresetResult>>{};
      final bestCounts = <String, int>{};

      for (var i = 0; i < symbols.length; i += _batchSize) {
        if (!mounted) return;
        final batch = symbols.skip(i).take(_batchSize);
        final batchResults = await Future.wait(
          batch.map((symbol) async {
            try {
              return await BacktestApi().fetchStrategyComparison(symbol, period: _period);
            } catch (_) {
              return null;
            }
          }),
        );
        if (!mounted) return;

        for (final result in batchResults) {
          if (result == null || result.results.isEmpty) {
            setState(() => _failed += 1);
            continue;
          }
          setState(() => _tested += 1);
          final best = result.results.first.preset;
          bestCounts[best] = (bestCounts[best] ?? 0) + 1;
          for (final presetResult in result.results) {
            byPreset.putIfAbsent(presetResult.preset, () => []).add(presetResult);
          }
        }
      }

      final aggregate = byPreset.entries.map((entry) {
        final list = entry.value;
        final avgReturn = list.map((r) => r.totalReturnPct).reduce((a, b) => a + b) / list.length;
        final avgWinRate = list.map((r) => r.winRatePct).reduce((a, b) => a + b) / list.length;
        final avgDrawdown = list.map((r) => r.maxDrawdownPct).reduce((a, b) => a + b) / list.length;
        return _AggregatePresetResult(
          preset: entry.key,
          avgReturnPct: avgReturn,
          avgWinRatePct: avgWinRate,
          avgMaxDrawdownPct: avgDrawdown,
          bestCount: bestCounts[entry.key] ?? 0,
          symbolCount: list.length,
        );
      }).toList()
        ..sort((a, b) => b.avgReturnPct.compareTo(a.avgReturnPct));

      if (!mounted) return;
      setState(() => _aggregateResults = aggregate);

      // AŞAMA 62: "her test yaptığımızda veri tutsun" — sonuç kalıcı olarak
      // kaydedilir. Kaydetme başarısız olsa bile ekrandaki sonucu etkilemesin
      // diye sessizce yutulur (kullanıcının testi tekrar görmesini engellemez).
      try {
        await BacktestApi().saveLabRun(
          period: _period,
          universe: _universe == _Universe.portfolio ? 'PORTFOLIO' : 'BIST100',
          testedCount: _tested,
          failedCount: _failed,
          results: aggregate
              .map((a) => StrategyPresetAggregate(
                    preset: a.preset,
                    avgReturnPct: a.avgReturnPct,
                    avgWinRatePct: a.avgWinRatePct,
                    avgMaxDrawdownPct: a.avgMaxDrawdownPct,
                    bestCount: a.bestCount,
                    symbolCount: a.symbolCount,
                  ))
              .toList(),
        );
      } catch (_) {
        // Test geçmişine kaydedilemedi — sessizce yut, ekrandaki sonucu bozmasın.
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
            color: Colors.blue.withValues(alpha: 0.08),
            child: const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                'Sınırlama: Bu test yalnızca teknik skora (fiyat/gösterge) dayanır — '
                'haber ve makro dahil değildir (Yahoo/Google News geçmiş tarihli haber '
                'arşivi sağlamıyor). Geçmiş performans gelecekteki performansın garantisi '
                'değildir.',
                style: TextStyle(fontSize: 12),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text('Dönem', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            children: _periodLabels.entries
                .map(
                  (e) => ChoiceChip(
                    label: Text(e.value),
                    selected: _period == e.key,
                    onSelected: _running ? null : (_) => setState(() => _period = e.key),
                  ),
                )
                .toList(),
          ),
          const SizedBox(height: 16),
          Text('Sembol Evreni', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          SegmentedButton<_Universe>(
            segments: const [
              ButtonSegment(value: _Universe.portfolio, label: Text('Portföyüm')),
              ButtonSegment(value: _Universe.allBist100, label: Text('BIST100 (Tümü)')),
            ],
            selected: {_universe},
            onSelectionChanged: _running ? null : (s) => setState(() => _universe = s.first),
          ),
          if (_universe == _Universe.allBist100) ...[
            const SizedBox(height: 6),
            const Text(
              'Yaklaşık 100 sembol test edilecek, birkaç dakika sürebilir.',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _running ? null : _runTest,
            icon: _running
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.science_outlined),
            label: Text(_running ? 'Test Ediliyor...' : 'Testi Başlat'),
          ),
          if (_running) ...[
            const SizedBox(height: 12),
            LinearProgressIndicator(
              value: _totalSymbols > 0 ? (_tested + _failed) / _totalSymbols : null,
            ),
            const SizedBox(height: 6),
            Text('${_tested + _failed}/$_totalSymbols sembol test edildi'
                '${_failed > 0 ? ' ($_failed veri hatası)' : ''}'),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text('Hata: $_error', style: const TextStyle(color: Colors.red)),
          ],
          if (_aggregateResults != null) ...[
            const SizedBox(height: 20),
            Text(
              'Sonuçlar ($_tested sembol, $_period)',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
            ),
            if (_failed > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '$_failed sembol için veri alınamadı (atlandı).',
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ),
            const SizedBox(height: 8),
            ..._aggregateResults!.asMap().entries.map(
                  (e) => _StrategyResultCard(rank: e.key + 1, result: e.value),
                ),
        ],
      ],
    );
  }
}

class _StrategyResultCard extends StatelessWidget {
  final int rank;
  final _AggregatePresetResult result;

  const _StrategyResultCard({required this.rank, required this.result});

  @override
  Widget build(BuildContext context) {
    final isWinner = rank == 1;
    final returnColor = result.avgReturnPct >= 0 ? Colors.green : Colors.red;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: isWinner ? Colors.amber.withValues(alpha: 0.12) : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (isWinner) const Padding(
                  padding: EdgeInsets.only(right: 6),
                  child: Icon(Icons.emoji_events, color: Colors.amber, size: 20),
                ),
                Expanded(
                  child: Text(
                    strategyPresetLabelsTr[result.preset] ?? result.preset,
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                  ),
                ),
                Text(
                  '${result.avgReturnPct >= 0 ? '+' : ''}${result.avgReturnPct.toStringAsFixed(2)}%',
                  style: TextStyle(color: returnColor, fontWeight: FontWeight.bold, fontSize: 16),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Ortalama kazanma oranı: %${result.avgWinRatePct.toStringAsFixed(1)} · '
              'Ortalama maks. düşüş: %${result.avgMaxDrawdownPct.toStringAsFixed(1)}',
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
            Text(
              '${result.symbolCount} sembolde test edildi, ${result.bestCount} sembolde en iyi sonucu verdi',
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
          ],
        ),
      ),
    );
  }
}

class _TestHistoryTab extends StatefulWidget {
  const _TestHistoryTab();

  @override
  State<_TestHistoryTab> createState() => _TestHistoryTabState();
}

class _TestHistoryTabState extends State<_TestHistoryTab> {
  late Future<List<StrategyLabRun>> _future;

  @override
  void initState() {
    super.initState();
    _future = BacktestApi().fetchLabRuns();
  }

  Future<void> _refresh() async {
    setState(() => _future = BacktestApi().fetchLabRuns());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<StrategyLabRun>>(
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
          final runs = snapshot.data!;
          if (runs.isEmpty) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: const [
                Padding(
                  padding: EdgeInsets.only(top: 80),
                  child: Center(
                    child: Text(
                      'Henüz kaydedilmiş test yok.\n"Yeni Test" sekmesinden bir tarama çalıştırın.',
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
            itemCount: runs.length,
            itemBuilder: (context, index) => _LabRunCard(run: runs[index]),
          );
        },
      ),
    );
  }
}

class _LabRunCard extends StatelessWidget {
  final StrategyLabRun run;
  const _LabRunCard({required this.run});

  String _fmtDate(DateTime d) {
    final local = d.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.${local.year} $hour:$minute';
  }

  @override
  Widget build(BuildContext context) {
    final universeLabel = run.universe == 'PORTFOLIO' ? 'Portföyüm' : 'BIST100 (Tümü)';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        title: Text(
          '${_periodLabels[run.period] ?? run.period} · $universeLabel',
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Text(
          '${_fmtDate(run.createdAt)} · Kazanan: ${strategyPresetLabelsTr[run.winnerPreset] ?? run.winnerPreset ?? '—'}\n'
          '${run.testedCount} sembol test edildi'
          '${run.failedCount > 0 ? ' (${run.failedCount} veri hatası)' : ''}',
        ),
        children: run.results
            .map(
              (r) => ListTile(
                dense: true,
                title: Text(strategyPresetLabelsTr[r.preset] ?? r.preset),
                subtitle: Text('Kazanma oranı: %${r.avgWinRatePct.toStringAsFixed(1)}'),
                trailing: Text(
                  '${r.avgReturnPct >= 0 ? '+' : ''}${r.avgReturnPct.toStringAsFixed(2)}%',
                  style: TextStyle(
                    color: r.avgReturnPct >= 0 ? Colors.green : Colors.red,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}
