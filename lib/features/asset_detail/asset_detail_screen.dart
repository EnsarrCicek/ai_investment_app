import 'package:flutter/material.dart';

import '../../models/backtest_result.dart';
import '../../models/decision.dart';
import '../../models/news_analysis.dart';
import '../../models/news_item.dart';
import '../../models/price_quote.dart';
import '../../models/technical_analysis.dart';
import '../../services/api/analysis_api.dart';
import '../../services/api/backtest_api.dart';
import '../../services/api/decision_api.dart';
import '../../services/api/market_data_api.dart';
import '../../services/api/news_analysis_api.dart';
import '../../services/api/news_api.dart';
import '../../utils/decision_style.dart';

const Map<String, ({String period, String interval})> _chartPeriods = {
  '1G': (period: '1d', interval: '5m'),
  '1H': (period: '5d', interval: '30m'),
  '1A': (period: '1mo', interval: '1d'),
  '3A': (period: '3mo', interval: '1d'),
  '6A': (period: '6mo', interval: '1d'),
  '1Y': (period: '1y', interval: '1wk'),
};

const Map<String, String> _changeLabels = {
  '1d': '1 Gün',
  '1w': '1 Hafta',
  '1m': '1 Ay',
  '3m': '3 Ay',
  '6m': '6 Ay',
  '1y': '1 Yıl',
};

const Map<String, String> _technicalLabels = {
  'rsi': 'RSI',
  'macd': 'MACD',
  'trend': 'EMA Trend (20/50)',
  'bollinger': 'Bollinger Bantları',
  'momentum': 'Momentum',
  'roc': 'ROC (Değişim Oranı)',
};

class AssetDetailScreen extends StatelessWidget {
  final String symbol;

  const AssetDetailScreen({super.key, required this.symbol});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Scaffold(
        appBar: AppBar(
          title: Text(symbol),
          bottom: const TabBar(
            isScrollable: true,
            tabs: [
              Tab(text: 'Fiyat'),
              Tab(text: 'Teknik'),
              Tab(text: 'Haberler'),
              Tab(text: 'Geçmiş'),
              Tab(text: 'Performans'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _PriceTab(symbol: symbol),
            _TechnicalTab(symbol: symbol),
            _NewsTab(symbol: symbol),
            _HistoryTab(symbol: symbol),
            _PerformanceTab(symbol: symbol),
          ],
        ),
      ),
    );
  }
}

class _TechnicalTab extends StatefulWidget {
  final String symbol;
  const _TechnicalTab({required this.symbol});

  @override
  State<_TechnicalTab> createState() => _TechnicalTabState();
}

class _TechnicalTabState extends State<_TechnicalTab> {
  late Future<TechnicalAnalysisDetail> _future;

  @override
  void initState() {
    super.initState();
    _future = AnalysisApi().fetchTechnical(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<TechnicalAnalysisDetail>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final data = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Teknik Skor: ${data.technicalScore.toStringAsFixed(1)}',
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                        ),
                        Text('Güven: %${data.confidence.toStringAsFixed(0)}'),
                      ],
                    ),
                    Text(data.trend, style: const TextStyle(fontWeight: FontWeight.bold)),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Gösterge Katkıları', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...data.components.entries.map(
              (e) => Card(
                child: ListTile(
                  title: Text(_technicalLabels[e.key] ?? e.key),
                  trailing: Text(
                    '${e.value >= 0 ? '+' : ''}${e.value.toStringAsFixed(1)}',
                    style: TextStyle(
                      color: e.value >= 0 ? Colors.green : Colors.red,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('Ham Gösterge Değerleri', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: data.indicators.entries
                      .map((e) => Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Text('${e.key}: ${e.value}'),
                          ))
                      .toList(),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

const Map<String, String> _eventTypeLabels = {
  'earnings': 'Bilanço/Kâr',
  'regulatory': 'Düzenleyici Karar',
  'corporate_action': 'Kurumsal Eylem',
  'macro': 'Makro Haber',
  'market_sentiment': 'Piyasa Algısı',
  'other': 'Diğer',
};

class _NewsTab extends StatefulWidget {
  final String symbol;
  const _NewsTab({required this.symbol});

  @override
  State<_NewsTab> createState() => _NewsTabState();
}

class _NewsTabState extends State<_NewsTab> {
  late Future<List<NewsItem>> _newsFuture;
  late Future<List<NewsAnalysis>> _analysisFuture;
  bool _analyzing = false;

  @override
  void initState() {
    super.initState();
    _newsFuture = NewsApi().fetchNews(widget.symbol);
    _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
  }

  Future<void> _refresh() async {
    setState(() {
      _newsFuture = NewsApi().fetchNews(widget.symbol);
      _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
    });
    await Future.wait([_newsFuture, _analysisFuture]);
  }

  Future<void> _analyzeNow(int newsCount) async {
    setState(() => _analyzing = true);
    try {
      // Ekrandaki HER haberi kapsayacak şekilde analiz iste — zaten analiz
      // edilmiş olanlar backend'de otomatik atlanır, tekrar maliyet oluşturmaz.
      await NewsAnalysisApi().analyze(widget.symbol, limit: newsCount);
      setState(() {
        _analysisFuture = NewsAnalysisApi().fetchAnalysis(widget.symbol);
      });
      await _analysisFuture;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Analiz hatası: $e')));
      }
    } finally {
      if (mounted) setState(() => _analyzing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<NewsItem>>(
        future: _newsFuture,
        builder: (context, newsSnapshot) {
          if (newsSnapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (newsSnapshot.hasError) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [Center(child: Text('Hata: ${newsSnapshot.error}'))],
            );
          }
          final items = newsSnapshot.data!;
          return FutureBuilder<List<NewsAnalysis>>(
            future: _analysisFuture,
            builder: (context, analysisSnapshot) {
              final analysisById = <String, NewsAnalysis>{
                for (final a in analysisSnapshot.data ?? const <NewsAnalysis>[]) a.newsId: a,
              };
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(12),
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'Haberler, OpenAI GPT-5.6 Luna ile duygu/etki analizi yapılarak gösterilir.',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
                        ),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton.icon(
                        onPressed: _analyzing ? null : () => _analyzeNow(items.length),
                        icon: _analyzing
                            ? const SizedBox(
                                width: 14,
                                height: 14,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.psychology_outlined, size: 18),
                        label: const Text('Analiz Et'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  if (items.isEmpty) const Text('Haber bulunamadı.'),
                  ...items.map((item) => _NewsCard(item: item, analysis: analysisById[item.externalId])),
                ],
              );
            },
          );
        },
      ),
    );
  }
}

class _NewsCard extends StatelessWidget {
  final NewsItem item;
  final NewsAnalysis? analysis;
  const _NewsCard({required this.item, required this.analysis});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => _openUrl(context, item.url),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(item.title, style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 4),
              Text(item.summary, maxLines: 3, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(item.publisher, style: const TextStyle(color: Colors.grey)),
                  Text('Güvenilirlik: %${(item.sourceReliability * 100).toStringAsFixed(0)}'),
                ],
              ),
              const SizedBox(height: 8),
              if (analysis == null)
                const Text(
                  'Bu haber henüz AI ile analiz edilmedi.',
                  style: TextStyle(color: Colors.orange, fontStyle: FontStyle.italic, fontSize: 12),
                )
              else
                _AnalysisBadge(analysis: analysis!),
            ],
          ),
        ),
      ),
    );
  }

  void _openUrl(BuildContext context, String url) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(url)));
  }
}

class _AnalysisBadge extends StatelessWidget {
  final NewsAnalysis analysis;
  const _AnalysisBadge({required this.analysis});

  @override
  Widget build(BuildContext context) {
    // Tek bir haberin duygu skoru, Dashboard'daki AL/TUT/SAT kararıyla AYNI
    // eşiklerle (DecisionEngine.DEFAULT_THRESHOLDS) sınıflandırılır — bu
    // haberin TEK BAŞINA bir varlık kararı olmadığını, yalnızca o haberin
    // yönünü aynı ölçekte gösterdiğini unutmayın.
    final decision = classifyScore(analysis.sentimentScore);
    final color = decisionColor(decision);
    final label = decisionLabel(decision);
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
                child: Text(
                  label,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${_eventTypeLabels[analysis.eventType] ?? analysis.eventType} · '
                  '${analysis.sentimentScore >= 0 ? '+' : ''}${analysis.sentimentScore.toStringAsFixed(0)} puan',
                  style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 13),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Güven %${(analysis.confidence * 100).toStringAsFixed(0)} · Etki %${(analysis.importance * 100).toStringAsFixed(0)}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
          const SizedBox(height: 6),
          Text(analysis.reasoning, style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
        ],
      ),
    );
  }
}

class _HistoryTab extends StatefulWidget {
  final String symbol;
  const _HistoryTab({required this.symbol});

  @override
  State<_HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends State<_HistoryTab> {
  late Future<List<Decision>> _future;

  @override
  void initState() {
    super.initState();
    _future = DecisionApi().fetchHistory(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Decision>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final decisions = snapshot.data!;
        if (decisions.isEmpty) {
          return const Center(child: Text('Henüz bir karar kaydı yok.'));
        }
        return ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: decisions.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) {
            final d = decisions[index];
            final label = decisionLabel(d.decision);
            final color = decisionColor(d.decision);
            return Card(
              child: ListTile(
                title: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold)),
                subtitle: Text('Skor: ${d.finalScore.toStringAsFixed(1)}   Güven: %${d.confidence.toStringAsFixed(0)}'),
                trailing: Text(_fmtDate(d.createdAt)),
              ),
            );
          },
        );
      },
    );
  }

  String _fmtDate(DateTime? date) {
    if (date == null) return '-';
    final local = date.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month $hour:$minute';
  }
}

class _PerformanceTab extends StatefulWidget {
  final String symbol;
  const _PerformanceTab({required this.symbol});

  @override
  State<_PerformanceTab> createState() => _PerformanceTabState();
}

class _PerformanceTabState extends State<_PerformanceTab> {
  late Future<BacktestResult> _future;

  @override
  void initState() {
    super.initState();
    _future = BacktestApi().fetchBacktest(widget.symbol);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<BacktestResult>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Hata: ${snapshot.error}'));
        }
        final r = snapshot.data!;
        final color = r.totalReturnPct >= 0 ? Colors.green : Colors.red;
        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${r.fromDate} — ${r.toDate}', style: const TextStyle(color: Colors.grey)),
                    const SizedBox(height: 8),
                    Text(
                      'Strateji Getirisi: ${r.totalReturnPct >= 0 ? '+' : ''}${r.totalReturnPct.toStringAsFixed(1)}%',
                      style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 18),
                    ),
                    Text(
                      'Al-Tut Getirisi: ${r.buyAndHoldReturnPct >= 0 ? '+' : ''}${r.buyAndHoldReturnPct.toStringAsFixed(1)}%',
                    ),
                    Text('Maksimum Düşüş: ${r.maxDrawdownPct.toStringAsFixed(1)}%'),
                    Text('İşlem Sayısı: ${r.tradeCount}   Kazanma Oranı: %${r.winRatePct.toStringAsFixed(0)}'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text('İşlemler', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            if (r.trades.isEmpty) const Text('Bu dönemde işlem yapılmadı.'),
            ...r.trades.reversed.map(
              (t) => Card(
                child: ListTile(
                  title: Text('${t.entryDate} → ${t.exitDate}'),
                  subtitle: Text('${t.entryPrice.toStringAsFixed(2)} → ${t.exitPrice.toStringAsFixed(2)} TL'),
                  trailing: Text(
                    '${t.returnPct >= 0 ? '+' : ''}${t.returnPct.toStringAsFixed(1)}%',
                    style: TextStyle(
                      color: t.returnPct >= 0 ? Colors.green : Colors.red,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _PriceTab extends StatefulWidget {
  final String symbol;
  const _PriceTab({required this.symbol});

  @override
  State<_PriceTab> createState() => _PriceTabState();
}

class _PriceTabState extends State<_PriceTab> {
  late Future<PriceQuote> _quoteFuture;
  late Future<Map<String, double?>> _changesFuture;
  late Future<List<PriceBar>> _historyFuture;
  String _selectedPeriod = '1A';

  @override
  void initState() {
    super.initState();
    _quoteFuture = MarketDataApi().fetchQuote(widget.symbol);
    _changesFuture = MarketDataApi().fetchChanges(widget.symbol);
    _historyFuture = _fetchHistory();
  }

  Future<List<PriceBar>> _fetchHistory() {
    final opt = _chartPeriods[_selectedPeriod]!;
    return MarketDataApi().fetchHistory(widget.symbol, period: opt.period, interval: opt.interval);
  }

  Future<void> _refresh() async {
    setState(() {
      _quoteFuture = MarketDataApi().fetchQuote(widget.symbol);
      _changesFuture = MarketDataApi().fetchChanges(widget.symbol);
      _historyFuture = _fetchHistory();
    });
    await Future.wait([_quoteFuture, _changesFuture, _historyFuture]);
  }

  void _selectPeriod(String period) {
    setState(() {
      _selectedPeriod = period;
      _historyFuture = _fetchHistory();
    });
  }

  String _fmtTimestamp(DateTime ts) {
    final local = ts.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.${local.year} $hour:$minute';
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<PriceQuote>(
        future: _quoteFuture,
        builder: (context, quoteSnapshot) {
          if (quoteSnapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (quoteSnapshot.hasError) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [Center(child: Text('Hata: ${quoteSnapshot.error}'))],
            );
          }
          final quote = quoteSnapshot.data!;
          final color = quote.change >= 0 ? Colors.green : Colors.red;

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
                      Text(
                        '${quote.lastPrice.toStringAsFixed(2)} TL',
                        style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${quote.change >= 0 ? '+' : ''}${quote.change.toStringAsFixed(2)} '
                        '(${quote.changePercent == null ? '—' : '${quote.changePercent! >= 0 ? '+' : ''}${quote.changePercent!.toStringAsFixed(2)}%'})',
                        style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Önceki kapanış: ${quote.previousClose.toStringAsFixed(2)} TL',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      Text(
                        'Güncelleme: ${_fmtTimestamp(quote.timestamp)} '
                        '(Yahoo Finance, hafif gecikmeli olabilir)',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _MiniStat(label: 'Açılış', value: quote.open.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Yüksek', value: quote.high.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Düşük', value: quote.low.toStringAsFixed(2))),
                  Expanded(child: _MiniStat(label: 'Hacim', value: _fmtVolume(quote.volume))),
                ],
              ),
              const SizedBox(height: 16),
              const Text('Fiyat Grafiği', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: _chartPeriods.keys
                    .map(
                      (p) => ChoiceChip(
                        label: Text(p),
                        selected: _selectedPeriod == p,
                        onSelected: (_) => _selectPeriod(p),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 12),
              FutureBuilder<List<PriceBar>>(
                future: _historyFuture,
                builder: (context, histSnapshot) {
                  if (histSnapshot.connectionState != ConnectionState.done) {
                    return const SizedBox(height: 180, child: Center(child: CircularProgressIndicator()));
                  }
                  if (histSnapshot.hasError) {
                    return SizedBox(height: 180, child: Center(child: Text('Hata: ${histSnapshot.error}')));
                  }
                  final bars = histSnapshot.data!;
                  if (bars.isEmpty) {
                    return const SizedBox(height: 180, child: Center(child: Text('Veri yok')));
                  }
                  final closes = bars.map((b) => b.close).toList();
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _Sparkline(prices: closes, color: color),
                          const SizedBox(height: 8),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                _fmtTimestamp(bars.first.timestamp),
                                style: const TextStyle(fontSize: 11, color: Colors.grey),
                              ),
                              Text(
                                _fmtTimestamp(bars.last.timestamp),
                                style: const TextStyle(fontSize: 11, color: Colors.grey),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(height: 16),
              const Text('Yüzde Değişim', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              FutureBuilder<Map<String, double?>>(
                future: _changesFuture,
                builder: (context, changesSnapshot) {
                  if (changesSnapshot.connectionState != ConnectionState.done) {
                    return const Padding(
                      padding: EdgeInsets.all(8),
                      child: Center(child: CircularProgressIndicator()),
                    );
                  }
                  if (changesSnapshot.hasError) {
                    return Text('Hata: ${changesSnapshot.error}');
                  }
                  final changes = changesSnapshot.data!;
                  return Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: _changeLabels.entries.map((entry) {
                      final pct = changes[entry.key];
                      final pctColor = pct == null ? Colors.grey : (pct >= 0 ? Colors.green : Colors.red);
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                          child: Column(
                            children: [
                              Text(entry.value, style: const TextStyle(fontSize: 11, color: Colors.grey)),
                              Text(
                                pct == null ? 'Veri yok' : '${pct >= 0 ? '+' : ''}${pct.toStringAsFixed(2)}%',
                                style: TextStyle(color: pctColor, fontWeight: FontWeight.bold),
                              ),
                            ],
                          ),
                        ),
                      );
                    }).toList(),
                  );
                },
              ),
            ],
          );
        },
      ),
    );
  }

  String _fmtVolume(int volume) {
    if (volume >= 1000000) return '${(volume / 1000000).toStringAsFixed(1)}M';
    if (volume >= 1000) return '${(volume / 1000).toStringAsFixed(1)}K';
    return volume.toString();
  }
}

class _MiniStat extends StatelessWidget {
  final String label;
  final String value;
  const _MiniStat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 2),
        Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
      ],
    );
  }
}

class _Sparkline extends StatelessWidget {
  final List<double> prices;
  final Color color;
  const _Sparkline({required this.prices, required this.color});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 160,
      width: double.infinity,
      child: CustomPaint(painter: _SparklinePainter(prices: prices, color: color)),
    );
  }
}

class _SparklinePainter extends CustomPainter {
  final List<double> prices;
  final Color color;
  _SparklinePainter({required this.prices, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    if (prices.length < 2) return;
    final minP = prices.reduce((a, b) => a < b ? a : b);
    final maxP = prices.reduce((a, b) => a > b ? a : b);
    final range = (maxP - minP) == 0 ? 1.0 : (maxP - minP);

    final path = Path();
    for (var i = 0; i < prices.length; i++) {
      final x = size.width * i / (prices.length - 1);
      final y = size.height - ((prices[i] - minP) / range) * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }

    final linePaint = Paint()
      ..color = color
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(path, linePaint);

    final fillPath = Path.from(path)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [color.withValues(alpha: 0.25), color.withValues(alpha: 0.0)],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));
    canvas.drawPath(fillPath, fillPaint);
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) =>
      oldDelegate.prices != prices || oldDelegate.color != color;
}
